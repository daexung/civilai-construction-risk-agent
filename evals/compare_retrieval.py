"""기존 질문 세트로 BM25와 벡터 검색(gemini-embedding-2, 정확한 코사인)을 비교한다.

실행: python evals/compare_retrieval.py
두 방식 모두 rag.evidence로 같은 절 단위 근거를 만든다. 벡터 쪽은 질문마다 임베딩 API를 1회 호출한다.
q06은 원본 파싱에서 표(p193-t1)가 빠진 문제라 검색 방식과 무관한 실패로 따로 표시한다.
결과: data/processed/retrieval_compare.jsonl (커밋하지 않는 생성물)
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from rag import CHUNKS, Index, evidence, evidence_chunk_ids, load  # noqa: E402
from vector import VectorIndex  # noqa: E402

QUESTIONS = Path(__file__).with_name("rag_questions.json")
OUT = ROOT / "data/processed/retrieval_compare.jsonl"
PARSER_GAPS = {"q06": "원본 파싱에서 193쪽 사용횟수 표(p193-t1)가 레코드 0개. 검색 방식과 무관"}


def judge(item: dict, ev: dict) -> dict:
    hit_nos = [c["section_no"] for _, c in ev["hits"]]
    texts = [c["text"] for g in ev["sections"] + ev["parents"] for c in g["chunks"]]
    ids = evidence_chunk_ids(ev)
    out = {"top3": [c["chunk_id"] for _, c in ev["hits"]], "top3_sections": hit_nos,
           "section_in_top3": item["expect_section"] in hit_nos,
           "top1_is_expected": bool(hit_nos) and hit_nos[0] == item["expect_section"],
           "no_duplicate_chunks": len(ids) == len(set(ids)),
           "evidence_sections": [g["section_no"] for g in ev["sections"]],
           "evidence_parents": [g["section_no"] for g in ev["parents"]]}
    if item.get("must_contain"):
        out["must_contain"] = any(item["must_contain"] in t for t in texts)
    if item.get("expect_parent"):
        # 상위 절이 검색 상위에 직접 올라오면 '선택된 절'로 한 번 담기고 상위 절 칸에는 없다. 합쳐서 정확히 한 번이면 된다
        out["parent_once"] = (out["evidence_parents"] + out["evidence_sections"]).count(item["expect_parent"]) == 1
    if item.get("whole_section_once"):
        out["section_once"] = out["evidence_sections"].count(item["expect_section"]) == 1
    passed = [v for k, v in out.items() if isinstance(v, bool) and k != "top1_is_expected"]
    out["pass"] = all(passed)
    return out


def main() -> int:
    spec = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    items = spec["questions"] + spec.get("evidence_checks", [])
    bm25 = Index(load(CHUNKS))
    vec = VectorIndex()
    if vec.stale or vec.missing:
        raise SystemExit(f"벡터가 청크와 맞지 않는다(옛 {len(vec.stale)}, 없음 {len(vec.missing)}). embed.py를 다시 실행")

    rows = []
    for item in items:
        started = time.perf_counter()
        ev_b = evidence(bm25, item["query"], 3)
        t_b = time.perf_counter() - started

        calls_before = vec.api_calls
        started = time.perf_counter()
        ev_v = evidence(vec, item["query"], 3)
        t_v = time.perf_counter() - started
        row = {"id": item["id"], "query": item["query"], "expect_section": item["expect_section"],
               "parser_gap": PARSER_GAPS.get(item["id"]),
               "bm25": {**judge(item, ev_b), "sec": round(t_b, 4), "api_calls": 0},
               "vector": {**judge(item, ev_v), "sec": round(t_v, 3), "embed_sec": round(vec.last_embed_sec, 3),
                          "api_calls": vec.api_calls - calls_before}}
        rows.append(row)
        time.sleep(0.5)

    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    print(f"{'id':4} {'기대':7} | {'BM25 상위3 절':28} {'판정':4} {'초':>7} | {'벡터 상위3 절':28} {'판정':4} {'초':>6} 호출")
    for r in rows:
        b, v = r["bm25"], r["vector"]
        mark = lambda x: "PASS" if x["pass"] else "FAIL"  # noqa: E731
        print(f"{r['id']:4} {r['expect_section']:7} | {str(b['top3_sections']):28} {mark(b):4} {b['sec']:7.4f} | "
              f"{str(v['top3_sections']):28} {mark(v):4} {v['sec']:6.2f} {v['api_calls']}"
              + ("  ※파서 누락" if r["parser_gap"] else ""))
    for name in ("bm25", "vector"):
        judged = [r for r in rows if not r["parser_gap"]]
        print(f"{name:6}: 통과 {sum(r[name]['pass'] for r in judged)}/{len(judged)} (파서 누락 q06 제외), "
              f"1위 일치 {sum(r[name]['top1_is_expected'] for r in rows)}/{len(rows)}, "
              f"평균 {sum(r[name]['sec'] for r in rows) / len(rows):.4f}초, API 호출 {sum(r[name]['api_calls'] for r in rows)}회")
    gap = [r for r in rows if r["parser_gap"]]
    for r in gap:
        print(f"※ {r['id']} {r['parser_gap']}: BM25 {'PASS' if r['bm25']['pass'] else 'FAIL'}, "
              f"벡터 {'PASS' if r['vector']['pass'] else 'FAIL'}")
    print(f"결과 -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
