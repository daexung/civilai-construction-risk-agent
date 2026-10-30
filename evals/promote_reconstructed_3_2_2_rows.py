"""Promote only the reconstructed, source-audited 3-2-2 item."""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/drafts/executable.json"
REPORT = ROOT / "data/drafts/report.json"
SPEC = ROOT / "data/drafts/specs/공통/3-2-2.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-3-2-2-source-audit-2026-10-19.json"
OLD_ID = "2026-정오표1차/공통/3-2-2/굴착(인력/암반)"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    item_id = package["draft"]["id"]
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "pass" and audit["independent_source_cells"] == 16
    assert audit["labor_calculation_cases"] and audit["format_citation_preflight"] == "pass"
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    failures = {row["id"]: row for row in data["failed"]}
    assert OLD_ID in failures and failures[OLD_ID]["stage"] == "format_or_input_preflight"
    assert item_id not in data["executable"] and OLD_ID not in data["executable"]
    backup = ROOT / "tmp/executable-before-3-2-2-source-row-promotion.json"
    if not backup.exists():
        shutil.copy2(INDEX, backup)
    data["failed"] = [row for row in data["failed"] if row["id"] != OLD_ID]
    data["executable"] = sorted([*data["executable"], item_id])
    data["summary"]["executable"] = len(data["executable"])
    data["summary"]["failed"] = len(data["failed"])
    by_type = Counter()
    for path in (ROOT / "data/drafts/specs").rglob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["draft"]["id"] in data["executable"]:
            by_type[record.get("calc_type")] += 1
    for kind, count in by_type.items():
        if kind in data["summary"]["by_calc_type"]:
            data["summary"]["by_calc_type"][kind]["executable"] = count
    data["summary"]["failure_reasons_top10"] = [list(pair) for pair in
        Counter(str(row.get("reason", "")) for row in data["failed"]).most_common(10)]
    INDEX.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = json.loads(REPORT.read_text(encoding="utf-8"))
    row = next(row for row in report["results"]
               if Path(row["path"]).as_posix() == "specs/공통/3-2-2.json")
    from pipeline.validate_drafts import load_chunks, validate_one
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    row.update(validation)
    report["ok"] = sum(1 for result in report["results"] if result["ok"])
    report["with_format_issues"] = sum(1 for result in report["results"] if result["format_issues"])
    report["with_citation_issues"] = sum(1 for result in report["results"] if result["citation_issues"])
    report["with_chunks_mismatch"] = sum(1 for result in report["results"] if result["chunks_mismatch"])
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    out = {
        "promoted": item_id, "previous_id": OLD_ID,
        "resolved_cause": "four source rock rows flattened into one; invalid slash in generated id",
        "source_audit": str(AUDIT.relative_to(ROOT)), "previous_stage": failures[OLD_ID]["stage"],
        "scope_note": "labor and equipment-hour rates are calculated; monetary equipment prices remain outside this cell check",
        "backup": str(backup.relative_to(ROOT)), "basic_executable": len(data["executable"]),
        "failed": len(data["failed"]), "unsupported": len(data["skipped"]),
        "index_sha256": hashlib.sha256(INDEX.read_bytes()).hexdigest(),
    }
    target = ROOT / "evals/runtime_validation/promotion-3-2-2-source-rows-2026-10-19.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
