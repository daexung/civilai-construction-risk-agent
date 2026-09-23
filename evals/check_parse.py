"""골든셋으로 parse.py를 채점한다.

실행: python evals/check_parse.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from parse import parse_pages  # noqa: E402

GOLDEN = ROOT / "evals/golden_parse.json"


def main() -> int:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    pdf = str(ROOT / golden["pdf"])
    cases = golden["cases"]

    # 표가 여러 쪽에 걸치는 경우가 있어 실제 사용처럼 범위 전체를 한 번에 파싱한다
    pages = sorted({case["page"] for case in cases})
    parsed = parse_pages(pdf, pages[0], pages[-1])
    records = {page: [r for r in parsed if r["page"] == page] for page in pages}

    passed, failed = 0, []

    for case in cases:
        texts = [r["text"] for r in records[case["page"]]]
        hits = [t for t in texts if all(word in t for word in case["must_contain"])]
        expect = case.get("expect_count", 1)

        if len(hits) != expect:
            failed.append((case, f"{expect}건이어야 하는데 {len(hits)}건"))
            continue

        banned = [w for w in case.get("must_not_contain", []) if any(w in t for t in hits)]
        if banned:
            failed.append((case, f"있으면 안 되는 값: {banned} / {hits[0][:90]}"))
            continue

        passed += 1

    print(f"통과 {passed} / 전체 {len(cases)}\n")
    for case, reason in failed:
        print(f"[실패] p{case['page']} {case['id']}")
        print(f"       {reason}")
        print(f"       찾던 것: {case['must_contain']}")
        print()

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
