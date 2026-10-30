"""Independent source-cell and exact coefficient check for civil 9-13-1."""
import hashlib
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from pipeline.validate_drafts import DEFAULT_CHUNKS, DEFAULT_DRAFTS_DIR, file_sha256, load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/토목/9-13-1.json"
AUDIT = ROOT / "evals/runtime_validation/per-unit-9-13-1-resurvey-source-audit-2026-10-19.json"
EXPECTED = {"지적기사": Fraction("0.84"), "지적산업기사": Fraction("0.83"), "지적기능사": Fraction("0.76")}
COEFFICIENTS = {"군지역": Fraction("1.00"), "시지역": Fraction("1.26"), "구지역": Fraction("1.36")}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p603-t0")
    region_table = next(t for t in spec["tables"] if t["id"] == "p603-t1")
    assert table["unit"] == "인/지구"
    cells = []
    source_values = {"지적기사": "0.84", "지적산업기사": "0.83", "지적기능사": "0.76"}
    for trade, value in EXPECTED.items():
        columns = [c for c, raw in table["values"]["합계"].items() if raw == source_values[trade]]
        assert len(columns) == 1, (trade, columns)
        cells.append({"table_id": "p603-t0", "row": "합계", "column": columns[0], "value": str(value)})
    for region, coefficient in COEFFICIENTS.items():
        assert Fraction(region_table["values"]["계수"][region]) == coefficient
        cells.append({"table_id": "p603-t1", "row": "계수", "column": region, "value": str(coefficient)})
    routes = []
    for region, coefficient in COEFFICIENTS.items():
        result = per_unit(spec, {"quantity": "1", "region_type": region, "survey_method": "지상측량"})
        assert result["status"] == "computed", result
        actual = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
        expected = {trade: rate * coefficient for trade, rate in EXPECTED.items()}
        assert actual == expected, (region, actual, expected)
        assert all(line["unit"] == "인·일/지구" for line in result["unit_lines"])
        assert all({c.get("internal_id") for c in line["citations"]} >= {"p603-t0", "p603-t1", "p603-x16"}
                   for line in result["unit_lines"])
        routes.append({"region": region, "source_coefficient": str(coefficient),
                       "rates": {name: str(value) for name, value in actual.items()}, "status": "computed"})
    blocked = per_unit(spec, {"quantity": "1", "region_type": "군지역", "survey_method": "드론측량"})
    assert blocked["status"] == "blocked" and any(c.get("internal_id") == "p604-x0" for c in blocked["citations"])
    validation = validate_one(SPEC, DEFAULT_DRAFTS_DIR.resolve(), load_chunks(DEFAULT_CHUNKS), file_sha256(DEFAULT_CHUNKS))
    assert validation["ok"], validation
    audit = {"id": spec["id"], "status": "source_cells_routes_and_alternate_method_gate_verified",
             "source": {"physical_page": 603, "printed_page": 547, "image": "evals/runtime_validation/source-p603-resurvey.png",
                        "image_sha256": sha(ROOT / "evals/runtime_validation/source-p603-resurvey.png"),
                        "table_pages_visual_reviewed": True, "independent_numeric_cells": cells,
                        "denominator_source": "p604-x0: one district basis is 400–450 parcels and is unchanged when parcel count varies"},
             "runtime": {"exact_region_routes": routes, "drone_route": "blocked by the explicit separate-standard note in p604-x0",
                         "validator": validation, "full_rule_verification": False},
             "unmodeled_source_items": ["travel", "boat rental", "equipment and consumables", "control points", "monuments",
                                         "drone postprocessing software"],
             "spec_sha256": sha(SPEC), "per_unit_sha256": sha(ROOT / "backend/agent/tools/calc/per_unit.py")}
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cells": len(cells), "ground_routes": len(routes), "drone": blocked["status"],
                      "validator": validation["ok"], "audit": str(AUDIT.relative_to(ROOT))}, ensure_ascii=False))

if __name__ == "__main__":
    main()
