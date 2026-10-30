"""Offline replay of retained Gemini responses through the corrected source validator."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
RAW_DIR = ROOT / "evals/runtime_validation/gemini_6_1_4_2026-10-17/module-json-raw"
PREFLIGHT = ROOT / "evals/runtime_validation/gemini_6_1_4_2026-10-17/module-json-semantic-preflight.json"
ATTEMPTS = ROOT / "evals/runtime_validation/gemini_6_1_4_2026-10-17/module-json-semantic-authoring-attempts.jsonl"
RESULT = ROOT / "evals/runtime_validation/gemini_6_1_4_2026-10-17/source-evidence-replay-2026-10-18-v4.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    from backend.agent.tools.calc.policies import allowed_policy_ids, resolve_policy_source_evidence
    from pipeline.calculation_contract import build_source_bundle
    from pipeline.calculation_modules import (
        SEMANTIC_AUTHORING_SCHEMA, _schema_errors, validate_candidate,
        validate_registered_policy_sources, validate_semantic_authoring,
    )

    pdf = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
    source_text, bundle = build_source_bundle(pdf, ROOT / "data/processed/chunks.all.jsonl",
        ROOT / "data/processed/page_map.json", "공통", "6-3-1")
    policy_ids = allowed_policy_ids("공통", "6-3-1")
    preflight_errors = validate_registered_policy_sources(source_text, policy_ids)
    policy_id = next(iter(policy_ids))
    policy_evidence, evidence_errors = resolve_policy_source_evidence(policy_id, bundle)
    stable_policy_evidence_id = policy_evidence.get("evidence_id") if policy_evidence else None
    allowed_note_ids = {item["evidence_id"] for item in bundle.get("calculation_notes", [])}
    aliases = {alias: item["evidence_id"] for item in bundle.get("calculation_notes", [])
               for alias in item.get("legacy_aliases", [])}

    baseline = json.loads(PREFLIGHT.read_text(encoding="utf-8"))
    attempt_errors = []
    if ATTEMPTS.exists():
        for line in ATTEMPTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                attempt_errors.extend(error for error in row.get("errors", []) if isinstance(error, str))
    old_anchor_error_count = sum("anchored source note" in error for error in attempt_errors)
    old_policy_shape_error_count = sum("registered policy" in error and "rewrites" in error
                                      for error in attempt_errors)

    responses = []
    for path in sorted(RAW_DIR.glob("generation-*.json")):
        raw_bytes = path.read_bytes()
        wrapper = json.loads(raw_bytes)
        raw_text = wrapper.get("response_text") if isinstance(wrapper, dict) else None
        row = {"file": path.name, "sha256": sha(raw_bytes),
               "finish_reason": (wrapper.get("usage_and_finish") or {}).get("finish_reason")
                   if isinstance(wrapper, dict) else None}
        try:
            candidate = json.loads(raw_text)
        except (TypeError, ValueError):
            row.update({"json": "fail", "current_schema": "not_run",
                        "current_contract": "not_run", "classifications": ["response_text_not_json"]})
            responses.append(row)
            continue
        row["json"] = "pass"
        is_semantic = isinstance(candidate, dict) and "note_interpretations" in candidate and "calculation_contract" not in candidate
        classifications = []
        if is_semantic:
            schema_errors = _schema_errors(candidate, SEMANTIC_AUTHORING_SCHEMA)
            semantic_errors = validate_semantic_authoring(candidate, source_text, policy_ids)
            row.update({"response_kind": "semantic_authoring", "current_schema": "pass" if not schema_errors else "fail",
                        "current_schema_errors": schema_errors,
                        "current_semantic_contract": "pass" if not semantic_errors else "fail",
                        "current_validator_errors": semantic_errors})
            model_rules = [rule for rule in candidate.get("rules", []) if isinstance(rule, dict)
                           and (rule.get("policy_id") == policy_id or rule.get("kind") == "system_policy_ref")]
            if model_rules and not candidate.get("policy_references"):
                classifications.append("registered_policy_encoded_as_rule_instead_of_policy_reference")
            if any(("operation" in rule or "value" in rule or "value_expr" in rule) for rule in model_rules):
                classifications.append("registered_policy_rewritten_as_formula_rule")
            if any(not rule.get("when") for rule in model_rules):
                classifications.append("registered_policy_rule_has_empty_condition")
            cited = {note_id for rule in model_rules for note_id in rule.get("source_note_ids", [])}
            resolved_cited = {aliases.get(note_id, note_id) for note_id in cited}
            if stable_policy_evidence_id and model_rules and stable_policy_evidence_id not in resolved_cited:
                classifications.append("policy_citation_does_not_resolve_to_registered_pdf_table_note")
            # This note was not in the historical bundle; do not score its absence as model failure.
            if any(note.get("kind") == "table_note" for note in bundle.get("calculation_notes", [])):
                classifications.append("current_bundle_adds_explicit_table_note_evidence_absent_from_historical_prompt")
            if schema_errors:
                classifications.append("historical_response_schema_differs_from_current_schema")
            if semantic_errors and not schema_errors:
                classifications.append("current_source_or_semantic_contract_failure")
        else:
            contract_errors = validate_candidate(candidate, allowed_system_policies=policy_ids, require_contract=True)
            row.update({"response_kind": "assembled_module", "current_contract": "pass" if not contract_errors else "fail",
                        "current_validator_errors": contract_errors})
            if stable_policy_evidence_id and candidate.get("policy_note_ids", {}).get(policy_id) != stable_policy_evidence_id:
                classifications.append("historical_policy_anchor_is_not_stable_pdf_table_evidence")
            classifications.append("historical_full_module_format_is_not_same_schema_as_current_semantic_authoring")
        row["classifications"] = classifications
        row["private_content_emitted"] = False
        responses.append(row)

    current_schema_hash = sha(json.dumps(SEMANTIC_AUTHORING_SCHEMA, sort_keys=True).encode("utf-8"))
    record = {
        "replay": "stored-response-only; no model calls",
        "current_source": {"pdf_sha256": bundle["pdf_sha256"],
                           "bundle_sha256": sha(source_text.encode("utf-8")),
                           "policy_evidence_id": stable_policy_evidence_id,
                           "preflight": "pass" if not preflight_errors and not evidence_errors else "fail",
                           "preflight_errors": preflight_errors + evidence_errors},
        "conditions": {"historical_schema_sha256": baseline.get("response_json_schema_sha256"),
                       "current_schema_sha256": current_schema_hash,
                       "schema_same": baseline.get("response_json_schema_sha256") == current_schema_hash,
                       "historical_source_bundle_sha256": baseline.get("source_bundle_sha256"),
                       "current_source_bundle_sha256": sha(source_text.encode("utf-8")),
                       "source_bundle_same": baseline.get("source_bundle_sha256") == sha(source_text.encode("utf-8")),
                       "not_same_condition_comparison": True},
        "historical_attempt_error_counts": {"wrong_anchor_validator_failures": old_anchor_error_count,
                                             "policy_rewrite_errors": old_policy_shape_error_count},
        "historical_error_attribution": {
            "wrong_anchor_failures": "source-contract/checker defect: the registry pointed at the following prose chunk while the PDF rule is a table note omitted from the historical calculation_notes bundle",
            "policy_rewrite_failures": "remain semantic model failures: the stored response encoded an authorized system policy as an ordinary rule with formula fields and an empty predicate",
            "table_note_citation_failures": "not scored as historical model error because the required table note was absent from that historical prompt",
            "comparison": "schema and source-bundle hashes differ; replay is diagnostic, not same-condition model comparison"
        },
        "responses": responses,
    }
    RESULT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"responses": len(responses),
                      "semantic_responses": sum(r.get("response_kind") == "semantic_authoring" for r in responses),
                      "full_modules": sum(r.get("response_kind") == "assembled_module" for r in responses),
                      "source_preflight": record["current_source"]["preflight"],
                      "historical_schema_matches": record["conditions"]["schema_same"],
                      "historical_bundle_matches": record["conditions"]["source_bundle_same"],
                      "result": str(RESULT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
