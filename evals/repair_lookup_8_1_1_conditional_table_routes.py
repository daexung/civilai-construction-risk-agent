"""Route mutually exclusive 8-1-1 criteria to their exact source table."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/공통/8-1-1.json"
BACKUP = ROOT / "tmp/8-1-1-spec-before-conditional-source-routing.json"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    fields = {field["name"]: field for field in draft["inputs"]}
    shutil.copy2(SPEC, BACKUP)
    fields["lookup_type"]["source_table_map"] = {
        "작업종류별": "p219-t0", "운반거리별": "p219-t1"
    }
    fields["work_type"]["when"] = {"input": "lookup_type", "equals": "작업종류별"}
    fields["earth_work_type"]["when"] = {"input": "lookup_type", "equals": "운반거리별"}
    fields["haul_distance"]["when"] = {"input": "lookup_type", "equals": "운반거리별"}
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {"cause": "the spec required axes from two alternative source tables at once",
              "exact_routes": fields["lookup_type"]["source_table_map"],
              "conditional_inputs": ["work_type", "earth_work_type", "haul_distance"],
              "source_matrices_modified": False,
              "backup": str(BACKUP.relative_to(ROOT)),
              "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest()}
    out = ROOT / "evals/runtime_validation/repair-8-1-1-conditional-source-routing-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
