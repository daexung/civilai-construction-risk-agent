"""Record the exact source-checked 2104-0010 row-reference candidate."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/drafts/executable.json"
KEY = "2026-정오표1차/공통/2104-0010/크레인(타이어)"
BACKUP = ROOT / "tmp/executable-before-2104-source-promotion.json"
REPORT = ROOT / "evals/runtime_validation/executable-2104-source-promotion-2026-10-19.json"


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
    data["summary"]["by_calc_type"]["lookup_only"]["executable"] = sum(
        1 for spec_path in (ROOT / "data/drafts/specs").rglob("*.json")
        if json.loads(spec_path.read_text(encoding="utf-8")).get("calc_type") == "lookup_only"
        and json.loads(spec_path.read_text(encoding="utf-8"))["draft"]["id"] in data["executable"])
    reasons = Counter(str(row.get("reason", "")) for row in data["failed"])
    data["summary"]["failure_reasons_top10"] = [list(pair) for pair in reasons.most_common(10)]
    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(INDEX.read_bytes()).hexdigest()
    REPORT.write_text(json.dumps({"promoted": KEY, "source_check": "check_lookup_2104_tire_crane_source_rows.py",
                                  "reason": "source-grid comparison: 8 rows / 32 values plus exact machine-code suffix mappings and citation preflight",
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
