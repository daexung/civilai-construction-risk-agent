"""Fixture regressions for same-group label shifts, offline and without PDF/API calls."""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.chunk import has_label_shift, make_chunks
DATA = ROOT / "data/processed"
FIXTURE = ROOT / "evals/fixtures/label_shift_expected.json"

def main() -> int:
    expected = set(json.loads(FIXTURE.read_text(encoding="utf-8-sig"))["expected_label_shift_table_ids"])
    parsed = [json.loads(line) for line in (DATA / "parsed.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    chunks = make_chunks(parsed)
    detected = {c["chunk_id"] for c in chunks if c["kind"] == "table" and
                has_label_shift([parsed[i] for i in c["record_ids"]])}
    missed, extra = sorted(expected - detected), sorted(detected - expected)
    print(f"fixture={len(expected)} detected={len(detected)} missed={missed}")
    print(f"rule_only_count={len(extra)} rule_only_tables={extra}")
    records_by_table = {}
    for row in parsed:
        if row.get("table_id"):
            records_by_table.setdefault(row["table_id"], []).append(row)
    for table_id in extra[:10]:
        print(f"RULE_ONLY {table_id}")
        for row in records_by_table.get(table_id, [])[:3]:
            print("  " + row["text"].replace("\n", " ")[:240])
    checks = [(f"fixture catches {table_id}", table_id in detected) for table_id in sorted(expected)]
    # These normal tables repeat equal values but have no unnamed numeric row in the group.
    for number, labels in enumerate((("보통인부", "특별인부"), ("공통공", "보통인부"), ("도장공", "조공")), 1):
        rows = [{"text": f"시험 표 | 그룹 100 | {label} | 작업량 2 | 수량 3"} for label in labels]
        checks.append((f"normal repeated values without unnamed row {number}", not has_label_shift(rows)))
    for name, passed in checks:
        print(("PASS " if passed else "FAIL ") + name)
    print(f"통과 {sum(ok for _, ok in checks)} / 전체 {len(checks)}")
    return 0 if all(ok for _, ok in checks) else 1
if __name__ == "__main__":
    raise SystemExit(main())
