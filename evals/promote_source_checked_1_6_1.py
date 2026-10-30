"""Promote 1-6-1 only after the source-cell and calculator audit passes."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/drafts/executable.json"
KEY = "2026-정오표1차/토목/1-6-1/린콘크리트기층포설"
AUDIT = ROOT / "evals/runtime_validation/per-unit-1-6-1-source-audit-2026-10-19.json"


def main() -> int:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit.get("status") == "pass" and audit.get("source_cells") == 10
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    failed = next(row for row in data["failed"] if row["id"] == KEY)
    assert failed.get("stage") == "format_or_input_preflight"
    data["failed"] = [row for row in data["failed"] if row["id"] != KEY]
    data["executable"] = sorted([*data["executable"], KEY])

    # Citation reconstruction also removes the stale 8-3-1 preflight label;
    # its generated 100 m interval is still explicitly blocked by source policy.
    refraction = next(row for row in data["failed"]
                      if row["id"] == "2026-정오표1차/토목/8-3-1/굴절법탄성파탐사")
    refraction["stage"] = "calculator_execution_or_rule_gate"
    refraction["reason"] = ("legacy synthetic input receiver_interval=100 is outside the source 5 m basis; "
                            "source-specific 5 m paths pass and unspecified interval adjustment remains blocked")

    data["summary"]["executable"] = len(data["executable"])
    data["summary"]["failed"] = len(data["failed"])
    by_type = Counter()
    for path in (ROOT / "data/drafts/specs").rglob("*.json"):
        package = json.loads(path.read_text(encoding="utf-8"))
        if package["draft"]["id"] in data["executable"]:
            by_type[package.get("calc_type")] += 1
    for calc_type, count in by_type.items():
        if calc_type in data["summary"]["by_calc_type"]:
            data["summary"]["by_calc_type"][calc_type]["executable"] = count
    data["summary"]["failure_reasons_top10"] = [list(pair) for pair in
        Counter(str(row.get("reason", "")) for row in data["failed"]).most_common(10)]
    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"promoted": KEY, "audit": str(AUDIT.relative_to(ROOT)),
              "reason": "p.315 cells independently checked; preflight and exact rate/equipment outputs pass",
              "executable": len(data["executable"]), "failed": len(data["failed"]),
              "unsupported": len(data["skipped"]), "index_sha256": hashlib.sha256(INDEX.read_bytes()).hexdigest(),
              "reclassified_failure": refraction["id"], "reclassification_reason": refraction["reason"]}
    target = ROOT / "evals/runtime_validation/executable-1-6-1-source-promotion-2026-10-19.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
