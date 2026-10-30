"""Audit Roller Table's mixed quantity units and source percentage adjustment."""
import json
import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402

SPEC = json.loads((ROOT / "data/drafts/specs/기계설비/13-7-20.json").read_text(encoding="utf-8"))["draft"]
INPUTS = {"equipment_type": "Depiler table", "quantity": "2", "surface_area": "3",
          "tech_management_days": "4"}
EXPECTED = [
    ("기계기사", "인/일", "0.20", None),
    ("특별인부", "인/㎡", "0.10", "surface_area"),
    ("플랜트기계설치공", "인/ton", "0.79", "quantity"),
    ("특별인부", "인/ton", "0.263", "quantity"),
    ("플랜트기계설치공", "인/ton", "2.47", "quantity"),
    ("비계공", "인/ton", "1.05", "quantity"),
    ("특별인부", "인/ton", "1.17", "quantity"),
]


def main():
    table = next(t for t in SPEC["tables"] if t["id"] == "p888-t1")
    source_values = [table["values"][row][column] for row, column in [
        ("기술관리", "기계기사"), ("표면손질", "특별인부"),
        ("가조립및해체", "플랜트기계설치공"),
        ("조립설치_특별인부_가조립", "특별인부"),
        ("조립설치_플랜트기계설치공", "플랜트기계설치공"),
        ("조립설치_비계공", "비계공"), ("조립설치_특별인부", "특별인부")]]
    assert source_values == ["0.20", "0.10", "0.79", "0.263", "2.47", "1.05", "1.17"]
    note = table["values"]["검사및교정"]["수량"]
    assert note == "기술관리를 제외한 본 품의 10%"
    exclusions = {item["item"]: item["cite"] for item in SPEC["not_calculated"]}
    assert len(exclusions) == 4
    assert all(cite.get("chunk_id") == "p889-x0" and cite.get("quote")
               for cite in exclusions.values())

    result = per_unit(SPEC, INPUTS, labor_only=True)
    assert result.get("status") == "computed", result
    lines = result["unit_lines"]
    assert len(lines) == len(EXPECTED)
    for line, (name, unit, raw_rate, quantity_input) in zip(lines, EXPECTED):
        expected_rate = Fraction(raw_rate) * (Fraction(1) if name == "기계기사" else Fraction(11, 10))
        assert line["name"] == name and line["unit"] == unit
        assert Fraction(line["exact"]) == expected_rate, line
        assert line.get("quantity_input") == quantity_input, line
        cite = line["citations"][0]
        assert cite["internal_id"] == "p888-t1" and cite["value"] == raw_rate

    adjustment = result["provenance"]["input_rate_adjustments"][0]
    assert adjustment["rate"] == "10" and len(adjustment["resources"]) == 6
    assert all(change["name"] != "기계기사" for change in adjustment["resources"])
    rule_cite = adjustment["citations"][0]
    assert (rule_cite["internal_id"], rule_cite["row"], rule_cite["column"], rule_cite["value"]) == (
        "p888-t1", "검사및교정", "수량", note)

    # Independently apply each source rate to its own user quantity. This is
    # total person-days, including exactly 10% on non-management work.
    quantities = {"기계기사": Fraction("4"), "특별인부:㎡": Fraction("3"),
                  "플랜트기계설치공": Fraction("2"), "특별인부:ton": Fraction("2"),
                  "비계공": Fraction("2")}
    pre_adjustment = [Fraction("0.20") * 4, Fraction("0.10") * 3,
                      Fraction("0.79") * 2, Fraction("0.263") * 2,
                      Fraction("2.47") * 2, Fraction("1.05") * 2,
                      Fraction("1.17") * 2]
    expected_total = pre_adjustment[0] + sum(pre_adjustment[1:]) * Fraction(11, 10)
    actual_total = sum(Fraction(line["exact"]) * Fraction(INPUTS[line.get("quantity_input") or "tech_management_days"])
                       for line in lines)
    assert expected_total == Fraction("13.7646") and actual_total == expected_total

    equipment_routes = 0
    baseline_rate_vector = [(line["name"], line["unit"], Fraction(line["exact"])) for line in lines]
    equipment_field = next(field for field in SPEC["inputs"] if field["name"] == "equipment_type")
    for equipment_type in equipment_field["allowed_values"]:
        route_inputs = {**INPUTS, "equipment_type": equipment_type}
        route = per_unit(SPEC, route_inputs, labor_only=True)
        assert route.get("status") == "computed", (equipment_type, route)
        vector = [(line["name"], line["unit"], Fraction(line["exact"]))
                  for line in route["unit_lines"]]
        assert vector == baseline_rate_vector, (equipment_type, vector)
        equipment_routes += 1

    priced = price_unit(SPEC, lines, select_rate_version("2026-10-19"), INPUTS, "2026-10-19")
    assert priced["status"] == "PARTIAL", priced
    priced_lines = priced["lines"]
    # Local wage pricing must preserve each task-specific quantity route. The
    # only unresolved catalog mapping in this check is the source trade name.
    assert len(priced_lines) == len(lines)
    unresolved = [line["name"] for line in priced_lines if line.get("amount") is None]
    assert unresolved == ["기계기사"], (unresolved, priced_lines)
    assert all(Decimal(line["amount"]) >= 0 for line in priced_lines if line.get("amount") is not None)
    assert sum(1 for line in priced_lines if line.get("quantity") is not None) == len(lines)

    report = {"status": "passed", "source_pdf_page": 888, "printed_page": 832,
              "numeric_cells": 7, "source_percentage_cell": note,
              "task_rate_lines": len(lines), "source_percentage": "10% excluding 기계기사",
              "equipment_type_routes": equipment_routes,
              "source_exclusion_notes": len(exclusions),
              "expected_total_person_days": str(expected_total),
              "offline_price_status": priced["status"], "unresolved_wage_names": unresolved,
              "all_task_quantity_routes_priced_or_reported": True}
    output = ROOT / "evals/runtime_validation/13-7-20-mixed-quantity-source-calc-audit-2026-10-19.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
