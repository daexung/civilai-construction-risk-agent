"""Route Tainter/Roller Gate labor rates to their exact source tables."""
import json
import sys
from fractions import Fraction
from pathlib import Path

import fitz

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SPEC_PATH = ROOT / "data/drafts/specs/기계설비/13-6-3.json"


def repair():
    package = json.loads(SPEC_PATH.read_text(encoding="utf8"))
    draft = package["draft"]
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    rate["row_input"] = None
    rate["column_input"] = None
    rate["table_selector"] = {"input": "gate_type", "values": {
        "Tainter Gate": "p853-t0", "Roller Gate": "p854-t1"}}
    rate["trades_by_table"] = {
        "p853-t0": ["기계기사", "플랜트제관공", "플랜트용접공", "비계공", "플랜트기계설치공",
                    "도장공", "측량사", "특별인부", "검사및교정"],
        "p854-t1": ["기계기사", "플랜트제관공", "플랜트용접공", "비계공", "플랜트기계설치공",
                    "도장공", "측량사", "특별인부", "시험및조정"],
    }
    SPEC_PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return draft


def check_pdf(spec, document):
    checked = 0
    p853 = document[852].find_tables().tables[0].extract()
    names, rates = p853[1][0].splitlines(), p853[1][1].splitlines()
    tainter = next(t for t in spec["tables"] if t["id"] == "p853-t0")["values"]
    for name, raw in zip(names[:-1], rates[:-1]):
        canonical = name.replace(" ", "")
        assert tainter[canonical]["수량"] == raw.strip(), (canonical, raw)
        checked += 1
    assert tainter["계"]["수량"] == rates[-1].strip()
    checked += 1

    p854 = document[853].find_tables().tables[1].extract()
    roller = next(t for t in spec["tables"] if t["id"] == "p854-t1")["values"]
    for name_col, rate_col in ((0, 1), (2, 3)):
        names, rates = p854[1][name_col].splitlines(), p854[1][rate_col].splitlines()
        for name, raw in zip(names, rates):
            canonical = name.replace(" ", "")
            assert roller[canonical]["수량"] == raw.strip(), (canonical, raw)
            checked += 1
    return checked


def check_routes(spec):
    sys.path.insert(0, str(ROOT))
    from backend.agent.tools.calc.per_unit import per_unit
    tables = {table["id"]: table["values"] for table in spec["tables"]}
    routes = outputs = 0
    for gate_type, table_id in (("Tainter Gate", "p853-t0"), ("Roller Gate", "p854-t1")):
        result = per_unit(spec, {"gate_type": gate_type, "quantity": "12.5"})
        assert result["status"] == "computed", result
        expected_trades = spec["quantity_model"]["params"]["unit_rate_table"]["trades_by_table"][table_id]
        assert {line["name"] for line in result["unit_lines"]} == set(expected_trades)
        for line in result["unit_lines"]:
            cite = line["citations"][0]
            raw = tables[table_id][line["name"]]["수량"]
            assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (
                table_id, line["name"], "수량", raw)
            assert line["exact"] == str(Fraction(raw))
            outputs += 1
        routes += 1
    return routes, outputs


def main():
    spec = repair()
    with fitz.open(PDF) as document:
        cells = check_pdf(spec, document)
    routes, outputs = check_routes(spec)
    print(json.dumps({"status": "pass", "section": "기계설비/13-6-3",
                      "source_root": "literal row/column headers plus omitted gate-type table selector",
                      "independent_pdf_cells": cells, "exact_table_routes": routes,
                      "exact_rate_outputs": outputs, "full_rule_verification": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
