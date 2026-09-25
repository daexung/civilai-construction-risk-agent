"""185~214쪽 청크 검색, 절 단위 근거 구성, 적산 제한을 실제 질문으로 점검한다.

실행: python pipeline/parse.py --start 185 --end 214 && python pipeline/chunk.py && python evals/check_rag.py
외부 API·DB 없이 data/processed의 parsed.jsonl·chunks.jsonl만 읽는다. 파서 정답 채점이 아니다.
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from rag import (CHUNKS, PARSED, Index, citation, estimate_labor, evidence,  # noqa: E402
                 evidence_chunk_ids, load)

QUESTIONS = Path(__file__).with_name("rag_questions.json")


def common_problems(ev: dict) -> list[str]:
    """모든 질문에 적용: 근거 안 청크 중복 없음, 출처(쪽, 표는 bbox) 유지."""
    problems = []
    dup = [cid for cid, n in Counter(evidence_chunk_ids(ev)).items() if n > 1]
    if dup:
        problems.append(f"근거 청크 중복 {dup}")
    for group in ev["sections"] + ev["parents"]:
        for c in group["chunks"]:
            if not c["source"]["page"] or (c["kind"] == "table" and not c["source"]["bbox"]):
                problems.append(f"출처 없는 청크 {c['chunk_id']}")
    return problems


def main() -> int:
    spec = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    chunks = load(CHUNKS)
    records = [json.loads(line) for line in PARSED.read_text(encoding="utf-8").splitlines() if line.strip()]
    index = Index(chunks)
    failed = 0

    for q in spec["questions"]:
        ev = evidence(index, q["query"], 3)
        hit_sections = [c["section_no"] for _, c in ev["hits"]]
        texts = [c["text"] for g in ev["sections"] + ev["parents"] for c in g["chunks"]]
        problems = common_problems(ev)
        if q["expect_section"] not in hit_sections:
            problems.append(f"기대 절 {q['expect_section']} 없음")
        if q.get("must_contain") and not any(q["must_contain"] in t for t in texts):
            problems.append(f"'{q['must_contain']}' 없음")
        failed += bool(problems)
        top = ev["hits"][0][1] if ev["hits"] else None
        groups = [f"{g['section_no']}({len(g['chunks'])})" for g in ev["sections"]]
        parents = [f"{g['section_no']}({len(g['chunks'])})" for g in ev["parents"]]
        print(f"{'PASS' if not problems else 'FAIL'} {q['id']} {q['query']}")
        print(f"     상위 3 절 {hit_sections} | 1위 {citation(top) if top else '-'}")
        print(f"     근거: 절 {groups} + 상위 {parents}" + (f" | {'; '.join(problems)}" if problems else ""))

    for v in spec.get("evidence_checks", []):
        ev = evidence(index, v["query"], 3)
        problems = common_problems(ev)
        nos = [g["section_no"] for g in ev["sections"]]
        if nos.count(v["expect_section"]) != 1:
            problems.append(f"절 {v['expect_section']}이 근거에 {nos.count(v['expect_section'])}번")
        else:
            group = next(g for g in ev["sections"] if g["section_no"] == v["expect_section"])
            if v.get("whole_section_once"):
                whole = [c["chunk_id"] for c in chunks if c["section_no"] == v["expect_section"]]
                if [c["chunk_id"] for c in group["chunks"]] != whole:
                    problems.append("절 전체가 원문 순서대로 담기지 않음")
            if v.get("expect_subsection"):
                hit_ids = {h["chunk_id"] for h in group["hits"]}
                subs = {c["subsection"]["no"] for c in group["chunks"] if c["chunk_id"] in hit_ids and c["subsection"]}
                if v["expect_subsection"] not in subs:
                    problems.append(f"소제목 {v['expect_subsection']} 조각이 선택되지 않음 (선택된 소제목 {sorted(subs)})")
        parent_nos = [g["section_no"] for g in ev["parents"]]
        if v.get("expect_parent") and parent_nos.count(v["expect_parent"]) != 1:
            problems.append(f"상위 절 {v['expect_parent']}이 {parent_nos.count(v['expect_parent'])}번")
        failed += bool(problems)
        print(f"{'PASS' if not problems else 'FAIL'} {v['id']} 근거 구성 '{v['query']}'")
        print(f"     절 {[(g['section_no'], len(g['chunks']), [h['rank'] for h in g['hits']]) for g in ev['sections']]}"
              f" | 상위 {[(g['section_no'], len(g['chunks'])) for g in ev['parents']]}"
              + (f" | {'; '.join(problems)}" if problems else ""))

    for e in spec["estimates"]:
        result = estimate_labor(chunks, records, e["section"], e["method"], e["trade"], e["column"], e["volume"])
        ok = (result["status"] == e["expect"]
              and (e["expect"] != "ok" or result["person_days"] == e["person_days"])
              and e.get("reason_contains", "") in result.get("reason", ""))
        failed += not ok
        detail = f"{result['person_days']} 인·일" if result["status"] == "ok" else result["reason"]
        print(f"{'PASS' if ok else 'FAIL'} {e['id']} 적산 {e['section']} {e['trade']} {e['volume']} → {result['status']}: {detail}")
        print(f"     출처 {result['sources']}")

    total = len(spec["questions"]) + len(spec.get("evidence_checks", [])) + len(spec["estimates"])
    print(f"\n통과 {total - failed} / 전체 {total} (검색 동작 점검. 파서 정답·보류 평가 아님)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
