"""Restore the source continuation rows for the GANTRY CRANE labor table."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SPEC_PATH = ROOT / "data/drafts/specs/기계설비/13-10-3.json"
BASE_TRADES = ["기계산업기사", "비계공", "플랜트기계설치공", "특별인부", "제관공"]
CONTINUED_TRADES = ["용접공", "측량사", "도장공", "시험및조정"]


def repair() -> dict:
    package = json.loads(SPEC_PATH.read_text(encoding="utf8"))
    spec = package["draft"]
    params = spec["quantity_model"]["params"]
    rate = params["unit_rate_table"]
    rate["row_input"] = None
    rate["column_input"] = None
    rate["trades"] = BASE_TRADES
    params["additional_unit_rates"] = [{
        "table": "p904-t0", "basis": "인/ton", "quantity_input": "quantity",
        "row_template": "{trade}", "column": "수량", "trades": CONTINUED_TRADES,
    }]
    SPEC_PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return spec


def check_pdf_tables(spec: dict, document: fitz.Document) -> int:
    source_values = {}
    base_grid = document[902].find_tables().tables[2].extract()
    base_names, base_rates = base_grid[1][0].splitlines(), base_grid[1][1].splitlines()
    assert [name.replace(" ", "") for name in base_names] == [name.replace(" ", "") for name in BASE_TRADES]
    base_table = next(table for table in spec["tables"] if table["id"] == "p903-t2")
    for trade, raw in zip(BASE_TRADES, base_rates):
        value = raw.strip()
        assert base_table["values"][trade]["수량"] == value
        source_values[trade] = ("p903-t2", trade, "수량", value)

    continuation_grid = document[903].find_tables().tables[0].extract()
    continuation_names = continuation_grid[1][0].splitlines()
    continuation_rates = continuation_grid[1][1].splitlines()
    continuation_table = next(table for table in spec["tables"] if table["id"] == "p904-t0")
    for trade, raw in zip(CONTINUED_TRADES, continuation_rates):
        value = raw.strip()
        assert continuation_table["values"][trade]["수량"] == value
        source_values[trade] = ("p904-t0", trade, "수량", value)
    assert [name.replace(" ", "") for name in continuation_names] == [name.replace(" ", "") for name in CONTINUED_TRADES]
    assert continuation_table["values"]["계"]["수량"] == continuation_grid[2][1]
    return len(source_values)


def check_routes(spec: dict) -> tuple[int, int]:
    sys.path.insert(0, str(ROOT))
    from backend.agent.tools.calc.per_unit import per_unit

    source = {}
    for table_id in ("p903-t2", "p904-t0"):
        table = next(table for table in spec["tables"] if table["id"] == table_id)
        for trade, row in table["values"].items():
            if trade == "계":
                continue
            source[trade] = (table_id, row["수량"])
    routes = paths = 0
    for quantity in ("1", "2", "17.5"):
        result = per_unit(spec, {"quantity": quantity})
        assert result["status"] == "computed", result
        assert {line["name"] for line in result["unit_lines"]} == set(source)
        for line in result["unit_lines"]:
            table_id, raw = source[line["name"]]
            cite = line["citations"][0]
            assert cite["internal_id"] == table_id
            assert cite["row"] == line["name"] and cite["column"] == "수량" and cite["value"] == raw
            assert line["exact"] == str(Fraction(raw)), (line, raw)
            paths += 1
        routes += 1
    return routes, paths


def main() -> None:
    spec = repair()
    with fitz.open(PDF) as document:
        cells = check_pdf_tables(spec, document)
    routes, paths = check_routes(spec)
    print(json.dumps({"status": "pass", "root_cause": "literal header selectors and page continuation rows omitted from the active rate route",
                      "section": "기계설비/13-10-3", "independent_pdf_cells_compared": cells,
                      "exact_input_routes": routes, "exact_rate_paths": paths,
                      "continuation_pages": [903, 904], "full_rule_verification": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
