"""Create a separately labeled provenance repair and run trusted evaluations.

The original saved semantic candidate is read-only. Expected values stay inside
the trusted evaluator and are never emitted into this record.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
RUN_DIR = Path(__file__).resolve().parent
ORIGINAL = RUN_DIR / "formwork-semantic-candidate.json"
REPAIRED = RUN_DIR / "formwork-semantic-candidate-source-repaired-v3.json"
RESULT = RUN_DIR / "source-repaired-v5-evaluation.json"
PDF = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
PAGE_MAP = ROOT / "data/processed/page_map.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    from backend.agent.tools.calc.policies import allowed_policy_ids
    from pipeline.calculation_contract import build_source_bundle
    from pipeline.calculation_modules import (
        SEMANTIC_AUTHORING_SCHEMA, _schema_errors, assemble_semantic_candidate,
        collect_known_input_fields, load_case_file, run_candidate_case,
        validate_semantic_authoring,
    )

    original_bytes = ORIGINAL.read_bytes()
    semantic = json.loads(original_bytes)
    source_text, bundle = build_source_bundle(PDF, CHUNKS, PAGE_MAP, "공통", "6-3-1")
    table_notes = [item for item in bundle["calculation_notes"] if item.get("kind") == "table_note"]
    if len(table_notes) != 1:
        raise RuntimeError("expected the explicit table '비고' evidence to resolve uniquely")
    table_note_id = table_notes[0]["evidence_id"]
    # Migrate the already-authored legacy positional citations once, by matching
    # them to the unchanged parser snapshot. The saved candidate itself stays read-only.
    parser_chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    section_chunks = [item for item in parser_chunks
                      if item.get("division") == "공통" and item.get("section_no") == "6-3-1"]
    index_to_evidence = {}
    for index, chunk in enumerate(section_chunks):
        match = next((item for item in bundle["calculation_notes"]
                      if (item.get("chunk") or {}).get("chunk_id") == chunk.get("chunk_id")), None)
        if match:
            index_to_evidence[f"공통/6-3-1/chunk-{index}"] = match["evidence_id"]
    for rule in [*semantic.get("rules", []), *semantic.get("policy_references", [])]:
        rule["source_note_ids"] = [index_to_evidence.get(note_id, note_id)
                                    for note_id in rule.get("source_note_ids", [])]
    for item in semantic["note_interpretations"]:
        item["note_id"] = index_to_evidence.get(item["note_id"], item["note_id"])
    semantic["note_interpretations"].append({
        "note_id": table_note_id,
        "rule_ids": ["height-policy-ref", "roof-slope-reduction",
                     "continuous-crane-no-output-deduction"],
        "excluded_reason": (
            "The scattered small-formwork clause selects the existing base-output complexity row. "
            "The crane clause is mapped to no output deduction; its added equipment quantity/cost "
            "is separate from this daily-output adjustment and remains explicitly unpriced/partial."
        ),
    })
    # The source rule reuses this existing typed input; it must not redeclare it.
    semantic["inputs"] = [field for field in semantic.get("inputs", [])
                          if field.get("name") != "lifting_equipment_used"]
    repaired_bytes = (json.dumps(semantic, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if REPAIRED.exists():
        if REPAIRED.read_bytes() != repaired_bytes:
            raise RuntimeError("existing provenance-repair artifact differs; refusing overwrite")
    else:
        REPAIRED.write_bytes(repaired_bytes)

    schema_errors = _schema_errors(semantic, SEMANTIC_AUTHORING_SCHEMA)
    policy_ids = allowed_policy_ids("공통", "6-3-1")
    authoring_cases = load_case_file(ROOT / "evals/calculation_modules/formwork_authoring_cases.json")
    spec = authoring_cases[0]["spec"]
    known_conditions = {item["condition"]: item for item in spec.get("blocked", [])}
    known_inputs = collect_known_input_fields(authoring_cases)
    semantic_errors = validate_semantic_authoring(semantic, source_text, policy_ids,
                                                  known_conditions, known_inputs)
    authoring = {"status": "not_run", "passed": 0, "total": len(authoring_cases), "failures": []}
    final = {"status": "not_run", "passed": 0, "total": None, "failures": []}
    assembly_errors = []
    assembled = None
    if not schema_errors and not semantic_errors:
        try:
            assembled = assemble_semantic_candidate(semantic, source_text, authoring_cases,
                allowed_system_policies=policy_ids,
                known_blocked_conditions=known_conditions, known_input_fields=known_inputs)
        except (ValueError, TypeError, KeyError) as exc:
            assembly_errors.append(str(exc))
    if assembled is not None:
        author_failures = []
        for index, case in enumerate(authoring_cases):
            errors = run_candidate_case(assembled, {**case, "allowed_system_policies": sorted(policy_ids)})
            if errors:
                # Retain failure class and field only; never persist reference or observed values.
                fields_failed = sorted({error.split(":", 1)[0] for error in errors})
                author_failures.append({"case_id": case.get("id", str(index)),
                                        "mismatched_fields": fields_failed})
        authoring = {"status": "passed" if not author_failures else "failed",
                     "passed": len(authoring_cases) - len(author_failures),
                     "total": len(authoring_cases), "failures": author_failures}
        if not author_failures:
            final_cases = load_case_file(ROOT / "evals/calculation_modules/formwork_final_evaluation_cases.json")
            author_ids = {case.get("id") for case in authoring_cases}
            final_ids = {case.get("id") for case in final_cases}
            if author_ids & final_ids:
                final = {"status": "blocked_overlap", "passed": 0, "total": len(final_cases),
                         "overlap_count": len(author_ids & final_ids), "failures": []}
            else:
                failures = []
                for index, case in enumerate(final_cases):
                    errors = run_candidate_case(assembled, {**case, "allowed_system_policies": sorted(policy_ids)})
                    if errors:
                        fields_failed = sorted({error.split(":", 1)[0] for error in errors})
                        failures.append({"case_id": case.get("id", str(index)),
                                         "mismatched_fields": fields_failed})
                final = {"status": "passed" if not failures else "failed",
                         "passed": len(final_cases) - len(failures),
                         "total": len(final_cases), "failures": failures,
                         "sent_to_model": False}
    if assembled is not None:
        artifact = RUN_DIR / "assembled-source-repaired-v5-module.json"
        artifact.write_text(json.dumps(assembled, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    record = {
        "candidate": {"original_path": str(ORIGINAL.relative_to(ROOT)),
                      "original_sha256": digest(original_bytes), "original_unchanged": digest(ORIGINAL.read_bytes()) == digest(original_bytes),
                      "repaired_path": str(REPAIRED.relative_to(ROOT)),
                      "repaired_sha256": digest(repaired_bytes), "repair_count": 3,
                      "repair_scope": ["Rebound old positional citations to stable evidence IDs for the unchanged parser snapshot.",
                                       "Added explicit note_interpretations for the table note.",
                                       "Removed the duplicate declaration of the existing typed lifting_equipment_used field."],
                      "prior_repair_artifact_preserved": str((RUN_DIR / "formwork-semantic-candidate-source-repaired.json").relative_to(ROOT))},
        "source": {"pdf_sha256": bundle["pdf_sha256"], "bundle_sha256": digest(source_text.encode("utf-8")),
                   "stable_table_note_id": table_note_id, "pdf_page": 193, "printed_page": 137},
        "validation": {"schema": "pass" if not schema_errors else "fail", "schema_errors": schema_errors,
                       "semantic_contract": "pass" if not semantic_errors else "fail",
                       "semantic_errors": semantic_errors, "assembly_errors": assembly_errors},
        "authoring": authoring, "held_out_final": final,
        "evaluation_integrity": {"expected_values_emitted": False, "candidate_or_prompt_received_expected_values": False,
                                 "held_out_loaded_after_authoring_pass_only": True,
                                 "independent_generation_claim": False,
                                 "reason": "Known policy and prior evaluation discussion; this is a direct Luna-authored artifact."},
    }
    RESULT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"semantic_contract": record["validation"]["semantic_contract"],
                      "assembly_errors": len(assembly_errors),
                      "authoring": authoring["status"], "authoring_passed": authoring["passed"],
                      "authoring_total": authoring["total"], "held_out_final": final["status"],
                      "held_out_passed": final["passed"], "held_out_total": final["total"],
                      "original_unchanged": record["candidate"]["original_unchanged"],
                      "result": str(RESULT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
