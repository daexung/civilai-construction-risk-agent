"""Source-derived checks for garden-stone per-ton labor and excavator time."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader

from backend.agent.tools.calc.per_unit import per_unit

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    package = json.loads(next((ROOT / "data/drafts/specs").rglob("4-4-1.json")).read_text(encoding="utf-8"))
    spec = package["draft"]
    assert package["calc_type"] == "per_unit"
    source = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))).pages[152].extract_text() or ""
    for value in ("1.212", "1.040", "0.968", "0.836", "0.657", "0.684", "20%"):
        assert value in source, value

    table = spec["tables"][0]["values"]
    labor_row, equipment_row = list(table)
    operation_values = next(x for x in spec["inputs"] if x["name"] == "operation")["allowed_values"]
    # The source headers are retained in full after restoring the grouped label.
    cases = [(operation_values[0], "10", "1.212", "0.657"),
             (operation_values[0], "20", "1.040", "0.684"),
             (operation_values[1], "10", "0.968", "0.657"),
             (operation_values[1], "20", "0.836", "0.684")]
    for operation, quantity, labor_rate, equipment_rate in cases:
        result = per_unit(spec, {"operation": operation, "quantity": quantity,
                                 "difficulty_surcharge": "20"})
        assert result["status"] == "computed", result
        rates = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
        assert rates[labor_row] == Fraction(labor_rate) * Fraction(6, 5)
        assert rates[equipment_row] == Fraction(equipment_rate) * Fraction(6, 5)
        assert result["unit_lines"][0]["unit"] == "인/ton"
        assert result["unit_lines"][1]["unit"] == "hr/ton"
        # Independently apply each printed per-ton rate to quantity and the selected surcharge.
        totals = (Fraction(labor_rate) * int(quantity) * Fraction(6, 5),
                  Fraction(equipment_rate) * int(quantity) * Fraction(6, 5))
        assert totals[0] == rates[labor_row] * int(quantity)
        assert totals[1] == rates[equipment_row] * int(quantity)
        assert all(len(line["citations"]) >= 2 for line in result["unit_lines"])

    zero = per_unit(spec, {"operation": operation_values[0], "quantity": "1",
                           "difficulty_surcharge": "0"})
    assert zero["status"] == "computed"
    outside = per_unit(spec, {"operation": operation_values[0], "quantity": "1",
                              "difficulty_surcharge": "20.01"})
    assert outside["status"] == "rejected", outside
    print("PASS p.97 four source columns, 20ton boundary, labor/equipment units, 0–20% input adjustment, and citations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
