"""Independently audit 8-3-6 exact category routes and source matrix cells."""
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

SPEC = ROOT / "data/drafts/specs/공통/8-3-6.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
TABLES = {f"p{page}-t{index}": (page, index)
          for page, indexes in {302: range(3), 303: range(2), 304: range(2),
                                305: range(2), 306: range(2), 307: range(4)}.items()
          for index in indexes}
EXPECTED_MAP = {
    "크러셔(이동식)": "p302-t0", "벨트 컨베이어": "p302-t1",
    "에이프런 피더": ["p302-t2", "p303-t0"], "죠 크러셔": ["p303-t1", "p304-t0"],
    "롤 크러셔": "p304-t1", "콘 크러셔": "p305-t0", "스크린(2단식)": "p305-t1",
    "스크린(3단식)": "p306-t0", "아그리게이트빈": ["p306-t1", "p307-t0"],
    "골재세척설비": "p307-t1", "파이프추진기(오거부착유압식)": "p307-t2",
    "파이프추진기(공압식)": "p307-t3",
}


def norm(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def lines(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines() if part.strip()]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    field = next(item for item in spec["inputs"] if item["name"] == "machine_category")
    assert field["source_table_map"] == EXPECTED_MAP
    pdf = pymupdf.open(PDF)
    draft_tables = {table["id"]: table for table in spec["tables"]}
    rows_checked = draft_cells = source_cells = 0
    for table_id, (printed_page, table_index) in TABLES.items():
        table = draft_tables[table_id]
        page = pdf[printed_page - 1]
        grid = page.find_tables().tables[table_index].extract()
        assert len(grid) >= 3 and grid[2], (table_id, grid)
        raw_cells = grid[2]
        raw_codes = lines(raw_cells[0])
        assert len(raw_codes) == len(table["values"]), (table_id, raw_codes, list(table["values"]))
        prefix = next((code.split("-")[0] + "-" for code in raw_codes if "-" in code), None)
        expanded_codes = [code if "-" in code or prefix is None else prefix + code for code in raw_codes]
        draft_rows = list(table["values"].items())
        assert len(raw_cells) == 1 + len(draft_rows[0][1]), (table_id, len(raw_cells), draft_rows[0])
        for row_index, (draft_key, draft_values) in enumerate(draft_rows):
            source_code = expanded_codes[row_index]
            assert norm(draft_key) == norm(source_code) or norm(source_code).endswith(norm(draft_key)), (
                table_id, draft_key, source_code)
        # Compare every scalar PDF column row-by-row. Multi-line specifications
        # can wrap within a single PDF cell, so compare those as ordered literal
        # source substrings after whitespace normalization.
        for col_index in range(1, len(raw_cells)):
            raw = raw_cells[col_index]
            source_lines = lines(raw)
            draft_column = [list(values.values())[col_index - 1] for _, values in draft_rows]
            if len(source_lines) == len(draft_rows):
                assert [norm(value) for value in draft_column] == [norm(value) for value in source_lines], (
                    table_id, col_index, draft_column, source_lines)
            else:
                source_compact = norm(raw)
                cursor = 0
                for expected in draft_column:
                    token = norm(expected)
                    position = source_compact.find(token, cursor)
                    assert token and position >= 0, (table_id, col_index, expected, raw)
                    cursor = position + len(token)
            draft_cells += len(draft_rows)
            source_cells += len(draft_rows)
        rows_checked += len(draft_rows)
        source_cells += len(raw_codes)  # table record-code cells

    routes = 0
    for category, mapped in EXPECTED_MAP.items():
        table_ids = mapped if isinstance(mapped, list) else [mapped]
        result = lookup(spec, {"machine_category": category})
        assert result.get("status") == "computed" and result.get("table_reference"), (category, result)
        actual_ids = result["provenance"].get("tables", [result["provenance"].get("table")])
        assert actual_ids == table_ids, (category, actual_ids, table_ids)
        expected = ({table_id: draft_tables[table_id]["values"] for table_id in table_ids}
                    if len(table_ids) > 1 else draft_tables[table_ids[0]]["values"])
        assert result["value"] == expected, category
        expected_citations = sum(sum(len(cells) for cells in draft_tables[table_id]["values"].values())
                                 for table_id in table_ids)
        assert len(result["provenance"]["citations"]) == expected_citations
        routes += 1

    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "printed_pages": [302, 303, 304, 305, 306, 307],
                      "source_tables": len(TABLES), "source_rows": rows_checked,
                      "draft_value_cells": draft_cells, "independently_compared_source_cells": source_cells,
                      "exact_category_routes": routes, "multi_table_categories": 3,
                      "citations": "all returned cells cite their exact source table", "citation_preflight": "pass"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
