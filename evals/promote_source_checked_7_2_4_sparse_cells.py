"""Promote 7-2-4 after the original sparse table and all routes pass audit."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = "2026-정오표1차/토목/7-2-4/수상고르기"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    audit_path = ROOT / "evals/runtime_validation/per-unit-7-2-4-sparse-cells-2026-10-19.json"
    audit = json.loads(audit_path.read_text(encoding="utf8"))
    assert audit["status"] == "pass" and audit["independent_source_cells"] == 20
    assert audit["source_dash_cells"] == audit["dash_cells_restored_to_chunk_and_exclusions"] == 6
    assert audit["exact_work_type_quantity_routes"] == 10
    assert audit["exact_resource_outputs_with_table_citations"] == 28
    assert audit["format_preflight"] == audit["citation_preflight"] == "pass"

    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf8"))
    if KEY not in index["executable"]:
        failure = next(row for row in index["failed"] if row["id"] == KEY)
        assert failure["stage"] == "calculator_execution_or_rule_gate"
        index["failed"] = [row for row in index["failed"] if row["id"] != KEY]
        index["executable"] = sorted([*index["executable"], KEY])
        index["summary"]["by_calc_type"]["per_unit"]["executable"] += 1
        index["summary"]["failure_reasons_top10"] = [
            list(pair) for pair in Counter(str(row.get("reason", ""))
                                           for row in index["failed"]).most_common(10)
        ]
    index["summary"]["executable"] = len(index["executable"])
    index["summary"]["failed"] = len(index["failed"])
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    stages = dict(Counter(row["stage"] for row in index["failed"]))
    current = {"executable": len(index["executable"]), "failed": len(index["failed"]),
               "unsupported": index["summary"]["skipped_without_compatible_calculator"],
               "excluded": index["summary"]["excluded_from_execution"],
               "failure_stages": stages}

    cp_path = ROOT / "evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json"
    cp = json.loads(cp_path.read_text(encoding="utf8"))
    cp["previous_active_lists"] = cp["current_active_lists"]
    cp["current_active_lists"] = current
    cp["promoted"].append(KEY)
    cp["source_checks"]["토목/7-2-4"] = (
        "Original PDF p.446 (printed p.390): all 20 cells in the four-resource × five-work matrix "
        "were independently transcribed. Six printed dash cells were restored to the source chunk and "
        "declared as exact conditional resource exclusions; 10 work-type/quantity routes produced 28 "
        "exact resource rates with matching table-cell citations."
    )
    cp["validation"]["sparse_table_7_2_4"] = audit
    added = cp.setdefault("source_evidence_added_this_continuation", {"sections": 0, "cells": 0,
                                                                        "breakdown": {}})
    added["sections"] += 1
    added["cells"] += 20
    added.setdefault("breakdown", {})["토목/7-2-4"] = 20
    cp["remaining_failures"] = {
        "calculator_or_rule_gate": stages.get("calculator_execution_or_rule_gate", 0),
        "source_preflight": stages.get("source_preflight", 0),
        "format_preflight": stages.get("format_or_input_preflight", 0),
        "open_policy": cp["remaining_failures"]["open_policy"],
    }

    spec_base = ROOT / "data/drafts/specs"
    manifest_entries = [path.relative_to(spec_base).as_posix().encode() + b"\0" + sha(path).encode()
                        for path in sorted(spec_base.rglob("*.json"))]
    cp["hashes"].update({
        "spec_count": len(manifest_entries),
        "spec_manifest_sha256": hashlib.sha256(b"\n".join(manifest_entries)).hexdigest(),
        "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl"),
        "executable_sha256": sha(index_path),
        "runtime_per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py"),
        "validator_sha256": sha(ROOT / "pipeline/validate_drafts.py"),
    })
    cp_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    report = {"promoted": KEY, "current_active_lists": current,
              "reused": "all unaffected saved validation evidence",
              "rerun": "7-2-4 only; 20 source cells, 10 exact work-type/quantity routes, 28 rate outputs",
              "full_replay": False, "full_rule_verification": 0,
              "hashes": cp["hashes"]}
    out = ROOT / "evals/runtime_validation/executable-7-2-4-sparse-cell-promotion-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
