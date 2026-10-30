"""Promote 8-3-9 after all four source tables have been independently checked."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/drafts/executable.json"
KEY = "2026-정오표1차/공통/8-3-9/스마트건설장비"
BACKUP = ROOT / "tmp/executable-before-8-3-9-source-promotion.json"
REPORT = ROOT / "evals/runtime_validation/executable-8-3-9-source-promotion-2026-10-19.json"


def main() -> int:
    shutil.copy2(INDEX, BACKUP)
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    assert KEY not in data["executable"]
    failing = [row for row in data["failed"] if row["id"] == KEY]
    assert len(failing) == 1 and failing[0]["stage"] == "calculator_execution_or_rule_gate", failing
    data["failed"] = [row for row in data["failed"] if row["id"] != KEY]
    data["executable"].append(KEY)
    data["executable"].sort()
    data["summary"]["executable"] = len(data["executable"])
    data["summary"]["failed"] = len(data["failed"])
    type_counts = Counter()
    for spec_path in (ROOT / "data/drafts/specs").rglob("*.json"):
        package = json.loads(spec_path.read_text(encoding="utf-8"))
        if package["draft"]["id"] in data["executable"]:
            type_counts[package.get("calc_type")] += 1
    for calc_type, count in type_counts.items():
        if calc_type in data["summary"]["by_calc_type"]:
            data["summary"]["by_calc_type"][calc_type]["executable"] = count
    reasons = Counter(str(row.get("reason", "")) for row in data["failed"])
    data["summary"]["failure_reasons_top10"] = [list(pair) for pair in reasons.most_common(10)]
    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(INDEX.read_bytes()).hexdigest()
    REPORT.write_text(json.dumps({"promoted": KEY, "source_check": "check_lookup_8_3_9_source_tables.py",
                                  "reason": "four source matrices compared: 4 rows / 40 value cells, exact category routes, citations, and preflight",
                                  "previous_stage": failing[0]["stage"], "backup": str(BACKUP.relative_to(ROOT)),
                                  "executable": len(data["executable"]), "failed": len(data["failed"]),
                                  "skipped": len(data["skipped"]), "index_sha256": digest},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"promoted": KEY, "executable": len(data["executable"]),
                      "failed": len(data["failed"]), "skipped": len(data["skipped"]),
                      "sha256": digest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
