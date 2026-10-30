"""Create an unregistered, source-verified migration candidate from the legacy module."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
RUN_DIR = Path(__file__).resolve().parent
SOURCE_MODULE = ROOT / "data/calculation_modules/approved/formwork-adjustments-v1.json"
SEMANTIC_MODULE = RUN_DIR / "assembled-source-repaired-v5-module.json"
OUTPUT = RUN_DIR / "formwork-adjustments-v1-provenance-migration-candidate.json"


def main() -> int:
    from backend.agent.tools.calc.policies import POLICIES, resolve_policy_source_evidence
    from pipeline.calculation_contract import build_source_bundle
    from pipeline.calculation_modules import validate_candidate

    legacy = json.loads(SOURCE_MODULE.read_text(encoding="utf-8"))
    semantic = json.loads(SEMANTIC_MODULE.read_text(encoding="utf-8"))
    pdf = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
    _, bundle = build_source_bundle(pdf, ROOT / "data/processed/chunks.all.jsonl",
                                    ROOT / "data/processed/page_map.json", "공통", "6-3-1")
    policy_id = "formwork-6-3-1-height-started-interval-compound-v1"
    evidence, evidence_errors = resolve_policy_source_evidence(policy_id, bundle)
    if evidence_errors or not evidence:
        raise RuntimeError("source verification failed: " + "; ".join(evidence_errors))
    locator = copy.deepcopy(POLICIES[policy_id]["source_locator"])
    locator["evidence_id"] = evidence["evidence_id"]
    module = copy.deepcopy(legacy)
    module["review_status"] = "candidate_unreviewed"
    module["source_hash"] = bundle["pdf_sha256"]
    module["policy_note_ids"] = {policy_id: evidence["evidence_id"]}
    module["policy_evidence_ids"] = {policy_id: evidence["evidence_id"]}
    module["policy_versions"] = {policy_id: POLICIES[policy_id]["version"]}
    module["policy_sources"] = {policy_id: copy.deepcopy(POLICIES[policy_id]["source"])}

    # This compatibility migration preserves the old questions/rules and output
    # factors. The retired operation is renamed to the typed site-fact question
    # operation; no rate or accumulation formula is changed here.
    for rule in module["rules"]:
        if rule.get("operation") == "ask_policy":
            rule["operation"] = "require_field"
    ids = ("height-input-required", "height-policy-ref", "roof-slope-reduction")
    for rule, rule_id in zip(module["rules"], ids):
        rule["id"] = rule_id

    contract = copy.deepcopy(semantic["calculation_contract"])
    contract["source"]["pdf_sha256"] = bundle["pdf_sha256"]
    contract["source"]["policy_evidence"] = {policy_id: locator}
    for mapping in contract["source"]["note_rule_map"]:
        if mapping.get("note_id") == evidence["evidence_id"]:
            mapping["rule_ids"] = ["height-input-required", "height-policy-ref", "roof-slope-reduction"]
    contract["application"]["order"] = list(ids)
    contract["application"]["system_policies"] = [policy_id]
    contract["application"]["policy_versions"] = {policy_id: POLICIES[policy_id]["version"]}
    contract["application"]["policy_sources"] = {policy_id: copy.deepcopy(POLICIES[policy_id]["source"])}
    contract["executor"]["module_version"] = module["version"]
    module["calculation_contract"] = contract

    errors = validate_candidate(module, allowed_system_policies={policy_id}, require_contract=True)
    if errors:
        raise RuntimeError("migrated candidate validation failed: " + "; ".join(errors))
    if OUTPUT.exists():
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if existing != module:
            raise RuntimeError("migration output exists with different contents; refusing overwrite")
    else:
        OUTPUT.write_text(json.dumps(module, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "candidate", "review_status": module["review_status"],
                      "source_evidence_id": evidence["evidence_id"], "validation": "passed",
                      "output": str(OUTPUT.relative_to(ROOT)),
                      "approved_source_unchanged": json.loads(SOURCE_MODULE.read_text(encoding="utf-8")) == legacy},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
