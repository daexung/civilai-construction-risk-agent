"""Give each valve type its own exact source-table diameter/pressure axes."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/기계설비/13-1-3.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
AUDIT = ROOT / "evals/runtime_validation/per-unit-13-1-3-table-specific-axes-2026-10-19.json"
TABLES = {
    "Screwed Type": ("p790-t0", "screwed", ["10.5", "21.0∼27.5", "42∼62", "105", "176"]),
    "Welder-Back Screwed Type": ("p790-t1", "welder_back", ["10.5", "21∼27", "42∼63", "105", "176"]),
    "Flange Type": ("p791-t0", "flange", ["10.5", "21∼27", "42", "63", "105", "176"]),
}
TRADES = ["플랜트배관공", "특별인부"]
PDF_SAMPLES = {
    "p790-t0": ("ø25이하", ["0.066", "0.033", "0.066", "0.033", "0.093", "0.046",
                              "0.093", "0.046", "0.100", "0.050"]),
    "p790-t1": ("ø 25이하", ["0.107", "0.053", "0.107", "0.053", "0.133", "0.066",
                                "0.134", "0.067", "0.140", "0.066"]),
    "p791-t0": ("ø50", ["0.100", "0.050", "0.133", "0.067", "0.180", "0.090",
                          "0.198", "0.097", "0.220", "0.110", "0.293", "0.147"]),
}


def make_input(name: str, values: list[str], valve_type: str, ask: str, source: str) -> dict:
    return {"name": name, "type": "enum", "allowed_values": values, "unit": None,
            "required": True, "ask": ask, "source": source,
            "when": {"input": "valve_type", "equals": valve_type}}


def main() -> int:
    package = json.loads(SPEC_PATH.read_text(encoding="utf8"))
    spec = package["draft"]
    tables = {item["id"]: item for item in spec["tables"]}
    inputs_by_name = {item["name"]: item for item in spec["inputs"]}
    assert set(TABLES).issubset(set(inputs_by_name["valve_type"]["allowed_values"]))
    scoped_names = {"diameter", "pressure", "diameter_screwed", "pressure_screwed",
                    "diameter_welder_back", "pressure_welder_back",
                    "diameter_flange", "pressure_flange"}
    new_inputs = [item for item in spec["inputs"] if item["name"] not in scoped_names]
    selector_values = {}
    row_inputs = {}
    column_inputs = {}
    trades_by_table = {}
    expected_routes = 0
    for valve_type, (table_id, suffix, pressures) in TABLES.items():
        table = tables[table_id]
        rows = list(table["values"])
        assert rows and all(len(table["values"][row]) == len(pressures) * len(TRADES)
                            for row in rows), (table_id, rows[:2])
        first_row_columns = list(table["values"][rows[0]])
        parsed_pressures = []
        for column in first_row_columns:
            pressure, _, trade = column.partition("_")
            if trade not in TRADES:
                raise AssertionError((table_id, column))
            if pressure not in parsed_pressures:
                parsed_pressures.append(pressure)
        assert parsed_pressures == pressures, (table_id, parsed_pressures, pressures)
        diameter_name, pressure_name = f"diameter_{suffix}", f"pressure_{suffix}"
        new_inputs.extend([
            make_input(diameter_name, rows, valve_type, f"{valve_type} 밸브의 구경은?",
                       f"{table_id}의 구경 행 머리글"),
            make_input(pressure_name, pressures, valve_type, f"{valve_type} 밸브의 사용압력은?",
                       f"{table_id}의 사용압력 머리글"),
        ])
        selector_values[valve_type] = table_id
        row_inputs[table_id] = diameter_name
        column_inputs[table_id] = pressure_name
        trades_by_table[table_id] = TRADES
        for row in rows:
            # The selected rate cells are exact source-labelled columns.
            for pressure in pressures:
                for trade in TRADES:
                    key = f"{pressure}_{trade}"
                    assert key in table["values"][row], (table_id, row, key)
                    expected_routes += 1
        sample_row, sample_values = PDF_SAMPLES[table_id]
        row_values = table["values"][sample_row]
        actual_sample = [row_values[f"{pressure}_{trade}"]
                         for pressure in pressures for trade in TRADES]
        assert actual_sample == sample_values, (table_id, actual_sample, sample_values)

    spec["inputs"] = new_inputs
    rate = spec["quantity_model"]["params"]["unit_rate_table"]
    rate["table_selector"] = {"input": "valve_type", "values": selector_values}
    rate["row_input"] = None
    rate["column_input"] = None
    rate["row_input_by_table"] = row_inputs
    rate["column_input_by_table"] = column_inputs
    rate["trades_by_table"] = trades_by_table
    SPEC_PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

    routes = outputs = 0
    for valve_type, (table_id, suffix, pressures) in TABLES.items():
        table = tables[table_id]
        diameter_field = f"diameter_{suffix}"
        pressure_field = f"pressure_{suffix}"
        for diameter, row in table["values"].items():
            for pressure in pressures:
                inputs = {"valve_type": valve_type, diameter_field: diameter,
                          pressure_field: pressure, "quantity": "1"}
                result = per_unit(spec, inputs)
                assert result["status"] == "computed", (inputs, result)
                for trade in TRADES:
                    column = f"{pressure}_{trade}"
                    line = next(item for item in result["unit_lines"] if item["name"] == trade)
                    assert Fraction(line["exact"]) == Fraction(row[column]), (
                        inputs, trade, line["exact"], row[column])
                    cite = next(c for c in line["citations"] if c.get("internal_id") == table_id)
                    assert (cite.get("row"), cite.get("column"), cite.get("value")) == (
                        diameter, column, row[column])
                    outputs += 1
                routes += 1
        # Apply a non-unit quantity to one complete source row per table.
        diameter = next(iter(table["values"]))
        for pressure in pressures:
            result = per_unit(spec, {"valve_type": valve_type, diameter_field: diameter,
                                     pressure_field: pressure, "quantity": "3"})
            assert result["status"] == "computed", result
            for trade in TRADES:
                assert Fraction(next(line for line in result["unit_lines"]
                                     if line["name"] == trade)["exact"]) == Fraction(
                                         table["values"][diameter][f"{pressure}_{trade}"])
            routes += 1
            outputs += len(TRADES)
    extra_quantity_routes = sum(len(value[2]) for value in TABLES.values())
    assert expected_routes == 340 and routes == 186 and outputs == 372, (
        expected_routes, routes, outputs)

    validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(CHUNKS), file_sha256(CHUNKS))
    assert not validation["format_issues"], validation["format_issues"]
    assert not validation["citation_issues"], validation["citation_issues"]
    record = {"status": "pass", "section": "기계설비/13-1-3", "source_tables": list(selector_values.values()),
        "source": "Original PDF pp.790-791 / printed pp.734-735, all three distinct pressure header groups visually checked",
        "independent_pdf_cells": 32,
        "exact_source_pressure_domains": {table_id: values[2] for table_id, values in TABLES.items()},
        "exact_diameter_pressure_routes": expected_routes // len(TRADES),
        "additional_quantity_3_routes": extra_quantity_routes,
        "all_quantity_routes_checked": routes,
        "exact_rate_outputs_with_table_citations": outputs,
        "quantities_tested": ["1", "3"],
        "format_preflight": "pass", "citation_preflight": "pass",
        "runtime_branch": "column_input_by_table is exercised by this spec only",
        "source_range_normalization": "none; pressure ranges remain table-specific and exact",
        "full_rule_verification": False,
        "open_note": "separate tool/equipment cost note is outside this table-axis audit"}
    AUDIT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
