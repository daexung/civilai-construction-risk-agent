"""Promote 1-6-3 after its four source cells and runtime unit rates pass."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/drafts/executable.json"
KEY = "2026-정오표1차/기계설비/1-6-3/가교화_폴리에틸렌관_접합_및_배관"
AUDIT = ROOT / "evals/runtime_validation/per-unit-1-6-3-source-audit-2026-10-19.json"


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit.get("status") == "pass" and audit.get("source_cells") == 4
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    failure = next(row for row in data["failed"] if row["id"] == KEY)
    assert failure.get("stage") == "format_or_input_preflight"
    data["failed"] = [row for row in data["failed"] if row["id"] != KEY]
    data["executable"] = sorted([*data["executable"], KEY])

    # These two source text omissions are repaired, but the calculator remains unsupported.
    incomplete = next(row for row in data["failed"]
                      if row["id"] == "2026-정오표1차/기계설비/13-5-4/덕트설치")
    incomplete["stage"] = "calculator_execution_or_rule_gate"
    incomplete["reason"] = ("source cell and citation now verify; calculator rejects because no quantity input/"
                            "unit_rate_table params are declared for heterogeneous work bases")
    data["summary"]["executable"] = len(data["executable"])
    data["summary"]["failed"] = len(data["failed"])
    counts = Counter()
    for path in (ROOT / "data/drafts/specs").rglob("*.json"):
        package = json.loads(path.read_text(encoding="utf-8"))
        if package["draft"]["id"] in data["executable"]:
            counts[package.get("calc_type")] += 1
    for calc_type, count in counts.items():
        if calc_type in data["summary"]["by_calc_type"]:
            data["summary"]["by_calc_type"][calc_type]["executable"] = count
    data["summary"]["failure_reasons_top10"] = [list(pair) for pair in
        Counter(str(row.get("reason", "")) for row in data["failed"]).most_common(10)]
    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"promoted": KEY, "audit": str(AUDIT.relative_to(ROOT)),
              "source_checked": "2 labor rows × 2 pipe-size columns",
              "calculation_checked": "exact per-meter rates for both pipe sizes",
              "executable": len(data["executable"]), "failed": len(data["failed"]),
              "unsupported": len(data["skipped"]),
              "index_sha256": hashlib.sha256(INDEX.read_bytes()).hexdigest(),
              "reclassified_failure": incomplete["id"], "reclassification_reason": incomplete["reason"]}
    target = ROOT / "evals/runtime_validation/executable-1-6-3-source-promotion-2026-10-19.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
