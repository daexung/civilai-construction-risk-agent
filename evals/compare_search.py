"""BM25, 벡터(gemini-embedding-2, 정확한 코사인), 하이브리드(RRF)를 같은 질문 세트로 비교한다.

실행: python evals/compare_search.py
판정(상위 3개 청크 기준):
  - 절: expect_section이 상위 3개 중 하나의 절 번호
  - 표: expect_tables 중 하나가 상위 3개 청크 ID에 있음 (기대 표가 없는 질문은 판정하지 않음)
시간은 질문마다 검색 함수 한 번의 실제 경과 시간이다. 벡터·하이브리드는 질문마다 임베딩 API를 각각 1회 호출한다.
q06은 원본 파싱에서 표(p193-t1)가 빠진 문제라 집계에서 빼고 따로 표시한다.
결과: data/processed/search_compare.jsonl (커밋하지 않는 생성물)
"""

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.tools.search.hybrid import HybridIndex  # noqa: E402
from agent.tools.search.bm25 import CHUNKS, Index, load  # noqa: E402
from agent.tools.search.vector import VectorIndex  # noqa: E402

QUESTIONS = Path(__file__).with_name("rag_questions.json")
OUT = ROOT / "data/processed/search_compare.jsonl"
PARSER_GAPS = {}


def timed_search(index, query: str) -> tuple[list, float, int]:
    """(상위 3개, 경과 초, 이번 API 호출 수). 호출 한도(429)면 30초 쉬고 한 번 더 한다."""
    before = getattr(index, "api_calls", 0)
    for attempt in range(2):
        try:
            started = time.perf_counter()
            hits = index.search(query, 3)
            return hits, time.perf_counter() - started, getattr(index, "api_calls", 0) - before
        except Exception as exc:  # noqa: BLE001
            if attempt == 0 and ("429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc)):
                time.sleep(30)
                continue
            raise
    raise RuntimeError("unreachable")


def judge(item: dict, hits: list) -> dict:
    ids = [c["chunk_id"] for _, c in hits]
    nos = [c["section_no"] for _, c in hits]
    out = {"top3": ids, "top3_sections": nos, "section_ok": item["expect_section"] in nos,
           "top1_section_ok": bool(nos) and nos[0] == item["expect_section"]}
    if item.get("expect_tables"):
        out["table_ok"] = any(t in ids for t in item["expect_tables"])
    return out


def main() -> int:
    spec = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    items = spec["questions"] + spec.get("evidence_checks", [])
    vector = VectorIndex()
    if vector.stale or vector.missing:
        raise SystemExit(f"벡터가 청크와 맞지 않는다(옛 {len(vector.stale)}, 없음 {len(vector.missing)}). embed.py를 다시 실행")
    bm25 = Index(load(CHUNKS))
    # 하이브리드는 따로 만든 벡터 인덱스로 자기 질문 임베딩을 직접 호출한다(호출 수·시간을 따로 잰다)
    methods = {"bm25": bm25, "vector": vector, "hybrid": HybridIndex(bm25=bm25, vector=VectorIndex())}

    rows = []
    for item in items:
        row = {"id": item["id"], "category": item.get("category", ""), "query": item["query"],
               "expect_section": item["expect_section"], "expect_tables": item.get("expect_tables"),
               "parser_gap": PARSER_GAPS.get(item["id"])}
        for name, index in methods.items():
            hits, sec, calls = timed_search(index, item["query"])
            row[name] = {**judge(item, hits), "sec": round(sec, 4), "api_calls": calls}
            if name != "bm25":
                time.sleep(0.7)
        rows.append(row)
    OUT.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    def mark(r, name, key):
        v = r[name].get(key)
        return "·" if v is None else ("O" if v else "X")

    print(f"{'id':4} {'분류':7} {'기대 절':7} {'기대 표':17} | 절 B V H | 표 B V H | 1위 B V H")
    for r in rows:
        tables = ",".join(r["expect_tables"] or ["-"])
        print(f"{r['id']:4} {r['category']:7} {r['expect_section']:7} {tables[:17]:17} | "
              f"   {mark(r, 'bm25', 'section_ok')} {mark(r, 'vector', 'section_ok')} {mark(r, 'hybrid', 'section_ok')} | "
              f"   {mark(r, 'bm25', 'table_ok')} {mark(r, 'vector', 'table_ok')} {mark(r, 'hybrid', 'table_ok')} | "
              f"    {mark(r, 'bm25', 'top1_section_ok')} {mark(r, 'vector', 'top1_section_ok')} {mark(r, 'hybrid', 'top1_section_ok')}"
              + ("  ※파서 누락" if r["parser_gap"] else ""))

    judged = [r for r in rows if not r["parser_gap"]]
    with_table = [r for r in judged if r["expect_tables"]]
    print(f"\n집계 (q06 제외 {len(judged)}문항, 표 판정 {len(with_table)}문항)")
    for name in methods:
        secs = sorted(r[name]["sec"] for r in rows)
        print(f"  {name:6} 절 {sum(r[name]['section_ok'] for r in judged):2}/{len(judged)} | "
              f"표 {sum(r[name]['table_ok'] for r in with_table):2}/{len(with_table)} | "
              f"1위 절 {sum(r[name]['top1_section_ok'] for r in judged):2}/{len(judged)} | "
              f"질문당 평균 {sum(secs) / len(secs):.4f}초, 중앙값 {secs[len(secs) // 2]:.4f}초 | "
              f"임베딩 API {sum(r[name]['api_calls'] for r in rows)}회")
    by_cat = defaultdict(list)
    for r in judged:
        by_cat[r["category"]].append(r)
    print("\n분류별 (절 / 표)")
    for cat, rs in by_cat.items():
        t = [r for r in rs if r["expect_tables"]]
        cells = [f"{n} {sum(r[n]['section_ok'] for r in rs)}/{len(rs)}, {sum(r[n]['table_ok'] for r in t)}/{len(t)}"
                 for n in methods]
        print(f"  {cat:7} " + " | ".join(cells))
    for r in rows:
        if r["parser_gap"]:
            print(f"\n※ {r['id']} {r['parser_gap']}")
            for n in methods:
                print(f"    {n:6} 절 {mark(r, n, 'section_ok')} 표 {mark(r, n, 'table_ok')} 상위3 {r[n]['top3']}")
    print(f"\n결과 -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
