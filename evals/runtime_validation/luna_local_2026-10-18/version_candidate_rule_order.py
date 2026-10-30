"""Version the eval candidate to make declared calculation order explicit."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
RUN_DIR = Path(__file__).resolve().parent
SOURCE = RUN_DIR / "assembled-source-repaired-v6-module.json"
OUTPUT = RUN_DIR / "assembled-source-repaired-v7-module.json"


def main() -> int:
    from pipeline.calculation_modules import validate_candidate

    candidate = copy.deepcopy(json.loads(SOURCE.read_text(encoding="utf-8")))
    desired_order = ["height-lifting-equipment-fact", "height-policy-ref",
                     "roof-slope-reduction", "continuous-crane-no-output-deduction"]
    actual = {rule.get("id") for rule in candidate["rules"]}
    if set(desired_order) != actual:
        raise RuntimeError("candidate rules differ from the reviewed order; refusing to rewrite")
    candidate["version"] = "1.0.2"
    candidate["calculation_contract"]["executor"]["module_version"] = candidate["version"]
    candidate["calculation_contract"]["application"]["order"] = desired_order
    errors = validate_candidate(candidate,
        allowed_system_policies={"formwork-6-3-1-height-started-interval-compound-v1"}, require_contract=True)
    if errors:
        raise RuntimeError("ordered candidate validation failed: " + "; ".join(errors))
    if OUTPUT.exists():
        raise RuntimeError("v7 candidate already exists; refusing overwrite")
    OUTPUT.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "candidate", "version": candidate["version"],
                      "application_order": desired_order, "validation": "passed",
                      "output": str(OUTPUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
