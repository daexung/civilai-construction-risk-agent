"""Independently audit reconstructed 8-3-3 rows against PDF p.292–295."""
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

SPEC = ROOT / "data/drafts/specs/공통/8-3-3.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
ROUTES = {
    "크레인(무한궤도)": ("p292-t2", 292, 2, "2101"),
    "크레인(타이어)": ("p293-t0", 293, 0, "2104"),
    "트럭탑재형 크레인": ("p293-t1", 293, 1, "2105"),
    "고소작업차": ("p294-t0", 294, 0, "2106"),
    "터널용고소작업차": ("p294-t1", 294, 1, "2107"),
    "리더(고정형)": ("p294-t2", 294, 2, "2115"),
    "리더(회전형)": ("p294-t3", 294, 3, "2116"),
    "케이싱": ("p294-t4", 294, 4, "2117"),
    "스킵버킷": ("p294-t5", 294, 5, "2118"),
    "타워크레인": ("p295-t0", 295, 0, "2208"),
}


def norm(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def lines(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines() if part.strip()]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    field = next(item for item in spec["inputs"] if item["name"] == "machine_type")
    assert field["source_table_map"] == {category: info[0] for category, info in ROUTES.items()}
    pdf = pymupdf.open(PDF)
    draft_tables = {table["id"]: table for table in spec["tables"]}
    rows_checked = value_cells = source_cells = route_count = 0
    for category, (table_id, printed_page, table_index, code_prefix) in ROUTES.items():
        page = pdf[printed_page - 1]
        page_text = norm(page.get_text())
        heading = category
        if category.startswith("리더("):
            heading = category.replace("리더(", "리더(LEADER; ")
        assert norm(heading) in page_text and norm(f"({code_prefix})") in page_text, (category, code_prefix)
        grid = page.find_tables().tables[table_index].extract()
        assert len(grid) == 3 and len(grid[2]) == 11, (table_id, grid)
        raw = grid[2]
        codes = lines(raw[0])
        row_keys = []
        for code in codes:
            code = norm(code)
            row_keys.append(code if "-" in code else code_prefix + "-" + code)
        expected_specs = []
        for token in lines(raw[1]):
            if token.startswith("("):
                assert expected_specs, (table_id, token)
                expected_specs[-1] += "\n" + token
            else:
                expected_specs.append(token)
        assert len(row_keys) == len(expected_specs), (table_id, row_keys, expected_specs)
        matrix = draft_tables[table_id]["values"]
        assert list(matrix) == row_keys, (table_id, list(matrix), row_keys)
        source_columns = [lines(raw[index]) for index in range(2, 11)]
        assert all(len(column) == len(row_keys) for column in source_columns), table_id
        for row_index, row_key in enumerate(row_keys):
            row = matrix[row_key]
            expected = [expected_specs[row_index], *(column[row_index] for column in source_columns)]
            assert len(row) == len(expected) == 10
            assert [norm(value) for value in row.values()] == [norm(value) for value in expected], (
                table_id, row_key, row, expected)
            rows_checked += 1
            value_cells += len(row)
            source_cells += len(row) + 1  # code cell plus every mapped source value cell
        result = lookup(spec, {"machine_type": category})
        assert result.get("status") == "computed" and result.get("table_reference"), (category, result)
        assert result["provenance"].get("table") == table_id and result["value"] == matrix
        citations = result["provenance"]["citations"]
        assert len(citations) == value_cells - sum(
            len(draft_tables[info[0]]["values"][key]) for previous, info in list(ROUTES.items())[:route_count]
            for key in draft_tables[info[0]]["values"])
        assert {citation["internal_id"] for citation in citations} == {table_id}
        route_count += 1
    first = lookup(spec, {})
    assert first.get("status") == "ask" and first["questions"][0]["name"] == "machine_type"
    assert first["questions"][0]["allowed_values"] == list(ROUTES)
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "printed_pages": [292, 293, 294, 295],
                      "source_tables": len(ROUTES), "source_rows": rows_checked,
                      "draft_value_cells": value_cells, "independently_compared_source_cells": source_cells,
                      "exact_category_routes": route_count, "returned_cell_citations": value_cells,
                      "citation_preflight": "pass"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
