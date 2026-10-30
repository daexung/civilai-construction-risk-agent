"""Promote source-checked 7-2-3 base routes after retaining steep-slope block."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = "2026-정오표1차/토목/7-2-3/육상투하"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    audit_path = ROOT / "evals/runtime_validation/per-unit-7-2-3-source-routes-2026-10-19.json"
    audit = json.loads(audit_path.read_text(encoding="utf8"))
    assert audit["status"] == "pass" and audit["independent_source_cells"] == 6
    assert audit["source_dash_cells"] == audit["restored_dash_cells"] == 2
    assert (audit["exact_calculated_routes"], audit["exact_rate_outputs_with_citations"],
            audit["source_separate_account_blocked_routes"]) == (12, 24, 4)
    assert audit["format_preflight"] == audit["citation_preflight"] == "pass"

    idx_path = ROOT / "data/drafts/executable.json"
    idx = json.loads(idx_path.read_text(encoding="utf8"))
    if KEY not in idx["executable"]:
        fail = next(row for row in idx["failed"] if row["id"] == KEY)
        assert fail["stage"] == "calculator_execution_or_rule_gate"
        idx["failed"] = [row for row in idx["failed"] if row["id"] != KEY]
        idx["executable"] = sorted([*idx["executable"], KEY])
        idx["summary"]["by_calc_type"]["per_unit"]["executable"] += 1
    idx["summary"]["executable"] = len(idx["executable"])
    idx["summary"]["failed"] = len(idx["failed"])
    idx["summary"]["failure_reasons_top10"] = [
        list(pair) for pair in Counter(str(row.get("reason", ""))
                                       for row in idx["failed"]).most_common(10)
    ]
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    stages = dict(Counter(row["stage"] for row in idx["failed"]))
    current = {"executable": len(idx["executable"]), "failed": len(idx["failed"]),
               "unsupported": idx["summary"]["skipped_without_compatible_calculator"],
               "excluded": idx["summary"]["excluded_from_execution"], "failure_stages": stages}

    cp_path = ROOT / "evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json"
    cp = json.loads(cp_path.read_text(encoding="utf8"))
    cp["previous_active_lists"] = cp["current_active_lists"]
    cp["current_active_lists"] = current
    if KEY not in cp["promoted"]:
        cp["promoted"].append(KEY)
    cp["source_checks"]["토목/7-2-3"] = (
        "Original PDF p.446 (printed p.390): all six cells of the three-resource × two-method table "
        "were independently checked. The source dashes for diver and special labor in the small-method "
        "column were restored and encoded as exact exclusions; the source note excluding divers on the "
        "above-water portion is applied conditionally. Only the steep small-method route is blocked per "
        "the separate-account note. 12 computed routes, 24 exact rate outputs/citations, four blocked "
        "quantity variants, and format/citation preflight passed."
    )
    cp["validation"]["land_dump_sparse_table"] = audit
    added = cp.setdefault("source_evidence_added_this_continuation", {"sections": 0, "cells": 0,
                                                                        "breakdown": {}})
    if "토목/7-2-3" not in added.setdefault("breakdown", {}):
        added["sections"] += 1
        added["cells"] += 6
        added["breakdown"]["토목/7-2-3"] = 6
    cp["remaining_failures"] = {
        "calculator_or_rule_gate": stages.get("calculator_execution_or_rule_gate", 0),
        "source_preflight": stages.get("source_preflight", 0),
        "format_preflight": stages.get("format_or_input_preflight", 0),
        "open_policy": cp["remaining_failures"]["open_policy"],
    }
    specs = ROOT / "data/drafts/specs"
    entries = [path.relative_to(specs).as_posix().encode() + b"\0" + sha(path).encode()
               for path in sorted(specs.rglob("*.json"))]
    cp["hashes"].update({
        "spec_count": len(entries), "spec_manifest_sha256": hashlib.sha256(b"\n".join(entries)).hexdigest(),
        "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl"),
        "executable_sha256": sha(idx_path),
        "runtime_per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py"),
        "validator_sha256": sha(ROOT / "pipeline/validate_drafts.py"),
    })
    cp_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    out = ROOT / "evals/runtime_validation/executable-7-2-3-source-promotion-2026-10-19.json"
    report = {"promoted": KEY, "current_active_lists": current, "audit": str(audit_path.relative_to(ROOT)),
              "reused": "all unaffected saved validations", "rerun": "7-2-3 source matrix and all routes",
              "full_replay": False, "full_rule_verification": 0, "hashes": cp["hashes"]}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
