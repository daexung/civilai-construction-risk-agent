"""Promote 1-4-6 after both source tables pass cell and route audit."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/drafts/executable.json"
KEY = "2026-정오표1차/공통/1-4-6/작업제한"
BACKUP = ROOT / "tmp/executable-before-1-4-6-source-promotion.json"
REPORT = ROOT / "evals/runtime_validation/executable-1-4-6-source-promotion-2026-10-19.json"


def main() -> int:
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    assert KEY not in data["executable"]
    failures = [row for row in data["failed"] if row["id"] == KEY]
    assert len(failures) == 1 and failures[0]["stage"] == "calculator_execution_or_rule_gate", failures
    shutil.copy2(INDEX, BACKUP)
    data["failed"] = [row for row in data["failed"] if row["id"] != KEY]
    data["executable"].append(KEY)
    data["executable"].sort()
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
    report = {
        "promoted": KEY,
        "source_check": "check_lookup_1_4_6_source_routes.py",
        "reason": "PDF p.29's two separate tables were checked for nine source cells; exact routes, source-derived options, all nine cell citations and citation preflight pass; wrong-branch input is rejected.",
        "previous_stage": failures[0]["stage"],
        "backup": str(BACKUP.relative_to(ROOT)),
        "executable": len(data["executable"]), "failed": len(data["failed"]),
        "skipped": len(data["skipped"]),
        "index_sha256": hashlib.sha256(INDEX.read_bytes()).hexdigest(),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
