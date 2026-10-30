"""Validate the locally authored semantic candidate without opening case files.

This intentionally stops before authoring/final case loading if the unchanged
semantic contract rejects the candidate. It never registers a module.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
RUN_DIR = Path(__file__).resolve().parent
SEMANTIC_PATH = RUN_DIR / "formwork-semantic-candidate.json"
RESULT_PATH = RUN_DIR / "evaluation-record.json"
PDF_PATH = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
SOURCE_BUNDLE_PATHS = (
    ROOT / "data/processed/chunks.all.jsonl",
    ROOT / "data/processed/page_map.json",
)
GEMINI_PREFLIGHT = ROOT / "evals/runtime_validation/gemini_6_1_4_2026-10-17/module-json-semantic-preflight.json"
AUTHORING_CASE_PATH = ROOT / "evals/calculation_modules/formwork_authoring_cases.json"
FINAL_CASE_PATH = ROOT / "evals/calculation_modules/formwork_final_evaluation_cases.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    from pipeline.calculation_contract import build_source_bundle
    from pipeline.calculation_modules import (
        SEMANTIC_AUTHORING_SCHEMA,
        _schema_errors,
        assemble_semantic_candidate,
        validate_semantic_authoring,
    )
    from backend.agent.tools.calc.policies import POLICIES, allowed_policy_ids

    semantic_bytes = SEMANTIC_PATH.read_bytes()
    semantic = json.loads(semantic_bytes)
    candidate_sha256 = digest(semantic_bytes)

    source_bundle, source_meta = build_source_bundle(
        PDF_PATH, SOURCE_BUNDLE_PATHS[0], SOURCE_BUNDLE_PATHS[1], "공통", "6-3-1"
    )
    source_bundle_sha256 = digest(source_bundle.encode("utf-8"))
    spec_path = ROOT / "data/drafts/specs/공통/6-3-1.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))["draft"]
    known_conditions = {item["condition"]: item for item in spec.get("blocked", [])}
    known_fields = {item["name"]: item for item in spec.get("inputs", []) if item.get("name")}
    policy_id = "formwork-6-3-1-height-started-interval-compound-v1"
    allowed = allowed_policy_ids("공통", "6-3-1")

    schema_errors = _schema_errors(semantic, SEMANTIC_AUTHORING_SCHEMA)
    semantic_errors = validate_semantic_authoring(
        semantic, source_bundle, allowed, known_conditions, known_fields
    )

    assembly_status = "not_attempted"
    assembly_error = None
    if not schema_errors and semantic_errors:
        try:
            # The assembler rejects before needing verification cases. Do not
            # load authoring or held-out expectations before that gate passes.
            assemble_semantic_candidate(
                semantic, source_bundle, [], allowed_system_policies=allowed,
                known_blocked_conditions=known_conditions, known_input_fields=known_fields,
            )
            assembly_status = "unexpectedly_assembled"
        except (ValueError, TypeError, KeyError) as exc:
            assembly_status = "rejected_by_existing_assembler"
            assembly_error = str(exc)

    baseline = json.loads(GEMINI_PREFLIGHT.read_text(encoding="utf-8"))
    policy_record = POLICIES[policy_id]
    schema_sha256 = digest(json.dumps(SEMANTIC_AUTHORING_SCHEMA, sort_keys=True).encode())
    page_193 = next((item for item in source_meta["full_section_pdf_pages"]
                     if item.get("pdf_page") == 193), None)
    result = {
        "author": "current assistant, direct manual semantic authoring",
        "independent_first_generation_claim": False,
        "contamination": {
            "known_before_authoring": True,
            "reason": "Earlier conversation already exposed the registered formwork height policy, example calculation results, and prior candidate failures.",
        },
        "attempts": {"initial_candidates": 1, "repairs": 0},
        "candidate": {
            "path": str(SEMANTIC_PATH.relative_to(ROOT)),
            "sha256_before_validation": candidate_sha256,
            "schema_validation": "pass" if not schema_errors else "fail",
            "schema_errors": schema_errors,
            "semantic_contract_validation": "pass" if not semantic_errors else "fail",
            "semantic_errors": semantic_errors,
            "assembly": assembly_status,
            "assembly_error": assembly_error,
            "executable_module_created": False,
        },
        "same_source_contract": {
            "source_pdf_sha256": digest(PDF_PATH.read_bytes()),
            "source_bundle_sha256": source_bundle_sha256,
            "gemini_source_bundle_sha256": baseline.get("source_bundle_sha256"),
            "source_bundle_matches_gemini": source_bundle_sha256 == baseline.get("source_bundle_sha256"),
            "semantic_schema_sha256": schema_sha256,
            "gemini_schema_sha256": baseline.get("response_json_schema_sha256"),
            "schema_matches_gemini": schema_sha256 == baseline.get("response_json_schema_sha256"),
            "policy_id": policy_id,
            "policy_version": policy_record["version"],
            "policy_source_note_id": policy_record["source_note_id"],
            "policy_source": policy_record["source"],
            "official_page_mapping": page_193,
        },
        "case_files": {
            "authoring": str(AUTHORING_CASE_PATH.relative_to(ROOT)),
            "held_out_final": str(FINAL_CASE_PATH.relative_to(ROOT)),
            "opened_by_this_checker": False,
            "authoring_execution": "not_run_semantic_contract_blocked",
            "held_out_final_evaluation": "not_run_authoring_gate_not_passed",
        },
        "interpretation": {
            "format_failure": bool(schema_errors),
            "semantic_or_provenance_failure": bool(semantic_errors),
            "calculation_failure": None,
            "source_contract_issue": (
                "The parsed height/roof/crane note is in a kind=table chunk (section item 9), "
                "but build_source_bundle only exposes kind note/paragraph/text as calculation_notes. "
                "The registered policy anchor is chunk-10, which is the following [주] text chunk, "
                "not the table note. The candidate cites the actual table locator chunk-9; the unchanged "
                "validator rejects it as an unknown calculation note and separately requires the wrong chunk-10 anchor."
            ),
        },
    }
    RESULT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "schema_validation": result["candidate"]["schema_validation"],
        "semantic_contract_validation": result["candidate"]["semantic_contract_validation"],
        "assembly": assembly_status,
        "source_bundle_matches_gemini": result["same_source_contract"]["source_bundle_matches_gemini"],
        "schema_matches_gemini": result["same_source_contract"]["schema_matches_gemini"],
        "authoring_expectations_opened": False,
        "held_out_final_opened": False,
        "candidate_sha256": candidate_sha256,
        "result_path": str(RESULT_PATH.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
