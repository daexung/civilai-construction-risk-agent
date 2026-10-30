"""Verify 9010-0003 exact category/table and source-row routes against PDF."""
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

SPEC = ROOT / "data/drafts/specs/공통/9010-0003.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
TABLES = {
    "p327-t0": (327, 0, "비항SD", 1, "(9010) 펌프 준설선"),
    "p327-t1": (327, 1, "예선", 1, "(9030) 예 선"),
    "p328-t0": (328, 0, "양묘선", 2, "(9040) 양묘선"),
    "p328-t1": (328, 1, "기중기선", 1, "(9050) 기중기선"),
    "p329-t0": (329, 0, "토운선", 1, "(9060) 토운선"),
    "p329-t1": (329, 1, "이우선", 1, "(9070) 이우선"),
    "p330-t0": (330, 0, "대선", 1, "(9080) 대선"),
    "p330-t1": (330, 1, "하천골재채취선", 2, "(9090) 하천골재채취선"),
}
EXPECTED_MAP = {category: table_id for table_id, (_, _, category, _, _) in TABLES.items()}


def norm(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def lines(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines() if part.strip()]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    fields = {field["name"]: field for field in spec["inputs"]}
    assert fields["machine_category"]["source_table_map"] == EXPECTED_MAP
    assert fields["spec"]["type"] == "source_reference" and fields["spec"]["source_row_key"] is True
    pdf = pymupdf.open(PDF)
    drafts = {table["id"]: table for table in spec["tables"]}
    checked_rows = checked_cells = cases = 0
    for table_id, (printed_page, source_index, category, key_column, heading) in TABLES.items():
        table = drafts[table_id]
        page = pdf[printed_page - 1]
        page_text = page.get_text()
        if table_id == "p327-t0":
            page_text += pdf[325].get_text()
        assert heading.replace(" ", "") in page_text.replace(" ", ""), (table_id, heading)
        source_grid = page.find_tables().tables[source_index].extract()
        source_row = source_grid[2]
        source_keys = norm(source_row[key_column])
        cursor = 0
        for row_key in table["values"]:
            token = norm(row_key)
            position = source_keys.find(token, cursor)
            assert token and position >= 0, (table_id, row_key, source_row[key_column])
            cursor = position + len(token)
        count = len(table["values"])
        coefficient_columns = [lines(source_row[index]) for index in range(8, len(source_row))
                               if len(lines(source_row[index])) == count]
        assert coefficient_columns, (table_id, source_row)
        assert len(coefficient_columns) == len(next(iter(table["values"].values()))), (
            table_id, len(coefficient_columns), next(iter(table["values"].values()))
        )
        for row_index, (row_key, values) in enumerate(table["values"].items()):
            expected = [column[row_index] for column in coefficient_columns]
            assert [norm(value) for value in values.values()] == [norm(value) for value in expected], (
                table_id, row_key, values, expected)
            question = lookup(spec, {"machine_category": category})
            assert question.get("status") == "ask" and question["questions"][0]["name"] == "spec"
            assert question["questions"][0]["allowed_values"] == list(table["values"])
            result = lookup(spec, {"machine_category": category, "spec": row_key})
            assert result.get("status") == "computed" and result.get("row_reference"), (table_id, row_key, result)
            assert result["provenance"]["table"] == table_id and result["provenance"]["row"] == row_key
            assert result["value"] == values and len(result["provenance"]["citations"]) == len(values)
            checked_rows += 1
            checked_cells += len(values) + 1  # returned coefficients and the independent source key
            cases += 1

    first = lookup(spec, {})
    assert first.get("status") == "ask" and first["questions"][0]["name"] == "machine_category"
    assert first["questions"][0]["allowed_values"] == list(EXPECTED_MAP)
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "printed_pages": [327, 328, 329, 330],
                      "source_tables": len(TABLES), "source_rows": checked_rows,
                      "draft_value_cells": checked_cells - checked_rows,
                      "independently_compared_source_cells": checked_cells,
                      "exact_category_routes": len(TABLES), "exact_source_row_choices": cases,
                      "citation_preflight": "pass"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
