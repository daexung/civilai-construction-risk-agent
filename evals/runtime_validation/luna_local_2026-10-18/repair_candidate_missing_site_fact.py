"""Version the saved candidate with a conditional question for a missing site fact."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
RUN_DIR = Path(__file__).resolve().parent
SOURCE = RUN_DIR / "assembled-source-repaired-v5-module.json"
OUTPUT = RUN_DIR / "assembled-source-repaired-v6-module.json"


def main() -> int:
    from pipeline.calculation_modules import validate_candidate

    original = json.loads(SOURCE.read_text(encoding="utf-8"))
    candidate = copy.deepcopy(original)
    if not any(rule.get("id") == "height-lifting-equipment-fact" for rule in candidate["rules"]):
        field = next(item for item in candidate["inputs"] if item.get("name") == "lifting_equipment_used")
        question_rule = {
            "id": "height-lifting-equipment-fact",
            "when": {"height": {"gt": 7}, "crane_used": False},
            "operation": "require_field",
            "policy_inputs": ["lifting_equipment_used"],
            "asks": {"lifting_equipment_used": field["ask"]},
            "source": field["source"],
            "reason": "This is a site fact needed to determine whether the source note's height adjustment applies.",
        }
        height_index = next(index for index, rule in enumerate(candidate["rules"])
                            if rule.get("system_policy_ref"))
        candidate["rules"].insert(height_index, question_rule)
        candidate["version"] = "1.0.1"
        contract = candidate["calculation_contract"]
        contract["executor"]["module_version"] = candidate["version"]
        contract["application"]["order"].insert(height_index, question_rule["id"])
        for mapping in contract["source"]["note_rule_map"]:
            if mapping.get("note_id") == candidate["policy_evidence_ids"][
                    "formwork-6-3-1-height-started-interval-compound-v1"]:
                mapping["rule_ids"].append(question_rule["id"])
        contract["application"]["conditions"].append(
            "When height exceeds 7 m without a continuous crane, ask whether general lifting equipment is used if that fact is missing.")
    candidate["review_status"] = "candidate_unreviewed"
    errors = validate_candidate(candidate,
        allowed_system_policies={"formwork-6-3-1-height-started-interval-compound-v1"}, require_contract=True)
    if errors:
        raise RuntimeError("repaired candidate validation failed: " + "; ".join(errors))
    if OUTPUT.exists():
        raise RuntimeError("v6 candidate already exists; refusing overwrite")
    OUTPUT.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "candidate", "version": candidate["version"],
                      "added_rule": "height-lifting-equipment-fact", "validation": "passed",
                      "output": str(OUTPUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
