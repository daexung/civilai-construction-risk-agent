"""Verify 8-3-10 category-dependent exact row choices against PDF p.326."""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/8-3-10.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"


def norm(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def lines(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines() if part.strip()]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    selector = next(field for field in spec["inputs"] if field["name"] == "equipment_type")
    assert selector["source_table_map"] == {"펌프 준설선": "p326-t1", "그래브 준설선": "p326-t2"}
    pdf = pymupdf.open(PDF)
    page = pdf[325]
    page_text = page.get_text()
    assert "(9010) 펌프 준설선" in page_text and "(9020) 그래브 준설선" in page_text
    source_tables = page.find_tables().tables
    drafts = {table["id"]: table for table in spec["tables"]}
    expected = [("펌프 준설선", "pump_spec", "p326-t1", 1, 2),
                ("그래브 준설선", "grab_spec", "p326-t2", 2, 1)]
    cells_checked = rows_checked = cases = 0
    for category, selector_field, table_id, source_index, spec_column in expected:
        table = drafts[table_id]
        grid = source_tables[source_index].extract()
        raw = grid[2]
        source_specs = lines(raw[spec_column])
        if category == "그래브 준설선":
            source_specs = [value for value in source_specs if norm(value) != norm("비항SD")]
        draft_rows = list(table["values"].items())
        assert len(source_specs) == len(draft_rows), (table_id, source_specs, list(table["values"]))
        for (row_key, values), source_spec in zip(draft_rows, source_specs):
            assert norm(row_key) == norm(source_spec), (table_id, row_key, source_spec)
        coefficient_columns = [lines(raw[index]) for index in (8, 9, 10)]
        assert all(len(column) == len(draft_rows) for column in coefficient_columns), table_id
        for index, (row_key, values) in enumerate(draft_rows):
            assert [norm(value) for value in values.values()] == [norm(column[index]) for column in coefficient_columns], (
                table_id, row_key, values)
            result = lookup(spec, {"equipment_type": category, selector_field: row_key})
            assert result.get("status") == "computed" and result.get("row_reference"), (category, row_key, result)
            assert result["provenance"]["table"] == table_id and result["provenance"]["row"] == row_key
            assert result["value"] == values and len(result["provenance"]["citations"]) == len(values)
            rows_checked += 1
            cells_checked += len(values)
            cases += 1
        # Check the exact output/spec labels as well as every returned coefficient.
        if category == "펌프 준설선":
            code_count = len(lines(raw[0]))
            output_count = len(lines(raw[2]))
            assert code_count == output_count == len(draft_rows)
            cells_checked += code_count + output_count
        else:
            code_lines = lines(raw[0])
            code_lines = [value for value in code_lines if value != "9020-"]
            assert len(code_lines) == len(draft_rows)
            output_count = len(lines(raw[2]))
            assert output_count == len(draft_rows)
            cells_checked += len(code_lines) + output_count

    first = lookup(spec, {})
    assert first.get("status") == "ask" and first["questions"][0]["name"] == "equipment_type"
    pump_question = lookup(spec, {"equipment_type": "펌프 준설선"})
    assert pump_question.get("status") == "ask" and pump_question["questions"][0]["name"] == "pump_spec"
    assert pump_question["questions"][0]["allowed_values"] == list(drafts["p326-t1"]["values"])
    grab_question = lookup(spec, {"equipment_type": "그래브 준설선"})
    assert grab_question.get("status") == "ask" and grab_question["questions"][0]["name"] == "grab_spec"
    assert grab_question["questions"][0]["allowed_values"] == list(drafts["p326-t2"]["values"])
    assert lookup(spec, {"equipment_type": "펌프 준설선", "grab_spec": "1.00"})["status"] == "rejected"
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "printed_page": 270, "source_tables": 2,
                      "source_rows": rows_checked, "draft_value_cells": cells_checked - 2 * rows_checked,
                      "independent_source_cells": cells_checked, "exact_selector_routes": 2,
                      "dependent_row_choices": 2, "lookup_cases": cases,
                      "inapplicable_branch_rejected": True, "citation_preflight": "pass"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
