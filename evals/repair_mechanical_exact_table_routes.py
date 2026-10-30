"""Repair exact source table routing for 13-3-2 and 13-5-12."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"


def spec_path(section: str) -> Path:
    return ROOT / "data/drafts/specs/기계설비" / f"{section}.json"


def update_route(section: str) -> dict:
    path = spec_path(section)
    pkg = json.loads(path.read_text(encoding="utf8"))
    spec = pkg["draft"]
    rate = spec["quantity_model"]["params"]["unit_rate_table"]
    rate["column_input"] = None  # resource names are the exact source columns
    if section == "13-3-2":
        rate["table_selector"] = {"input": "equipment_type", "values": {
            "Boiler 본체": "p819-t1", "Duct": "p820-t0", "일반기기": "p820-t0"}}
        rate["row_input_by_table"] = {"p819-t1": "thickness_boiler", "p820-t0": "thickness_duct"}
        rate["ignored_columns_by_table"] = {"p819-t1": ["계"], "p820-t0": ["계"]}
    else:
        rate["table_selector"] = {"input": "pump_type", "values": {
            "원심펌프(2단)": "p841-t0", "원심펌프(2단 대용량)": "p841-t1",
            "Rotary Pump, Centrifugal pump(3,4 stage)": "p842-t0"}}
        rate["row_input_by_table"] = {"p841-t0": "capacity_1", "p841-t1": "capacity_2",
                                       "p842-t0": "capacity_3"}
        rate["trades_by_table"] = {
            "p841-t0": ["목공", "플랜트기계\n설치공", "인력운반공", "특별인부"],
            "p841-t1": ["목공", "플랜트기계\n설치공", "특별인부", "비계공", "건설기계\n운전"],
            "p842-t0": ["목공", "플랜트기계\n설치공", "인력운반공", "특별인부"],
        }
        rate["ignored_columns_by_table"] = {table_id: ["계"]
                                               for table_id in ("p841-t0", "p841-t1", "p842-t0")}
    path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return spec


def compare_grid(document: fitz.Document, spec: dict) -> int:
    checked = 0
    definitions = [
        ("p819-t1", 819, 1, 2, ["용접공", "보온공", "함석공", "특별인부"]),
        ("p820-t0", 820, 0, 2, ["용접공", "보온공", "함석공", "특별인부"]),
        ("p841-t0", 841, 0, 1, ["목공", "플랜트기계\n설치공", "인력운반공", "특별인부"]),
        ("p841-t1", 841, 1, 1, ["목공", "플랜트기계\n설치공", "특별인부", "비계공", "건설기계\n운전"]),
        ("p842-t0", 842, 0, 1, ["목공", "플랜트기계\n설치공", "인력운반공", "특별인부"]),
    ]
    for table_id, page_no, index, data_row, trades in definitions:
        if table_id not in {t["id"] for t in spec["tables"]}:
            continue
        pdf_table = document[page_no - 1].find_tables().tables[index].extract()
        row_labels = pdf_table[data_row][0].splitlines()
        table = next(t for t in spec["tables"] if t["id"] == table_id)
        assert list(table["values"]) == row_labels, (table_id, list(table["values"]), row_labels)
        for col_index, trade in enumerate(trades, start=1):
            raw_values = pdf_table[data_row][col_index].splitlines()
            for row_i, row_label in enumerate(row_labels):
                actual = table["values"][row_label][trade]
                source = raw_values[row_i].strip()
                assert actual == source, (table_id, row_label, trade, actual, source)
                checked += 1
    return checked


def fields_for_132(spec: dict, equipment: str, thickness: str) -> dict:
    return {"equipment_type": equipment,
            "thickness_boiler": thickness if equipment == "Boiler 본체" else "60이하",
            "thickness_duct": "35이하" if equipment == "Boiler 본체" else thickness,
            "quantity": "1", "material_shape": "Blanket",
            "lagging_sheet_made_on_site": False, "lagging_sheet_used": True,
            "finishing_work_required": False, "insulation_layers": 1, "outdoor_boiler": False}


def check_routes(spec_132: dict, spec_13512: dict) -> tuple[int, int]:
    sys.path.insert(0, str(ROOT))
    from backend.agent.tools.calc.per_unit import per_unit

    routes = 0
    rate_paths = 0
    boiler = spec_132["tables"][0]["values"]
    duct = spec_132["tables"][1]["values"]
    for equipment, row_input, source, expected_factor in (
        ("Boiler 본체", "thickness_boiler", boiler, Fraction(1)),
        ("Duct", "thickness_duct", duct, Fraction(1)),
        ("일반기기", "thickness_duct", duct, Fraction(2)),
    ):
        table_id = "p819-t1" if equipment == "Boiler 본체" else "p820-t0"
        for row_value in source:
            inputs = fields_for_132(spec_132, equipment, row_value)
            result = per_unit(spec_132, inputs)
            assert result["status"] == "computed", (equipment, row_value, result)
            assert len(result["unit_lines"]) == 4, (equipment, row_value, result)
            for line in result["unit_lines"]:
                cite = line["citations"][0]
                assert cite["internal_id"] == table_id
                assert cite["row"] == row_value and cite["column"] == line["name"]
                assert cite["value"] == source[row_value][line["name"]]
                assert line["exact"] == str(Fraction(source[row_value][line["name"]]) * expected_factor)
                rate_paths += 1
            routes += 1

    tables = {t["id"]: t["values"] for t in spec_13512["tables"]}
    route_inputs = [
        ("원심펌프(2단)", "p841-t0", "capacity_1"),
        ("원심펌프(2단 대용량)", "p841-t1", "capacity_2"),
        ("Rotary Pump, Centrifugal pump(3,4 stage)", "p842-t0", "capacity_3"),
    ]
    for pump_type, table_id, row_input in route_inputs:
        for row_value, values in tables[table_id].items():
            inputs = {"pump_type": pump_type, "capacity_1": "50이하", "capacity_2": "1,001∼2,000",
                      "capacity_3": "50이하", "quantity": "1"}
            inputs[row_input] = row_value
            result = per_unit(spec_13512, inputs)
            assert result["status"] == "computed", (pump_type, row_value, result)
            expected_trades = spec_13512["quantity_model"]["params"]["unit_rate_table"]["trades_by_table"][table_id]
            assert len(result["unit_lines"]) == len(expected_trades)
            for line in result["unit_lines"]:
                cite = line["citations"][0]
                assert cite["internal_id"] == table_id and cite["row"] == row_value
                assert cite["column"] == line["name"] and cite["value"] == values[line["name"]]
                assert line["exact"] == str(Fraction(values[line["name"]]))
                rate_paths += 1
            routes += 1
    return routes, rate_paths


def main() -> None:
    spec_132 = update_route("13-3-2")
    spec_13512 = update_route("13-5-12")
    with fitz.open(PDF) as document:
        cells = compare_grid(document, spec_132) + compare_grid(document, spec_13512)
    routes, rate_paths = check_routes(spec_132, spec_13512)
    print(json.dumps({"status": "pass", "root_cause": "literal column label substituted for resource columns and selected table did not select its paired row input",
                      "sections": ["기계설비/13-3-2", "기계설비/13-5-12"],
                      "independent_pdf_cells_compared": cells, "exact_input_routes": routes,
                      "exact_calculated_rate_paths": rate_paths,
                      "all_capacity_combinations_exercised": True,
                      "policy_note": "13-3-2 lagging-sheet reduction remains a memo, not claimed as fully modeled",
                      "full_rule_verification": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
