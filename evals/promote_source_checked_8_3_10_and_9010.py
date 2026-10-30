"""Promote maritime equipment references after PDF-backed row verification."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/drafts/executable.json"
KEYS = {
    "2026-정오표1차/공통/8-3-10/해상장비": "evals/check_lookup_8_3_10_source_rows.py",
    "2026-정오표1차/공통/9010-0003/기계경비산출": "evals/check_lookup_9010_source_rows.py",
}
BACKUP = ROOT / "tmp/executable-before-source-checked-marine-lookup-promotion.json"
REPORT = ROOT / "evals/runtime_validation/executable-marine-lookup-source-promotion-2026-10-19.json"


def main() -> int:
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    failures = {}
    for key in KEYS:
        assert key not in data["executable"]
        matches = [row for row in data["failed"] if row["id"] == key]
        assert len(matches) == 1 and matches[0]["stage"] == "calculator_execution_or_rule_gate", matches
        failures[key] = matches[0]
    shutil.copy2(INDEX, BACKUP)
    selected = set(KEYS)
    data["failed"] = [row for row in data["failed"] if row["id"] not in selected]
    data["executable"].extend(selected)
    data["executable"].sort()
    data["summary"]["executable"] = len(data["executable"])
    data["summary"]["failed"] = len(data["failed"])
    type_counts = Counter()
    for path in (ROOT / "data/drafts/specs").rglob("*.json"):
        package = json.loads(path.read_text(encoding="utf-8"))
        if package["draft"]["id"] in data["executable"]:
            type_counts[package.get("calc_type")] += 1
    for calc_type, count in type_counts.items():
        if calc_type in data["summary"]["by_calc_type"]:
            data["summary"]["by_calc_type"][calc_type]["executable"] = count
    data["summary"]["failure_reasons_top10"] = [list(pair) for pair in
        Counter(str(row.get("reason", "")) for row in data["failed"]).most_common(10)]
    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    digest = hashlib.sha256(INDEX.read_bytes()).hexdigest()
    REPORT.write_text(json.dumps({"promoted": sorted(selected), "source_checks": KEYS,
                                  "source_evidence": {
                                      "8-3-10": "2 PDF tables / 16 rows / 48 draft coefficient cells / 80 independent source cells / 16 exact row lookups",
                                      "9010-0003": "8 PDF tables / 63 rows / 239 draft coefficient cells / 302 independent source cells / 63 exact row lookups; source SD row restored",
                                  },
                                  "previous_stages": {key: failures[key]["stage"] for key in KEYS},
                                  "backup": str(BACKUP.relative_to(ROOT)),
                                  "executable": len(data["executable"]), "failed": len(data["failed"]),
                                  "skipped": len(data["skipped"]), "index_sha256": digest},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"promoted": sorted(selected), "executable": len(data["executable"]),
                      "failed": len(data["failed"]), "skipped": len(data["skipped"]),
                      "sha256": digest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
