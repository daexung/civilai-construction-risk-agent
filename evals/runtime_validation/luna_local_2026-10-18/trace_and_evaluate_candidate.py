"""Trace a saved assembled candidate and keep references inside the evaluator."""
from __future__ import annotations

import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
RUN_DIR = Path(__file__).resolve().parent
CANDIDATE_PATH = RUN_DIR / "assembled-source-repaired-v5-module.json"
MIGRATION_PATH = RUN_DIR / "formwork-adjustments-v1-provenance-migration-candidate.json"
AUTHORING_PATH = ROOT / "evals/calculation_modules/formwork_authoring_cases.json"
FINAL_PATH = ROOT / "evals/calculation_modules/formwork_final_evaluation_cases.json"
RESULT_PATH = RUN_DIR / "luna-calculation-debug-v7.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    from backend.agent.tools.calc.daily_crew import _validate
    from backend.agent.tools.calc.generated import generated_daily_crew
    from backend.agent.tools.calc.policies import policy_applies
    from pipeline.calculation_modules import load_case_file, run_candidate_case_detailed

    candidate = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
    migrated = json.loads(MIGRATION_PATH.read_text(encoding="utf-8"))
    authoring = load_case_file(AUTHORING_PATH)
    policy_id = "formwork-6-3-1-height-started-interval-compound-v1"
    first = authoring[0]
    first_spec = json.loads(json.dumps(first["spec"], ensure_ascii=False))
    first_spec["quantity_model"]["params"]["module_id"] = candidate["id"]
    first_result = generated_daily_crew(first_spec, first["inputs"], labor_only=True,
                                        module_override=candidate)
    input_fields = {field["name"]: field for field in first_spec["inputs"]}
    input_fields.update({field["name"]: field for field in candidate.get("inputs", [])})
    normalized = {}
    for name, value in first["inputs"].items():
        if name in input_fields:
            checked, error = _validate(input_fields[name], value)
            normalized[name] = {"value": str(checked) if isinstance(checked, Fraction) else checked,
                                "valid": error is None}
        else:
            normalized[name] = {"valid": False, "reason": "undeclared"}

    base = first_result.get("provenance", {}).get("daily_volume_m3", {}).get("base_output", {})
    adjustments = first_result.get("provenance", {}).get("daily_volume_m3", {}).get("output_adjustments", [])
    first_detail = run_candidate_case_detailed(candidate,
        {**first, "allowed_system_policies": [policy_id]})
    authoring_results = []
    for case in authoring:
        detail = run_candidate_case_detailed(candidate,
            {**case, "allowed_system_policies": [policy_id]})
        authoring_results.append({"case_id": case.get("id"), "status": detail["status"],
            "execution": detail.get("execution"), "mismatched_fields": detail.get("mismatched_fields", []),
            "validation_errors": detail.get("validation_errors", [])})
    authoring_pass = all(item["status"] == "passed" for item in authoring_results)

    legacy_spec = json.loads(json.dumps(first["spec"], ensure_ascii=False))
    legacy_spec["quantity_model"]["params"]["module_id"] = migrated["id"]
    migrated_policy_applies = policy_applies(policy_id, migrated, legacy_spec)
    legacy = json.loads((ROOT / "data/calculation_modules/approved/formwork-adjustments-v1.json").read_text(encoding="utf-8"))
    legacy_policy_applies = policy_applies(policy_id, legacy, legacy_spec)
    migration_results = []
    for case in authoring:
        detail = run_candidate_case_detailed(migrated,
            {**case, "allowed_system_policies": [policy_id]})
        migration_results.append({"case_id": case.get("id"), "status": detail["status"],
            "execution": detail.get("execution"), "mismatched_fields": detail.get("mismatched_fields", []),
            "validation_errors": detail.get("validation_errors", [])})

    held_out = {"status": "not_run", "passed": 0, "total": None, "failures": []}
    if authoring_pass:
        final_cases = load_case_file(FINAL_PATH)
        if {case.get("id") for case in authoring} & {case.get("id") for case in final_cases}:
            held_out = {"status": "blocked_overlap", "passed": 0, "total": len(final_cases), "failures": []}
        else:
            final_results = []
            for case in final_cases:
                detail = run_candidate_case_detailed(candidate,
                    {**case, "allowed_system_policies": [policy_id]})
                if detail["status"] != "passed":
                    final_results.append({"case_id": case.get("id"), "status": detail["status"],
                        "execution": detail.get("execution"),
                        "mismatched_fields": detail.get("mismatched_fields", []),
                        "validation_errors": detail.get("validation_errors", [])})
            held_out = {"status": "passed" if not final_results else "failed",
                        "passed": len(final_cases) - len(final_results),
                        "total": len(final_cases), "failures": final_results}

    record = {
        "candidate": {"path": str(CANDIDATE_PATH.relative_to(ROOT)), "sha256": sha(CANDIDATE_PATH),
                      "external_model_called": False, "expected_values_emitted": False},
        "first_authoring_execution": {
            "case_id": first.get("id"), "status": first_result.get("status"),
            "reason": first_result.get("reason"), "normalized_inputs": normalized,
            "module": first_result.get("provenance", {}).get("generated_module"),
            "selected_base": {key: base.get(key) for key in ("table", "row", "column", "value", "source")},
            "output_adjustments_in_order": adjustments,
            "final_daily_output": first_result.get("daily_volume_m3"),
            "numeric_representation": type(first_result.get("daily_volume_m3")).__name__,
            "trusted_comparison": {"status": first_detail["status"],
                                   "mismatched_fields": first_detail.get("mismatched_fields", [])}},
        "fixture_diagnosis": {"pre_correction_first_base": {"column": "제물치장", "value": "20"},
            "source_table_selected_for_correction": {"table": "p193-t0", "row": "시공량",
                "column": "복잡", "value": "30"},
            "authoring_input_file_sha256": sha(AUTHORING_PATH),
            "original_fixture_preserved": str((RUN_DIR / "formwork_authoring_cases.before-input-fix.json").relative_to(ROOT))},
        "authoring": {"status": "passed" if authoring_pass else "failed",
                      "passed": sum(item["status"] == "passed" for item in authoring_results),
                      "total": len(authoring_results), "cases": authoring_results},
        "held_out_final": held_out,
        "legacy_compatibility": {"original_approved_module_policy_applies": legacy_policy_applies,
            "migrated_candidate_policy_applies": migrated_policy_applies,
            "migrated_candidate_review_status": migrated.get("review_status"),
            "migrated_candidate_authoring": {"passed": sum(item["status"] == "passed" for item in migration_results),
                "total": len(migration_results), "cases": migration_results},
            "registered_or_deployed": False},
        "evaluation_integrity": {"debug_comparison_used_trusted_expected_values": True,
            "independent_generation_claim": False,
            "candidate_or_prompt_received_expected_values": False,
            "final_cases_loaded_only_after_authoring_pass": authoring_pass},
    }
    if RESULT_PATH.exists():
        raise RuntimeError("result file exists; refusing to overwrite prior evaluation record")
    RESULT_PATH.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"first_status": first_result.get("status"), "first_reason": first_result.get("reason"),
        "first_base": record["first_authoring_execution"]["selected_base"],
        "first_adjustments": len(adjustments), "authoring": record["authoring"]["status"],
        "authoring_passed": record["authoring"]["passed"], "held_out_final": held_out["status"],
        "migrated_module_passed": record["legacy_compatibility"]["migrated_candidate_authoring"]["passed"],
        "result": str(RESULT_PATH.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
