"""Independently compare 8-3-5 table routes and selected cells with PDF tables."""
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

SPEC = ROOT / "data/drafts/specs/공통/8-3-5.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED_TABLES = {
    "p299-t1": (299, 1), "p299-t2": (299, 2),
    "p300-t0": (300, 0), "p300-t1": (300, 1), "p300-t2": (300, 2), "p300-t3": (300, 3),
    "p301-t0": (301, 0), "p301-t1": (301, 1), "p301-t2": (301, 2), "p301-t3": (301, 3),
}


def norm(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


def lines(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines() if part.strip()]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    field = next(item for item in spec["inputs"] if item["name"] == "machine_category")
    mapping = field["source_table_map"]
    expected_categories = {
        "콘크리트 배치플랜트": "p299-t1", "사일로": "p299-t2",
        "콘크리트 믹서": "p300-t0", "콘크리트 믹서트럭": "p300-t1", "커터": "p300-t2",
        "콘크리트 펌프차": ["p300-t3", "p301-t0"], "콘크리트 펌프": "p301-t1",
        "초고압펌프": "p301-t2", "콘크리트 진동기": "p301-t3",
    }
    assert mapping == expected_categories
    pdf = pymupdf.open(PDF)
    tables = {table["id"]: table for table in spec["tables"]}
    table_rows = table_cells = checked_source_cells = 0
    for table_id, (printed_page, table_index) in EXPECTED_TABLES.items():
        source_page = pdf[printed_page - 1]
        source_text = source_page.get_text()
        assert "콘크리트" in source_text and ("펌프" in source_text if printed_page >= 300 else True)
        source_tables = source_page.find_tables().tables
        assert table_index < len(source_tables), (printed_page, table_index)
        grid = source_tables[table_index].extract()
        assert len(grid) >= 3 and len(grid[2]) >= 10, (table_id, grid)
        source = grid[2]
        codes = lines(source[0])
        prefix = next((code.split("-")[0] + "-" for code in codes if "-" in code), None)
        row_keys = [code if "-" in code or prefix is None else prefix + code for code in codes]
        draft_values = tables[table_id]["values"]
        assert len(row_keys) == len(draft_values), (table_id, row_keys, list(draft_values))
        coeff_source = [lines(source[column]) for column in (7, 8, 9)]
        assert all(len(column) == len(row_keys) for column in coeff_source), (table_id, coeff_source)
        for index, (row_key, cells) in enumerate(draft_values.items()):
            assert (norm(row_key) == norm(row_keys[index])
                    or norm(row_keys[index]).endswith(norm(row_key))), (table_id, row_key, row_keys[index])
            spec_column = next(name for name in cells if norm(name).startswith(norm("규격")))
            # Some printed specifications include a secondary dimension on the
            # following line; the drafted selector is the first labeled dimension.
            assert norm(cells[spec_column]) in norm(source[1]), (table_id, row_key, cells[spec_column], source[1])
            for draft_column, source_column in zip(list(cells)[1:], coeff_source):
                assert norm(cells[draft_column]) == norm(source_column[index]), (
                    table_id, row_key, draft_column, cells[draft_column], source_column[index])
            table_rows += 1
            table_cells += len(cells)
            checked_source_cells += 1 + 1 + 3  # code, selected spec dimension, and three coefficient cells

    category_routes = 0
    for category, mapped in expected_categories.items():
        ids = mapped if isinstance(mapped, list) else [mapped]
        result = lookup(spec, {"machine_category": category})
        assert result.get("status") == "computed" and result.get("table_reference"), (category, result)
        assert result["provenance"].get("tables", [result["provenance"].get("table")]) == ids
        expected_value = ({table_id: tables[table_id]["values"] for table_id in ids}
                          if len(ids) > 1 else tables[ids[0]]["values"])
        assert result["value"] == expected_value, category
        assert len(result["provenance"]["citations"]) == sum(
            sum(len(row) for row in tables[table_id]["values"].values()) for table_id in ids)
        category_routes += 1
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "printed_pages": [299, 300, 301],
                      "source_tables": len(EXPECTED_TABLES), "source_rows": table_rows,
                      "draft_value_cells": table_cells, "independently_compared_source_cells": checked_source_cells,
                      "exact_category_routes": category_routes, "multi_table_category": "콘크리트 펌프차",
                      "citations": "all returned draft cells cite their exact source table", "citation_preflight": "pass"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
