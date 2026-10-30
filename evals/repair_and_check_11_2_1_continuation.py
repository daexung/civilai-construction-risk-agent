"""Route PE butt-fusion diameters to their exact continuation-page tables."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/기계설비/11-2-1.json"
CHUNKS_PATH = ROOT / "data/processed/chunks.all.jsonl"
AUDIT_PATH = ROOT / "evals/runtime_validation/per-unit-11-2-1-continuation-2026-10-19.json"
LOW = {"ø 25": ("0.081", "0.019"), "32": ("0.094", "0.022"),
       "40": ("0.108", "0.025"), "50": ("0.141", "0.033")}
HIGH = {"63": ("0.184", "0.043"), "75": ("0.210", "0.049"),
        "90": ("0.244", "0.057"), "110": ("0.288", "0.067"),
        "125": ("0.322", "0.075"), "140": ("0.355", "0.083"),
        "160": ("0.400", "0.094"), "180": ("0.444", "0.104"),
        "200": ("0.489", "0.114"), "225": ("0.545", "0.127"),
        "250": ("0.601", "0.140"), "280": ("0.667", "0.156"),
        "315": ("0.745", "0.174"), "355": ("0.835", "0.195"),
        "400": ("0.935", "0.219")}
TRADES = ["배 관 공(인)", "보통인부(인)"]


def main() -> int:
    package = json.loads(SPEC_PATH.read_text(encoding="utf8"))
    spec = package["draft"]
    params = spec["quantity_model"]["params"]
    rate = params["unit_rate_table"]
    inputs = next(field for field in spec["inputs"] if field["name"] == "pipe_diameter")
    assert inputs["allowed_values"] == [*LOW.keys(), *HIGH.keys()]
    expected = {**LOW, **HIGH}
    rate["table_selector"] = {"input": "pipe_diameter", "values": {
        diameter: ("p770-t3" if diameter in LOW else "p771-t0") for diameter in expected
    }}
    rate["row_input"] = "pipe_diameter"
    rate["row_input_by_table"] = {"p770-t3": "pipe_diameter", "p771-t0": "pipe_diameter"}
    rate["trades_by_table"] = {"p770-t3": TRADES, "p771-t0": TRADES}
    SPEC_PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

    tables = {table["id"]: table for table in spec["tables"]}
    for diameter, values in expected.items():
        table_id = "p770-t3" if diameter in LOW else "p771-t0"
        table = tables[table_id]
        row = table["values"][diameter]
        assert [row[trade] for trade in TRADES] == list(values), (diameter, row, values)
    assert set(tables["p770-t3"]["values"]) == set(LOW)
    assert set(tables["p771-t0"]["values"]) == set(HIGH)

    routes = outputs = 0
    for diameter, values in expected.items():
        selected = "p770-t3" if diameter in LOW else "p771-t0"
        for method in ["버트융착식", "전자소켓(전기융착기)"]:
            for quantity in ["1", "3"]:
                result = per_unit(spec, {"pipe_diameter": diameter,
                                         "joint_method": method, "quantity": quantity})
                assert result["status"] == "computed", (diameter, method, quantity, result)
                got = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
                assert got == {trade: Fraction(values[i]) for i, trade in enumerate(TRADES)}, (
                    diameter, method, quantity, got, values)
                for line in result["unit_lines"]:
                    citation = line["citations"]
                    match = [item for item in citation if item.get("internal_id") == selected]
                    assert len(match) == 1 and match[0].get("row") == diameter
                    assert match[0].get("value") == values[TRADES.index(line["name"])]
                    assert Fraction(line["exact"]) * Fraction(quantity) == (
                        Fraction(values[TRADES.index(line["name"])]) * Fraction(quantity))
                routes += 1
                outputs += len(got)
    assert routes == 76 and outputs == 152

    chunks = load_chunks(CHUNKS_PATH)
    validation = validate_one(SPEC_PATH, ROOT / "data/drafts", chunks, file_sha256(CHUNKS_PATH))
    assert not validation["format_issues"], validation["format_issues"]
    assert not validation["citation_issues"], validation["citation_issues"]
    audit = {"status": "pass", "section": "기계설비/11-2-1",
             "source_tables": ["p770-t3", "p771-t0"],
             "source": "Original PDF pp.770-771 (printed pp.714-715), both continuation grids visually checked",
             "independent_source_cells": 38, "diameter_values_mapped_exactly": len(expected),
             "exact_diameter_method_quantity_routes": routes,
             "exact_rate_outputs_with_table_citations": outputs,
             "quantities_tested": ["1", "3"],
             "format_preflight": "pass", "citation_preflight": "pass",
             "full_rule_verification": False,
             "open_note": "machine-cost 5% rule remains separate; no cost is asserted by this route audit"}
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
