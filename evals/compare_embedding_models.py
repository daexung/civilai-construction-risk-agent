"""Compare 2+ model-specific hybrid indexes on legacy and/or draft-derived questions."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.nodes.select import MARGIN, decide  # noqa: E402
from backend.agent.rules.specs import specs_by_section  # noqa: E402
from backend.agent.tools.search.hybrid import HybridIndex  # noqa: E402
from evals.check_select import classify, questions as select_questions  # noqa: E402
from backend.shared.embedding import query_input, rate_limit_error, sha256  # noqa: E402

RAG_QUESTIONS = ROOT / "evals/rag_questions.json"
DRAFT_QUESTIONS = ROOT / "evals/draft_questions.jsonl"
RESULTS = ROOT / "evals/results"
QUERY_CACHE = RESULTS / "embedding_query_cache.jsonl"


class QueryCache:
    """Persist successful query vectors so interrupted comparisons can resume."""

    def __init__(self, path: Path = QUERY_CACHE, pause: float = 0,
                 sleep_fn=time.sleep, clock_fn=time.monotonic):
        if pause < 0:
            raise ValueError("--pause는 0 이상이어야 합니다")
        self.path, self.pause = path, pause
        self.sleep_fn, self.clock_fn = sleep_fn, clock_fn
        self.last_call: float | None = None
        self.rows = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue  # An interrupted append must not discard earlier results.
                key = (row["provider"], row["model"], row["dim"], row["query_sha256"])
                self.rows[key] = row["vector"]

    def embed(self, index: HybridIndex, query: str, original) -> np.ndarray:
        config = index.vector.embedding
        key = (config.provider, config.model, config.dim, sha256(query_input(query, config)))
        if key in self.rows:
            vector = np.asarray(self.rows[key], dtype=np.float32)
            if len(vector) != config.dim or not np.all(np.isfinite(vector)):
                raise ValueError(f"손상된 질문 임베딩 캐시: {config.model}")
            return vector
        for attempt in range(4):  # Initial call plus at most three 429 retries.
            if self.last_call is not None:
                remaining = self.pause - (self.clock_fn() - self.last_call)
                if remaining > 0:
                    self.sleep_fn(remaining)
            self.last_call = self.clock_fn()
            try:
                vector = original(query)
                break
            except Exception as exc:
                if not rate_limit_error(exc) or attempt == 3:
                    raise
                self.sleep_fn(60)
                self.last_call = self.clock_fn() - self.pause
        row = {"provider": key[0], "model": key[1], "dim": key[2],
               "query_sha256": key[3], "vector": vector.tolist()}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.rows[key] = row["vector"]
        return vector


def _top(hit: dict | None) -> dict | None:
    if hit is None:
        return None
    division = hit.get("division", "공통")
    return {"division": division, "section_no": hit.get("section_no"),
            "label": f"{division} {hit['section']}" if division else hit["section"]}


def _search(index: HybridIndex, query: str, cache: dict, k: int = 10) -> list[dict]:
    if query not in cache:
        cache[query] = [chunk for _score, chunk in index.search(query, k)]
    return cache[query]


def _select_result(case: dict, chunks: list[dict], specs: dict) -> dict:
    hits = [{"rank": rank, "section_no": chunk.get("section_no"),
             "division": chunk.get("division", "공통"), "section": chunk["section"]}
            for rank, chunk in enumerate(chunks, 1)]
    decision = decide(hits, specs, MARGIN)
    outcome = classify(case["expect"], decision) if decision["candidates"] else "ask"
    return {"top": _top(chunks[0] if chunks else None), "decision": decision["decision"],
            "outcome": outcome,
            "correct": outcome == ("ask" if case["expect"] == "ask" else "correct")}


def legacy_questions() -> list[dict]:
    rag = json.loads(RAG_QUESTIONS.read_text(encoding="utf-8"))
    rows = [{"id": item["id"], "kind": "legacy", "query": item["query"],
             "division": "공통", "section_no": item["expect_section"]}
            for item in rag["questions"] + rag["evidence_checks"]]
    rows += [{"id": item["id"], "kind": "legacy", "query": None,
              "division": "공통", "section_no": item["section"],
              "skip_reason": "적산 사례에 검색 질문이 없음"} for item in rag["estimates"]]
    return rows


def draft_questions(scope: str | None) -> list[dict]:
    if not DRAFT_QUESTIONS.exists():
        return []
    rows = []
    for line in DRAFT_QUESTIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if scope and not f"{item['division']}/{item['section_no']}".startswith(scope):
            continue
        rows.append({"id": item["id"], "kind": "draft", "query": item["question"],
                     "division": item["division"], "section_no": item["section_no"]})
    return rows


def _rank_hit(chunks: list[dict], division: str, section_no: str, top_k: int) -> bool:
    for chunk in chunks[:top_k]:
        if chunk.get("division", "공통") == division and chunk.get("section_no") == section_no:
            return True
    return False


def compare(config_paths: list[Path], *, questions: str = "both", scope: str | None = None,
            pause: float = 0, query_cache_path: Path = QUERY_CACHE) -> dict:
    if len(config_paths) < 2:
        raise ValueError("설정 파일은 2개 이상이어야 합니다")
    names = [chr(ord("A") + i) for i in range(len(config_paths))]
    indexes = {name: HybridIndex(config_path=path) for name, path in zip(names, config_paths)}
    models = {index.vector.embedding.model for index in indexes.values()}
    if len(models) != len(indexes):
        raise ValueError("설정들이 서로 다른 임베딩 모델이어야 합니다")
    chunk_orders = {tuple(chunk["chunk_id"] for chunk in index.chunks) for index in indexes.values()}
    if len(chunk_orders) != 1 or len(next(iter(chunk_orders))) != 175:
        raise ValueError("설정들의 청크 목록이 다릅니다")
    for name, index in indexes.items():
        if index.vector.stale or index.vector.missing:
            raise ValueError(f"{name} 색인 벡터가 미완성입니다: stale {len(index.vector.stale)}, "
                             f"missing {len(index.vector.missing)}")

    query_cache = QueryCache(query_cache_path, pause)
    for index in indexes.values():
        original = index.vector.embed_query
        index.vector.embed_query = lambda query, index=index, original=original: query_cache.embed(index, query, original)
    caches = {name: {} for name in indexes}
    specs = specs_by_section()

    retrieval_cases = []
    if questions in ("legacy", "both"):
        retrieval_cases += legacy_questions()
    if questions in ("draft", "both"):
        retrieval_cases += draft_questions(scope)

    retrieval_rows = []
    for case in retrieval_cases:
        row = {"id": case["id"], "kind": case["kind"], "query": case["query"],
               "expected": {"division": case["division"], "section_no": case["section_no"]}}
        if "skip_reason" in case:
            row["skip_reason"] = case["skip_reason"]
            for name in indexes:
                row[name] = {"top": None, "top1": None, "top3": None}
            retrieval_rows.append(row)
            continue
        for name, index in indexes.items():
            chunks = _search(index, case["query"], caches[name])
            row[name] = {"top": _top(chunks[0] if chunks else None),
                         "top1": _rank_hit(chunks, case["division"], case["section_no"], 1),
                         "top3": _rank_hit(chunks, case["division"], case["section_no"], 3)}
        retrieval_rows.append(row)

    select_rows = []
    for case in select_questions():
        row = {"id": case["id"], "query": case["query"], "expected": case["expect"]}
        for name, index in indexes.items():
            row[name] = _select_result(case, _search(index, case["query"], caches[name]), specs)
        select_rows.append(row)

    summary = {}
    for name, index in indexes.items():
        searchable = [row for row in retrieval_rows if row[name]["top1"] is not None]
        summary[name] = {
            "model": index.vector.embedding.model, "provider": index.vector.embedding.provider,
            "retrieval_total": len(retrieval_rows), "retrieval_searchable": len(searchable),
            "top1_correct": sum(row[name]["top1"] for row in searchable),
            "top3_correct": sum(row[name]["top3"] for row in searchable),
            "select_correct": sum(row[name]["outcome"] == "correct" for row in select_rows),
            "select_wrong": sum(row[name]["outcome"] == "wrong" for row in select_rows),
            "select_ask": sum(row[name]["outcome"] == "ask" for row in select_rows),
            "select_total": len(select_rows), "api_calls": index.api_calls,
        }
    return {"date": date.today().isoformat(), "questions": questions, "scope": scope,
            "configs": {name: str(path) for name, path in zip(names, config_paths)},
            "summary": summary, "retrieval": retrieval_rows, "select": select_rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configs", type=Path, nargs="+", help="비교할 색인 설정 파일(2개 이상)")
    parser.add_argument("--questions", choices=("legacy", "draft", "both"), default="both")
    parser.add_argument("--scope", help="초안 질문의 부문/절 접두어 필터, 예: 공통/6-")
    parser.add_argument("--pause", type=float, default=0, help="새 질문 임베딩 호출 사이 대기(초)")
    args = parser.parse_args()
    result = compare(args.configs, questions=args.questions, scope=args.scope, pause=args.pause)
    names = list(result["configs"])
    for row in result["retrieval"]:
        cells = " | ".join(f"{name} {row[name]['top']['label'] if row[name]['top'] else '-'} "
                           f"(top1={row[name]['top1']}, top3={row[name]['top3']})" for name in names)
        print(f"retrieval {row['kind']} {row['id']}: {cells}")
    for row in result["select"]:
        cells = " | ".join(f"{name} {row[name]['top']['label'] if row[name]['top'] else '-'} "
                           f"({row[name]['correct']})" for name in names)
        print(f"select {row['id']}: {cells}")
    for name, summary in result["summary"].items():
        print(f"{name} {summary['model']}: top1 {summary['top1_correct']}/{summary['retrieval_searchable']} "
              f"(전체 {summary['retrieval_total']}), top3 {summary['top3_correct']}/{summary['retrieval_searchable']}; "
              f"select 정답 {summary['select_correct']}, 오답 {summary['select_wrong']}, "
              f"되묻기 {summary['select_ask']}/{summary['select_total']}")
    RESULTS.mkdir(parents=True, exist_ok=True)
    scope_tag = (args.scope or "all").replace("/", "-")
    output = RESULTS / f"embedding_compare_{date.today():%Y%m%d}_{scope_tag}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"저장: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
