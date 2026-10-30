"""Recheck the saved Luna semantic candidate with the current provenance contract.

The first pass is intentionally read-only with respect to the saved candidate and
does not load authoring or held-out expectations.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
RUN_DIR = Path(__file__).resolve().parent
SEMANTIC = RUN_DIR / "formwork-semantic-candidate.json"
RESULT = RUN_DIR / "source-evidence-recheck-v2.json"
PDF = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
PAGE_MAP = ROOT / "data/processed/page_map.json"
SPEC = ROOT / "data/drafts/specs/공통/6-3-1.json"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    from backend.agent.tools.calc.policies import allowed_policy_ids, resolve_policy_source_evidence
    from pipeline.calculation_contract import build_source_bundle
    from pipeline.calculation_modules import (
        SEMANTIC_AUTHORING_SCHEMA, _schema_errors, assemble_semantic_candidate,
        validate_registered_policy_sources, validate_semantic_authoring,
    )

    candidate_bytes = SEMANTIC.read_bytes()
    semantic = json.loads(candidate_bytes)
    before_hash = sha(candidate_bytes)
    source_text, bundle = build_source_bundle(PDF, CHUNKS, PAGE_MAP, "공통", "6-3-1")
    source_hash = sha(source_text.encode("utf-8"))
    policy_ids = allowed_policy_ids("공통", "6-3-1")
    source_errors = validate_registered_policy_sources(source_text, policy_ids)
    schema_errors = _schema_errors(semantic, SEMANTIC_AUTHORING_SCHEMA)
    spec = json.loads(SPEC.read_text(encoding="utf-8"))["draft"]
    known_conditions = {item["condition"]: item for item in spec.get("blocked", [])}
    known_inputs = {item["name"]: item for item in spec.get("inputs", []) if item.get("name")}
    semantic_errors = validate_semantic_authoring(
        semantic, source_text, policy_ids, known_conditions, known_inputs)
    assembly = "not_attempted"
    assembly_error = None
    if not schema_errors and not semantic_errors:
        try:
            assemble_semantic_candidate(semantic, source_text, [],
                allowed_system_policies=policy_ids,
                known_blocked_conditions=known_conditions,
                known_input_fields=known_inputs)
            assembly = "passed"
        except (ValueError, TypeError, KeyError) as exc:
            assembly, assembly_error = "failed", str(exc)
    policy_id = next(iter(policy_ids))
    policy_evidence, policy_evidence_errors = resolve_policy_source_evidence(policy_id, bundle)
    after_hash = sha(SEMANTIC.read_bytes())
    result = {
        "candidate": {"path": str(SEMANTIC.relative_to(ROOT)), "sha256_before": before_hash,
                      "sha256_after": after_hash, "unchanged": before_hash == after_hash,
                      "schema": "pass" if not schema_errors else "fail",
                      "schema_errors": schema_errors,
                      "semantic_contract": "pass" if not semantic_errors else "fail",
                      "semantic_errors": semantic_errors, "assembly": assembly,
                      "assembly_error": assembly_error},
        "source": {"pdf_sha256": bundle["pdf_sha256"], "bundle_sha256": source_hash,
                   "calculation_evidence_count": len(bundle["calculation_notes"]),
                   "table_note_count": sum(n.get("kind") == "table_note" for n in bundle["calculation_notes"]),
                   "policy_preflight": "pass" if not source_errors else "fail",
                   "policy_preflight_errors": source_errors,
                   "policy_evidence_id": policy_evidence.get("evidence_id") if policy_evidence else None,
                   "policy_evidence_errors": policy_evidence_errors,
                   "pdf_page": 193, "printed_page": 137,
                   "gemini_bundle_comparison": "different source-bundle serialization; not same-condition replay"},
        "evaluation_cases": {"authoring_opened": False, "held_out_opened": False,
                             "authoring": "not_run_candidate_contract_not_passed",
                             "held_out": "not_run_authoring_gate_not_passed"},
        "independence": {"independent_first_generation": False,
                         "known_prior_policy_and_evaluation_discussion": True},
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"schema": result["candidate"]["schema"],
                      "semantic_contract": result["candidate"]["semantic_contract"],
                      "assembly": assembly, "candidate_unchanged": result["candidate"]["unchanged"],
                      "policy_preflight": result["source"]["policy_preflight"],
                      "authoring_expectations_opened": False, "held_out_opened": False,
                      "result": str(RESULT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
