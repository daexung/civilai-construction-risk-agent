"""Measure service-scope retrieval and selection on a fixed stratified draft sample.

Offline: python evals/check_scope.py --mode bm25
Reviewer only (query embedding API): python evals/check_scope.py --mode hybrid
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.nodes.route import route  # noqa: E402
from backend.agent.nodes.select import decide  # noqa: E402
from backend.agent.rules.scope import enabled_divisions  # noqa: E402
from backend.agent.rules.misfiled import misfiled_sections  # noqa: E402
from backend.agent.rules.specs import specs_by_section  # noqa: E402
from backend.agent.state import new_state  # noqa: E402
from backend.agent.nodes.retrieve import make_search_index  # noqa: E402

SOURCE = ROOT / "evals/draft_questions.jsonl"
SAMPLE = ROOT / "evals/scope_sample.jsonl"
RESULTS = ROOT / "evals/results"
SEED = 181
SAMPLE_SIZE = 300


def make_sample() -> list[dict]:
    divisions = enabled_divisions()
    grouped: dict[str, list[dict]] = {division: [] for division in divisions}
    excluded = misfiled_sections()
    for line in SOURCE.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("division") in grouped and (row["division"], row["section_no"]) not in excluded:
            grouped[row["division"]].append(row)
    total = sum(map(len, grouped.values()))
    if total < SAMPLE_SIZE or any(not values for values in grouped.values()):
        raise ValueError("켜진 부문의 질문 표본이 부족합니다")
    exact = {division: SAMPLE_SIZE * len(grouped[division]) / total for division in divisions}
    quota = {division: int(exact[division]) for division in divisions}
    remain = SAMPLE_SIZE - sum(quota.values())
    for division in sorted(divisions, key=lambda key: (-(exact[key] - quota[key]), key))[:remain]:
        quota[division] += 1
    rng = random.Random(SEED)
    selected = []
    for division in divisions:
        for row in rng.sample(grouped[division], quota[division]):
            selected.append({key: row[key] for key in ("id", "question", "division", "section_no")})
    return sorted(selected, key=lambda row: row["id"])


def _hits(index, query: str) -> list[dict]:
    return [{"rank": rank, "chunk_id": chunk["chunk_id"],
             "division": chunk.get("division"), "section_no": chunk.get("section_no"),
             "section": chunk["section"]}
            for rank, (_score, chunk) in enumerate(index.search(query, 10), 1)]


def evaluate(mode: str, sample: list[dict]) -> dict:
    os.environ.pop("INDEX_CONFIG", None)
    index, method, warning = make_search_index(offline=mode == "bm25")
    if mode == "hybrid" and (method != "hybrid" or warning):
        raise RuntimeError(f"하이브리드 색인을 준비하지 못했습니다: {warning}")
    specs = specs_by_section()
    rows = []
    for case in sample:
        passed = route(new_state(case["question"])) == {}
        before = getattr(index, "api_calls", 0)
        hits = _hits(index, case["question"]) if passed else []
        if mode == "hybrid" and (getattr(index, "used", None) != "hybrid" or
                                 getattr(index, "api_calls", 0) - before < 1):
            raise RuntimeError(f"{case['id']}: 하이브리드 질의 실패 또는 API 호출 없음")
        expected = (case["division"], case["section_no"])
        top_sections = list(dict.fromkeys((hit["division"], hit["section_no"]) for hit in hits))
        choice = decide(hits, specs)
        selected = choice["candidates"][0] if choice["candidates"] else None
        chosen = ((selected["division"], selected["section_no"]) if selected else None)
        confirmed = choice["decision"] in ("chosen", "no_spec")
        outcome = ("correct" if chosen == expected else "wrong") if confirmed else "ask"
        confusion = any(hit["section_no"] == case["section_no"] and
                        hit["division"] != case["division"] for hit in hits)
        rows.append({"id": case["id"], "division": case["division"],
                     "section_no": case["section_no"], "route_pass": passed,
                     "top1_correct": bool(top_sections) and top_sections[0] == expected,
                     "top3_correct": expected in top_sections[:3],
                     "select": outcome, "same_number_other_division": confusion,
                     "selected": chosen, "decision": choice["decision"]})
    def metrics(items: list[dict]) -> dict:
        return {"total": len(items), "route_pass": sum(x["route_pass"] for x in items),
                "top1_correct": sum(x["top1_correct"] for x in items),
                "top3_correct": sum(x["top3_correct"] for x in items),
                "select_correct": sum(x["select"] == "correct" for x in items),
                "select_wrong": sum(x["select"] == "wrong" for x in items),
                "select_ask": sum(x["select"] == "ask" for x in items),
                "same_number_other_division": sum(x["same_number_other_division"] for x in items)}
    return {"mode": mode, "date": date.today().isoformat(), "seed": SEED,
            "sample_size": len(sample), "method": method, "summary": metrics(rows),
            "by_division": {division: metrics([x for x in rows if x["division"] == division])
                            for division in enabled_divisions()}, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("bm25", "hybrid"), default="bm25")
    parser.add_argument("--refresh-sample", action="store_true",
                        help="Refresh the committed sample after correcting source divisions")
    args = parser.parse_args()
    generated = make_sample()
    if SAMPLE.exists() and not args.refresh_sample:
        sample = [json.loads(line) for line in SAMPLE.read_text(encoding="utf-8").splitlines() if line]
        if sample != generated:
            raise ValueError("고정 표본이 현재 부문 설정 또는 원본 질문과 다릅니다")
    else:
        sample = generated
        SAMPLE.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in sample) + "\n",
                          encoding="utf-8")
    result = evaluate(args.mode, sample)
    RESULTS.mkdir(parents=True, exist_ok=True)
    output = RESULTS / f"scope_{args.mode}_{result['date'].replace('-', '')}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = ("total", "route_pass", "top1_correct", "top3_correct", "select_correct",
               "select_wrong", "select_ask", "same_number_other_division")
    print("division | " + " | ".join(columns))
    for division, metrics in [*result["by_division"].items(), ("전체", result["summary"])]:
        print(division + " | " + " | ".join(str(metrics[key]) for key in columns))
    print(output.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
