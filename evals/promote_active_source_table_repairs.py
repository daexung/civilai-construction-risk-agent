"""Promote only source-checked rows from the current incremental active gate."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TARGETS = [
    "2026-정오표1차/토목/2-3-1/식생매트설치",
    "2026-정오표1차/토목/3-4-3/터널바닥암반청소",
    "2026-정오표1차/토목/6-7-3/유리섬유복합관부설및접합",
    "2026-정오표1차/토목/6-8-4/부단수_할정자관_부설_및_접합",
    "2026-정오표1차/기계설비/13-5-12/펌프설치",
]
NOT_PROMOTED = "2026-정오표1차/기계설비/13-3-2/기기보온"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def spec_manifest_hash() -> str:
    base = ROOT / "data/drafts/specs"
    files = sorted(base.rglob("*.json"))
    return hashlib.sha256(b"\n".join(
        p.relative_to(base).as_posix().encode() + b"\0" + sha(p).encode() for p in files
    )).hexdigest()


def targeted_verify() -> dict:
    # The source-grid and every-capacity exact-rate checks are mandatory gates.
    summaries = []
    for script in ("repair_civil_dash_cell_cluster.py", "repair_mechanical_exact_table_routes.py"):
        result = subprocess.run([sys.executable, str(ROOT / "evals" / script)],
                                cwd=ROOT, check=True, capture_output=True, text=True)
        summaries.append(json.loads(result.stdout.strip().splitlines()[-1]))
    from pipeline.validate_drafts import file_sha256, load_chunks, validate_one
    from backend.agent.tools.calc.per_unit import per_unit
    from evals.check_draft_executability import _values

    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    chunks = load_chunks(chunks_path)
    for section in ("2-3-1", "3-4-3", "6-7-3", "6-8-4"):
        path = ROOT / "data/drafts/specs/토목" / f"{section}.json"
        validation = validate_one(path, ROOT / "data/drafts", chunks, file_sha256(chunks_path))
        assert not validation["format_issues"] and not validation["citation_issues"], (section, validation)
    for section in ("13-3-2", "13-5-12"):
        path = ROOT / "data/drafts/specs/기계설비" / f"{section}.json"
        validation = validate_one(path, ROOT / "data/drafts", chunks, file_sha256(chunks_path))
        assert not validation["format_issues"] and not validation["citation_issues"], (section, validation)
        spec = json.loads(path.read_text(encoding="utf8"))["draft"]
        fields = spec["inputs"]
        blocked = {}
        for condition in spec.get("blocked", []):
            if condition.get("blocked_if"):
                name = condition["blocked_if"]["input"]
                blocked.setdefault(name, []).append(condition["blocked_if"])
        adjustments = (spec["quantity_model"]["params"].get("surcharges", [])
                       + spec["quantity_model"]["params"].get("note_adjustments", []))
        inputs = {field["name"]: _values(field, blocked.get(field["name"], []), adjustments)[0]
                  for field in fields}
        result = per_unit(spec, inputs)
        if section == "13-5-12":
            assert result["status"] == "computed", result
        else:
            # Its source-axis repair is useful, but an unresolved rate reduction
            # still blocks the active gate; do not promote it as executable.
            assert result["status"] == "blocked" and "아직 자동 계산하지 않음" in result.get("reason", ""), result
    return {"source_checkers": summaries, "preflight_sections": 6,
            "source_checked_but_not_promoted": {"id": NOT_PROMOTED,
                                                "reason": "conditional lagging-sheet reduction remains unmodeled"}}


def main() -> None:
    verification = targeted_verify()
    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf8"))
    assert (len(index["executable"],), len(index["failed"])) == (756, 126)
    for item in TARGETS:
        failure = next(x for x in index["failed"] if x["id"] == item)
        assert failure["stage"] == "calculator_execution_or_rule_gate", failure
    # Keep the unfinished 13-3-2 decision in the failure queue with its current
    # observed block status, rather than preserving the stale axis error.
    unresolved = next(x for x in index["failed"] if x["id"] == NOT_PROMOTED)
    unresolved["reason"] = "기본 조합 blocked: 이 할증 규칙은 아직 자동 계산하지 않음"
    index["failed"] = [x for x in index["failed"] if x["id"] not in TARGETS]
    index["executable"] = sorted([*index["executable"], *TARGETS])
    index["summary"]["executable"] = len(index["executable"])
    index["summary"]["failed"] = len(index["failed"])
    index["summary"]["by_calc_type"]["per_unit"]["executable"] += len(TARGETS)
    index["summary"]["failure_reasons_top10"] = [
        list(pair) for pair in Counter(str(x.get("reason", "")) for x in index["failed"]).most_common(10)
    ]
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

    checkpoint_path = ROOT / "evals/runtime_validation/incremental-source-citation-checkpoint-2026-10-19.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf8"))
    stages = dict(Counter(x["stage"] for x in index["failed"]))
    checkpoint["previous_active_lists"] = checkpoint.get("current_active_lists", {})
    checkpoint["current_active_lists"] = {"executable": len(index["executable"]),
                                           "failed": len(index["failed"]),
                                           "unsupported": 174, "excluded": 2,
                                           "failure_stages": stages}
    checkpoint["promoted"].extend(TARGETS)
    checkpoint.setdefault("source_checks", {})["토목/2-3-1 + 3-4-3 + 6-7-3 + 6-8-4"] = (
        "Original PDF tables p390-t2, p399-t3, p432-t0, p438-t1: 192 cells independently compared; "
        "24 exact input routes checked, including 10 condition-specific dash exclusions. "
        "6-7-3 uses opt-in exact child-header token matching so 압력관 cannot match 비압력관."
    )
    checkpoint["source_checks"]["기계설비/13-3-2 + 13-5-12"] = (
        "Five original PDF rate tables across physical pp.819-820, 841-842: 218 resource cells "
        "independently compared; all 57 selected input routes and 242 exact rate outputs checked. "
        "13-5-12 promoted. 13-3-2 remains failed because the lagging-sheet reduction is still blocked; "
        "its table routing was checked but no incomplete rule was promoted."
    )
    checkpoint.setdefault("validation", {})["targeted_preflight_sections"] = 6
    checkpoint["validation"]["all_rule_verification"] = 0
    checkpoint["validation"]["full_replay"] = False
    checkpoint["validation"]["per_unit_runtime_impact"] = (
        "Added opt-in column_match_mode=token, row_input_by_table, trades_by_table, and "
        "ignored_columns_by_table. Scans show these new branches are declared only by the targeted "
        "source-checked specs. check_per_unit.py passed 44/44 and the six prior promoted per-unit "
        "source/citation checkers passed after the final runtime edit."
    )
    checkpoint["validation"]["source_table_cluster"] = verification
    checkpoint["hashes"].update({
        "spec_count": len(list((ROOT / "data/drafts/specs").rglob("*.json"))),
        "spec_manifest_sha256": spec_manifest_hash(),
        "chunks_sha256": sha(ROOT / "data/processed/chunks.all.jsonl"),
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
    record = {
        "checkpoint": "grouped source table repairs",
        "scope": "incremental only; no full inventory replay",
        "previous": {"executable": 756, "failed": 126, "unsupported": 174, "excluded": 2},
        "current": checkpoint["current_active_lists"],
        "table_link_failure_queue_before": 39,
        "table_link_failure_queue_after": 33,
        "other_table_diagnostics_before": 8,
        "source_evidence": {"new_independent_pdf_cells": 410,
                            "new_source_sections": 6,
                            "dash_cluster_runtime_routes": 24,
                            "mechanical_exact_input_routes": 57,
                            "mechanical_exact_rate_outputs": 242},
        "reused": ["prior active failure list except six changed sections",
                   "prior source and estimate-flow validations outside per-unit runtime branches"],
        "rerun": ["six target spec preflights", "check_per_unit.py 44/44",
                  "six prior promoted per-unit source/citation suites",
                  "four civil dash-table routes", "two mechanical selected-table route matrices"],
        "full_rule_verification": 0,
        "official_rule_denominator": "unknown",
        "hashes": checkpoint["hashes"],
    }
    out = ROOT / "evals/runtime_validation/incremental-table-root-cause-checkpoint-2026-10-19.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"promoted": TARGETS, "not_promoted": NOT_PROMOTED,
                      "active": checkpoint["current_active_lists"],
                      "new_pdf_cells": 410, "source_routes": 81,
                      "exact_rate_outputs": 242, "checkpoint": str(out.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
