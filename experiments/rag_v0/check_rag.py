"""185~214쪽 청크 검색과 적산 제한을 실제 질문으로 점검한다.

실행: python pipeline/parse.py --start 185 --end 214 && python pipeline/chunk.py && python evals/check_rag.py
외부 API·DB 없이 data/processed의 parsed.jsonl·chunks.jsonl만 읽는다. 파서 정답 채점이 아니다.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from rag import CHUNKS, PARSED, Index, citation, estimate_labor, evidence, load  # noqa: E402

QUESTIONS = Path(__file__).with_name("rag_questions.json")


def main() -> int:
    spec = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    chunks = load(CHUNKS)
    records = [json.loads(line) for line in PARSED.read_text(encoding="utf-8").splitlines() if line.strip()]
    index = Index(chunks)
    failed = 0

    for q in spec["questions"]:
        hits = evidence(index, q["query"], 3)
        sections = [h["chunk"]["section_no"] for h in hits]
        texts = [h["chunk"]["text"] for h in hits] + [n["text"] for h in hits for n in h["section_notes"]]
        traced = all(h["chunk"]["source"]["page"] and (h["chunk"]["kind"] == "text" or h["chunk"]["source"]["bbox"])
                     for h in hits)
        problems = []
        if q["expect_section"] not in sections:
            problems.append(f"기대 절 {q['expect_section']} 없음")
        if q.get("must_contain") and not any(q["must_contain"] in t for t in texts):
            problems.append(f"'{q['must_contain']}' 없음")
        if not traced:
            problems.append("출처(쪽·표 bbox) 없는 청크")
        failed += bool(problems)
        top = hits[0]["chunk"] if hits else None
        flags = [h["chunk"]["chunk_id"] for h in hits if h["chunk"]["structure"] == "uncertain"]
        print(f"{'PASS' if not problems else 'FAIL'} {q['id']} {q['query']}")
        print(f"     상위 3 절 {sections} | 1위 {citation(top) if top else '-'}"
              + (f" | 구조 불확실 {flags}" if flags else "") + (f" | {'; '.join(problems)}" if problems else ""))

    for e in spec["estimates"]:
        result = estimate_labor(chunks, records, e["section"], e["method"], e["trade"], e["column"], e["volume"])
        ok = (result["status"] == e["expect"]
              and (e["expect"] != "ok" or result["person_days"] == e["person_days"])
              and e.get("reason_contains", "") in result.get("reason", ""))
        failed += not ok
        detail = f"{result['person_days']} 인·일" if result["status"] == "ok" else result["reason"]
        print(f"{'PASS' if ok else 'FAIL'} {e['id']} 적산 {e['section']} {e['trade']} {e['volume']} → {result['status']}: {detail}")
        print(f"     출처 {result['sources']}")

    total = len(spec["questions"]) + len(spec["estimates"])
    print(f"\n통과 {total - failed} / 전체 {total} (검색 동작 점검. 파서 정답·보류 평가 아님)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
