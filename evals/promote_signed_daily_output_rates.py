"""Promote two source-audited daily-output calculations after focused replay."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/drafts/executable.json"
KEYS = {
    "2026-정오표1차/공통/2-6-1/강관동바리_토목",
    "2026-정오표1차/유지관리/1-2-11/잔디깎기",
}
AUDIT = ROOT / "evals/runtime_validation/signed-daily-output-rates-source-audit-2026-10-19.json"


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit.get("status") == "pass"
    assert audit["calculation_cases"] == {"strut_height_x_spacing": 9,
                                          "mower_machine_x_frequency_x_netting": 12,
                                          "mower_conditional_price_rates": 12}
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    failed = {row["id"]: row for row in data["failed"]}
    assert KEYS <= failed.keys(), KEYS - failed.keys()
    assert all(failed[key].get("stage") == "calculator_execution_or_rule_gate" for key in KEYS)
    data["failed"] = [row for row in data["failed"] if row["id"] not in KEYS]
    data["executable"] = sorted([*data["executable"], *KEYS])
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
    result = {"promoted": sorted(KEYS), "audit": str(AUDIT.relative_to(ROOT)),
              "executable": len(data["executable"]), "failed": len(data["failed"]),
              "unsupported": len(data["skipped"]),
              "index_sha256": hashlib.sha256(INDEX.read_bytes()).hexdigest(),
              "partial_rule_limit": audit["remaining_source_note"]}
    out = ROOT / "evals/runtime_validation/executable-signed-daily-output-promotion-2026-10-19.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
