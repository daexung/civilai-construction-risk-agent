"""Original p.891 source-cell and calculator-route audit for mechanical 13-8-1."""
import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402

SPEC = json.loads((ROOT / "data/drafts/specs/기계설비/13-8-1.json").read_text(encoding="utf-8"))["draft"]
SOURCE = {
    "기술관리": ("기계기사", "1.45", "일"),
    "포장해체": ("목공:0.07;특별인부:0.33", None, "㎥"),
    "표면손질": ("특별인부", "0.15", "㎡"),
    "급진기설치": ("플랜트기계설치공:4.45;비계공:3.35;특별인부:3.73;플랜트제관공:4.75;플랜트용접공:2.96", None, "ton"),
    "소각로모듈설치": ("플랜트기계설치공:3.61;비계공:3.05;플랜트제관공:4.70;특별인부:3.12;플랜트용접공:2.38", None, "ton"),
    "화격자설치": ("플랜트기계설치공:4.81;플랜트제관공:2.16;플랜트용접공:1.16;비계공:3.10;특별인부:2.39", None, "ton"),
    "내화물": ("제철축조공:2.67;목공:0.32;비계공:0.17;특별인부:1.71;보통인부:2.56", None, "ton"),
    "재축출기설치": ("플랜트기계설치공:5.47;비계공:4.36;플랜트제관공:3.44;특별인부:3.37", None, "ton"),
    "원치설치및철거": ("기계설비공:3.30;비계공:11.00;용접공:3.30;특별인부:4.95", None, "대"),
}


def expected_map(encoded):
    if ":" not in encoded:
        return {encoded: SOURCE_CURRENT_RATE}
    return {part.split(":", 1)[0]: part.split(":", 1)[1]
            for part in encoded.split(";")}


def main():
    tables = {table["id"]: table for table in SPEC["tables"]}
    checked_cells = checked_routes = 0
    results = {}
    rate = SPEC["quantity_model"]["params"]["unit_rate_table"]
    for process, (encoded, single_value, unit) in SOURCE.items():
        table_id = rate["table_selector"]["values"][process]
        row = rate["row_value_map"][process]
        source_cells = tables[table_id]["values"][row]
        want = ({encoded: single_value} if single_value is not None else expected_map(encoded))
        assert source_cells == want, (process, source_cells, want)
        result = per_unit(SPEC, {"process": process, "quantity": "2"}, labor_only=True)
        assert result.get("status") == "computed", (process, result)
        got = {line["name"]: line["exact"] for line in result["unit_lines"]}
        assert {name: Fraction(value) for name, value in got.items()} == {
            name: Fraction(value) for name, value in want.items()}, (process, got, want)
        assert all(line["unit"] == f"인/{unit}" for line in result["unit_lines"]), (process, result["unit_lines"])
        assert all(any(cite.get("internal_id") == table_id and cite.get("row") == row
                       for cite in line.get("citations", []) if isinstance(cite, dict))
                   for line in result["unit_lines"]), (process, result["unit_lines"])
        checked_cells += len(want)
        checked_routes += 1
        results[process] = {"table": table_id, "source_row": row, "unit": unit,
                            "rates": got, "status": result["status"]}

    # The printed source expresses inspection/calibration as 10% of other work,
    # not as a numerical unit-rate cell. Fail closed until its labor-scope rule
    # has an independent source-backed implementation.
    unresolved = per_unit(SPEC, {"process": "검사및교정", "quantity": "2"}, labor_only=True)
    assert unresolved.get("status") in ("unresolvable", "blocked"), unresolved
    report = {"status": "passed", "source_pdf_page": 891, "printed_page": 835,
              "source_cells": checked_cells, "exact_process_routes": checked_routes,
              "inspection_rule": unresolved.get("reason", unresolved.get("status")),
              "inspection_rule_verified": False, "routes": results}
    output = ROOT / "evals/runtime_validation/13-8-1-exact-process-source-audit-2026-10-19.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
