"""Promote 11-2-1 after the exact continuation-table routing audit passes."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = "2026-정오표1차/기계설비/11-2-1/버트융착식접합및부설"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    audit_path = ROOT / "evals/runtime_validation/per-unit-11-2-1-continuation-2026-10-19.json"
    audit = json.loads(audit_path.read_text(encoding="utf8"))
    assert audit["status"] == "pass" and audit["independent_source_cells"] == 38
    assert audit["diameter_values_mapped_exactly"] == 19
    assert (audit["exact_diameter_method_quantity_routes"],
            audit["exact_rate_outputs_with_table_citations"]) == (76, 152)
    assert audit["format_preflight"] == audit["citation_preflight"] == "pass"
    idx_path = ROOT / "data/drafts/executable.json"
    idx = json.loads(idx_path.read_text(encoding="utf8"))
    if KEY not in idx["executable"]:
        failure = next(row for row in idx["failed"] if row["id"] == KEY)
        assert failure["stage"] == "calculator_execution_or_rule_gate"
        idx["failed"] = [row for row in idx["failed"] if row["id"] != KEY]
        idx["executable"] = sorted([*idx["executable"], KEY])
        idx["summary"]["by_calc_type"]["per_unit"]["executable"] += 1
    idx["summary"]["executable"] = len(idx["executable"])
    idx["summary"]["failed"] = len(idx["failed"])
    idx["summary"]["failure_reasons_top10"] = [
        list(pair) for pair in Counter(str(row.get("reason", ""))
                                       for row in idx["failed"]).most_common(10)]
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
    cp["source_checks"]["기계설비/11-2-1"] = (
        "Original PDF pp.770-771 (printed pp.714-715): 38 source labor cells were visually compared. "
        "The exact diameter map routes 25-50mm to p770-t3 and 63-400mm to continuation p771-t0. "
        "Both source-approved joint methods and quantities 1/3 were checked across 76 routes, "
        "152 rate outputs, and exact table citations. The note's separate 5% machine cost is not "
        "claimed verified in this quantity-path audit."
    )
    cp["validation"]["pe_pipe_continuation"] = audit
    added = cp.setdefault("source_evidence_added_this_continuation", {"sections": 0, "cells": 0,
                                                                        "breakdown": {}})
    if "기계설비/11-2-1" not in added.setdefault("breakdown", {}):
        added["sections"] += 1
        added["cells"] += 38
        added["breakdown"]["기계설비/11-2-1"] = 38
    cp["remaining_failures"] = {
        "calculator_or_rule_gate": stages.get("calculator_execution_or_rule_gate", 0),
        "source_preflight": stages.get("source_preflight", 0),
        "format_preflight": stages.get("format_or_input_preflight", 0),
        "open_policy": cp["remaining_failures"]["open_policy"],
    }
    base = ROOT / "data/drafts/specs"
    items = [path.relative_to(base).as_posix().encode() + b"\0" + sha(path).encode()
             for path in sorted(base.rglob("*.json"))]
    cp["hashes"].update({"spec_count": len(items),
        "spec_manifest_sha256": hashlib.sha256(b"\n".join(items)).hexdigest(),
        "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl"),
        "executable_sha256": sha(idx_path),
        "runtime_per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py"),
        "validator_sha256": sha(ROOT / "pipeline/validate_drafts.py")})
    cp_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    report = {"promoted": KEY, "current_active_lists": current,
        "audit": str(audit_path.relative_to(ROOT)), "reused": "unaffected saved validation evidence",
        "rerun": "11-2-1 two-table continuation routing only", "full_replay": False,
        "full_rule_verification": 0, "hashes": cp["hashes"]}
    (ROOT / "evals/runtime_validation/executable-11-2-1-continuation-promotion-2026-10-19.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
