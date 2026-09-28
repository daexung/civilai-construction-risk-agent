"""Compare two model-specific hybrid indexes on unchanged RAG and select questions."""

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

from agent.nodes.select import MARGIN, decide  # noqa: E402
from agent.rules.specs import specs_by_section  # noqa: E402
from agent.tools.search.hybrid import HybridIndex  # noqa: E402
from evals.check_select import classify, questions as select_questions  # noqa: E402
from shared.embedding import query_input, rate_limit_error, sha256  # noqa: E402

RAG_QUESTIONS = ROOT / "evals/rag_questions.json"
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


def _search(index: HybridIndex, query: str, cache: dict) -> list[dict]:
    if query not in cache:
        cache[query] = [chunk for _score, chunk in index.search(query, 10)]
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


def compare(a_path: Path, b_path: Path, *, pause: float = 0,
            query_cache_path: Path = QUERY_CACHE) -> dict:
    indexes = {"A": HybridIndex(config_path=a_path), "B": HybridIndex(config_path=b_path)}
    if len({index.vector.embedding.model for index in indexes.values()}) != 2:
        raise ValueError("A와 B가 서로 다른 임베딩 모델이어야 합니다")
    chunk_orders = {tuple(chunk["chunk_id"] for chunk in index.chunks) for index in indexes.values()}
    if len(chunk_orders) != 1 or len(next(iter(chunk_orders))) != 175:
        raise ValueError("A와 B의 청크 목록이 다릅니다")
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
    rag = json.loads(RAG_QUESTIONS.read_text(encoding="utf-8"))
    rag_rows = []
    for item in rag["questions"] + rag["evidence_checks"]:
        row = {"id": item["id"], "query": item["query"],
               "expected": {"division": "공통", "section_no": item["expect_section"]}}
        for name, index in indexes.items():
            chunks = _search(index, item["query"], caches[name])
            top = _top(chunks[0] if chunks else None)
            row[name] = {"top": top, "correct": bool(top and top["division"] == "공통"
                                                        and top["section_no"] == item["expect_section"])}
        rag_rows.append(row)
    for item in rag["estimates"]:
        rag_rows.append({"id": item["id"], "query": None,
                         "expected": {"division": "공통", "section_no": item["section"]},
                         "A": {"top": None, "correct": None}, "B": {"top": None, "correct": None},
                         "skip_reason": "적산 사례에 검색 질문이 없음"})

    select_rows = []
    for case in select_questions():
        row = {"id": case["id"], "query": case["query"], "expected": case["expect"]}
        for name, index in indexes.items():
            row[name] = _select_result(case, _search(index, case["query"], caches[name]), specs)
        select_rows.append(row)

    summary = {}
    for name, index in indexes.items():
        summary[name] = {
            "model": index.vector.embedding.model, "provider": index.vector.embedding.provider,
            "rag_correct": sum(row[name]["correct"] is True for row in rag_rows),
            "rag_searchable": sum(row[name]["correct"] is not None for row in rag_rows),
            "rag_total": len(rag_rows),
            "select_correct": sum(row[name]["outcome"] == "correct" for row in select_rows),
            "select_wrong": sum(row[name]["outcome"] == "wrong" for row in select_rows),
            "select_ask": sum(row[name]["outcome"] == "ask" for row in select_rows),
            "select_total": len(select_rows), "api_calls": index.api_calls,
        }
    return {"date": date.today().isoformat(), "configs": {"A": str(a_path), "B": str(b_path)},
            "summary": summary, "rag": rag_rows, "select": select_rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("A", type=Path)
    parser.add_argument("B", type=Path)
    parser.add_argument("--pause", type=float, default=0, help="새 질문 임베딩 호출 사이 대기(초)")
    args = parser.parse_args()
    result = compare(args.A, args.B, pause=args.pause)
    for group in ("rag", "select"):
        for row in result[group]:
            a, b = row["A"], row["B"]
            a_top = a["top"]["label"] if a["top"] else "-"
            b_top = b["top"]["label"] if b["top"] else "-"
            print(f"{group} {row['id']}: A {a_top} ({a['correct']}) | B {b_top} ({b['correct']})")
    for name, summary in result["summary"].items():
        print(f"{name} {summary['model']}: RAG {summary['rag_correct']}/{summary['rag_searchable']} "
              f"(전체 {summary['rag_total']}); select 오답 {summary['select_wrong']}, "
              f"되묻기 {summary['select_ask']}/{summary['select_total']}")
    RESULTS.mkdir(parents=True, exist_ok=True)
    output = RESULTS / f"embedding_compare_{date.today():%Y%m%d}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"저장: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
