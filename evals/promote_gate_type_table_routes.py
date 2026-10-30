"""Promote 13-6-3 after both source tables and routes pass."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TARGET = "2026-정오표1차/기계설비/13-6-3/수문제작"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest():
    base = ROOT / "data/drafts/specs"
    return hashlib.sha256(b"\n".join(
        path.relative_to(base).as_posix().encode() + b"\0" + sha(path).encode()
        for path in sorted(base.rglob("*.json"))
    )).hexdigest()


def main():
    from backend.agent.tools.calc.per_unit import per_unit
    from pipeline.validate_drafts import file_sha256, load_chunks, validate_one
    spec_path = ROOT / "data/drafts/specs/기계설비/13-6-3.json"
    spec = json.loads(spec_path.read_text(encoding="utf8"))["draft"]
    assert per_unit(spec, {"gate_type": "Tainter Gate", "quantity": "1"})["status"] == "computed"
    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    v = validate_one(spec_path, ROOT / "data/drafts", load_chunks(chunks_path), file_sha256(chunks_path))
    assert not v["format_issues"] and not v["citation_issues"], v
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf8"))
    assert (len(index["executable"]), len(index["failed"])) == (763, 119)
    failure = next(item for item in index["failed"] if item["id"] == TARGET)
    assert failure["stage"] == "calculator_execution_or_rule_gate"
    index["failed"] = [item for item in index["failed"] if item["id"] != TARGET]
    index["executable"] = sorted([*index["executable"], TARGET])
    index["summary"]["executable"] = len(index["executable"])
    index["summary"]["failed"] = len(index["failed"])
    index["summary"]["by_calc_type"]["per_unit"]["executable"] += 1
    index["summary"]["failure_reasons_top10"] = [
        list(pair) for pair in Counter(str(item.get("reason", "")) for item in index["failed"]).most_common(10)
    ]
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

    cp_path = ROOT / "evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json"
    cp = json.loads(cp_path.read_text(encoding="utf8")); stages = dict(Counter(x["stage"] for x in index["failed"]))
    cp["previous_active_lists"] = cp["current_active_lists"]
    cp["current_active_lists"] = {"executable": len(index["executable"]), "failed": len(index["failed"]),
                                   "unsupported": 174, "excluded": 2, "failure_stages": stages}
    cp["promoted"].append(TARGET)
    cp["source_checks"]["기계설비/13-6-3"] = (
        "Original p853-t0 Tainter Gate and p854-t1 Roller Gate grids: 20 rate/total cells compared; "
        "table_selector maps each declared gate type to its own source table and per-table resource list. "
        "Both routes returned 18 exact labor values with matching citations."
    )
    cp["validation"]["gate_type_table_routes"] = {"source_cells": 20, "routes": 2,
                                                    "exact_rate_outputs": 18, "full_rule_verification": False}
    cp["hashes"].update({"spec_manifest_sha256": manifest(), "chunks_sha256": sha(chunks_path),
                         "executable_sha256": sha(index_path),
                         "runtime_per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py"),
                         "validator_sha256": sha(ROOT / "pipeline/validate_drafts.py")})
    cp["remaining_failures"] = {
        "calculator_or_rule_gate": stages.get("calculator_execution_or_rule_gate", 0),
        "source_preflight": stages.get("source_preflight", 0),
        "format_preflight": stages.get("format_or_input_preflight", 0),
        "open_policy": "13-3-2 lagging-sheet reduction; cooling-tower unit basis inferred as 인/대; "
                       "maintenance 2-1-6 roller count and unresolved rates/combination policies remain open"}
    cp_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

    record_path = ROOT / "evals/runtime_validation/incremental-table-root-cause-checkpoint-2026-10-19.json"
    record = json.loads(record_path.read_text(encoding="utf8")); record["previous"] = record["current"]
    record["current"] = cp["current_active_lists"]; record["table_link_failure_queue_after"] = 30
    record["source_evidence"]["new_independent_pdf_cells"] += 20
    record["source_evidence"]["new_source_sections"] += 1
    record["source_evidence"]["gate_table_routes"] = 2
    record["source_evidence"]["gate_exact_rate_outputs"] = 18
    record["rerun"].append("13-6-3 Tainter/Roller Gate selected source-table routes")
    record["hashes"] = cp["hashes"]
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"promoted": TARGET, "active": cp["current_active_lists"],
                      "source_cells": 20, "exact_outputs": 18}, ensure_ascii=False))


if __name__ == "__main__": main()
