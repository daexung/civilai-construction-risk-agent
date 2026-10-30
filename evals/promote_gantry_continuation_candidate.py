"""Promote the source-checked 13-10-3 continuation-table repair."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TARGET = "2026-정오표1차/기계설비/13-10-3/GANTRY_CRANE_설치"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest():
    base = ROOT / "data/drafts/specs"
    files = sorted(base.rglob("*.json"))
    return hashlib.sha256(b"\n".join(
        p.relative_to(base).as_posix().encode() + b"\0" + sha(p).encode() for p in files
    )).hexdigest()


def main():
    from backend.agent.tools.calc.per_unit import per_unit
    from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

    spec_path = ROOT / "data/drafts/specs/기계설비/13-10-3.json"
    spec = json.loads(spec_path.read_text(encoding="utf8"))["draft"]
    assert per_unit(spec, {"quantity": "1"})["status"] == "computed"
    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(spec_path, ROOT / "data/drafts", load_chunks(chunks_path), file_sha256(chunks_path))
    assert not validation["format_issues"] and not validation["citation_issues"], validation

    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf8"))
    assert (len(index["executable"]), len(index["failed"])) == (761, 121)
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

    checkpoint_path = ROOT / "evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf8"))
    stages = dict(Counter(item["stage"] for item in index["failed"]))
    checkpoint["previous_active_lists"] = checkpoint["current_active_lists"]
    checkpoint["current_active_lists"] = {"executable": len(index["executable"]), "failed": len(index["failed"]),
                                           "unsupported": 174, "excluded": 2, "failure_stages": stages}
    checkpoint["promoted"].append(TARGET)
    checkpoint["source_checks"]["기계설비/13-10-3"] = (
        "PDF p903-t2 and continuation p904-t0: nine labor cells independently compared to the original "
        "grids; the first five and the four continued trades are separately cited. Three quantity routes "
        "returned all nine exact source rates. The total row is excluded as a resource."
    )
    checkpoint["validation"]["gantry_continuation"] = {
        "preflight": "format/citation pass", "independent_pdf_cells": 9,
        "quantity_routes": 3, "exact_rate_outputs": 27, "full_rule_verification": False,
    }
    checkpoint["hashes"].update({
        "spec_manifest_sha256": manifest(), "chunks_sha256": sha(chunks_path),
        "executable_sha256": sha(index_path),
        "runtime_per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py"),
        "validator_sha256": sha(ROOT / "pipeline/validate_drafts.py"),
    })
    checkpoint["remaining_failures"] = {
        "calculator_or_rule_gate": stages.get("calculator_execution_or_rule_gate", 0),
        "source_preflight": stages.get("source_preflight", 0),
        "format_preflight": stages.get("format_or_input_preflight", 0),
        "open_policy": "13-3-2 lagging-sheet reduction; cooling-tower unit basis inferred as 인/대; "
                       "maintenance 2-1-6 roller count and unresolved rates/combination policies remain open",
    }
    checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

    record_path = ROOT / "evals/runtime_validation/incremental-table-root-cause-checkpoint-2026-10-19.json"
    record = json.loads(record_path.read_text(encoding="utf8"))
    record["previous"] = record["current"]
    record["current"] = checkpoint["current_active_lists"]
    record["table_link_failure_queue_after"] = 32
    record["source_evidence"]["new_independent_pdf_cells"] += 9
    record["source_evidence"]["new_source_sections"] += 1
    record["source_evidence"]["gantry_routes"] = 3
    record["source_evidence"]["gantry_exact_rate_outputs"] = 27
    record["rerun"].append("13-10-3 GANTRY CRANE base and continuation rate table source check")
    record["hashes"] = checkpoint["hashes"]
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"promoted": TARGET, "active": checkpoint["current_active_lists"],
                      "new_pdf_cells": 9, "exact_rate_outputs": 27}, ensure_ascii=False))


if __name__ == "__main__":
    main()
