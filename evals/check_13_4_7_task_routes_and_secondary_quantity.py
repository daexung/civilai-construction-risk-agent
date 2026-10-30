"""Verify source cells, task flags, note multipliers and priced secondary area."""
import json
import sys
from decimal import Decimal, ROUND_DOWN
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/기계설비/13-4-7.json"
OUT = ROOT / "evals/runtime_validation/13-4-7-task-routes-source-calc-audit-2026-10-19.json"
EXPECTED = {
    "떠내기": {"중유(B.C)": "0.25", "휘발유,경유": "0.13", "물": "0.03"},
    "오물제거": {"중유(B.C)": "0.25", "휘발유,경유": "0.13", "물": "0.07"},
    "녹제거": {"중유(B.C)": "0.02", "휘발유,경유": "0.02", "물": "0.02"},
    "되붓기": {"중유(B.C)": "0.1", "휘발유,경유": "0.07"},
    "드럼운반": {"중유(B.C)": "0.1", "휘발유,경유": "0.07"},
    "닦아내기": {"중유(B.C)": "0.05", "휘발유,경유": "0.03", "물": "0.01"},
}
TASK_INPUTS = {
    "떠내기": "task_scoop", "오물제거": "task_remove_dirt", "녹제거": "task_remove_rust",
    "되붓기": "task_pour_back", "드럼운반": "task_drum_transport", "닦아내기": "task_wipe",
}


def inputs_for(task: str, fluid: str, *, area: str = "1", door: bool = True,
               extra: str = "0", toxic: bool = False) -> dict:
    if task == "녹제거" and extra == "0":
        extra = "1"
    values = {"fluid_type": fluid, "area": area, "has_clean_out_door": door,
              "extra_rust_removal_area": extra, "has_toxic_gas": toxic}
    values.update({name: False for name in TASK_INPUTS.values()})
    values[TASK_INPUTS[task]] = True
    return values


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))["draft"]
    table = next(table for table in spec["tables"] if table["id"] == "p825-t1")
    checked_cells = []
    route_cases = 0
    for task, fluids in EXPECTED.items():
        for fluid, raw in fluids.items():
            assert Fraction(table["values"][task][fluid]) == Fraction(raw), (task, fluid)
            result = per_unit(spec, inputs_for(task, fluid), labor_only=True)
            assert result["status"] == "computed", result
            matching = [line for line in result["unit_lines"] if line["name"] == "보통인부"]
            selected = next(line for line in matching if line["exact"] != "0")
            assert Fraction(selected["applied"]) == Fraction(raw), (task, fluid, selected)
            checked_cells.append({"row": task, "column": fluid, "value": raw})
            route_cases += 1
    assert len(checked_cells) == 16
    for task in ("되붓기", "드럼운반"):
        result = per_unit(spec, inputs_for(task, "물"), labor_only=True)
        assert result["status"] == "unresolvable", result

    for task, raw in (("떠내기", "0.25"), ("오물제거", "0.25")):
        result = per_unit(spec, inputs_for(task, "중유(B.C)", door=False), labor_only=True)
        assert result["status"] == "computed", result
        line = next(line for line in result["unit_lines"] if line["exact"] != "0")
        assert Fraction(line["applied"]) == Fraction(raw) * Fraction(6, 5)
        route_cases += 1

    combined = {
        "fluid_type": "휘발유,경유", "area": "100", "task_scoop": True,
        "task_remove_dirt": True, "task_remove_rust": True, "task_pour_back": False,
        "task_drum_transport": False, "task_wipe": False, "has_clean_out_door": False,
        "extra_rust_removal_area": "20", "has_toxic_gas": False,
    }
    result = per_unit(spec, combined, labor_only=True)
    assert result["status"] == "computed", result
    extra_line = next(line for line in result["unit_lines"]
                      if line.get("quantity_input") == "extra_rust_removal_area")
    assert Fraction(extra_line["applied"]) == Fraction("0.016")
    priced = price_unit(spec, result["unit_lines"], select_rate_version("2026-10-19"),
                        combined, "2026-10-19")
    assert priced["status"] == "PARTIAL"
    expected_line_amounts = [
        (Fraction("0.156"), Decimal("172698")),
        (Fraction("0.156"), Decimal("172698")),
        (Fraction("0.02"), Decimal("172698")),
    ]
    # Each source line amount is rounded down independently to 0.1 won.
    expected_unit_labor = sum(
        (Decimal(rate.numerator) / Decimal(rate.denominator) * wage).quantize(
            Decimal("0.1"), rounding=ROUND_DOWN)
        for rate, wage in expected_line_amounts
    )
    assert Decimal(priced["labor_subtotal"]) == expected_unit_labor
    expected_displayed_unit_price = expected_unit_labor.quantize(Decimal("1"), rounding=ROUND_DOWN)
    expected_secondary_amount = (Decimal("0.016") * Decimal("20") * Decimal("172698")).quantize(
        Decimal("0.1"), rounding=ROUND_DOWN)
    expected_reference_labor = (expected_displayed_unit_price * 100 + expected_secondary_amount).quantize(
        Decimal("1"), rounding=ROUND_DOWN)
    assert Decimal(priced["reference_amounts"]["subtotals"]["노무비"]) == expected_reference_labor
    price_rows = [row for row in priced["lines"] if row.get("quantity_input")]
    assert len(price_rows) == 4 and price_rows[-1]["quantity"] == "0.32"
    assert price_rows[-1]["quantity_basis"] == "separate_total_input"

    toxic = per_unit(spec, inputs_for("떠내기", "중유(B.C)", toxic=True), labor_only=True)
    assert toxic["status"] == "blocked", toxic
    OUT.write_text(json.dumps({
        "status": "all_numeric_source_cells_task_routes_and_secondary_area_price_verified",
        "id": spec["id"],
        "source": {"physical_page": 825, "printed_page": 769, "numeric_cells": len(checked_cells),
                   "original_visual": "source-p825-tank-clean.png", "cells": checked_cells},
        "runtime": {"source_cell_route_cases": route_cases, "clean_out_door_cases": 2,
                    "secondary_rust_area": {"area": "20㎡", "source_rate": "0.02", "rule_factor": "0.8",
                                            "separately_priced_labor_quantity": "0.32인"},
                    "offline_price": {"basis_date": "2026-10-19", "independently_derived_labor_subtotal_per_㎡": str(expected_unit_labor),
                                      "displayed_unit_price_won": str(expected_displayed_unit_price),
                                      "primary_area": "100㎡", "reference_labor_amount": str(expected_reference_labor)},
                    "water_dash_routes_rejected": 2, "toxic_gas_still_blocked": True,
                    "full_rules_verified": False,
                    "partial_reason": "consumables are separately accounted; source table dash cases are not calculated"},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "verified", "source_cells": len(checked_cells),
                      "route_cases": route_cases, "price": priced["status"],
                      "per_primary_labor": str(expected_unit_labor)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
