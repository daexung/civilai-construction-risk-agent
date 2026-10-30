"""Independent cell, route, citation and preflight audit for 5203-1800."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from evals.repair_lookup_5203_from_pdf import (  # noqa: E402
    PDF_PATH, SPEC_PATH, TABLE_LOCATIONS, equipment_matrix,
)
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402


def main() -> int:
    package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = package["draft"]
    tables = {table["id"]: table for table in spec["tables"]}
    with pymupdf.open(PDF_PATH) as document:
        source = {table_id: equipment_matrix(document, table_id) for table_id in TABLE_LOCATIONS}

    checked_cells = 0
    for table_id, expected in source.items():
        actual = tables[table_id]["values"]
        assert actual == expected["values"], (table_id, "PDF cells differ")
        checked_cells += sum(len(row) for row in actual.values())
    assert checked_cells == 360, checked_cells

    # Direct visual transcription on printed p.253 supplements two cells the
    # PDF table extractor drops from the 5220-0015 line.
    assert tables["p309-t0"]["values"] == {
        "5220-0015": {"규 격": "1.5㎾", "내용시간": "8,000", "시 간 당(10-7)": "2,500"}
    }

    compressor = tables["p308-t3"]["values"]
    expected_accessories = {
        "3.5": ["1", "-", "-", "3", "2", "1", "1", "3", "3", "3", "3"],
        "7.1": ["2(1)", "-", "-", "7", "5", "3", "2", "7", "7", "7", "7"],
        "10.3": ["3(2)", "1", "-", "13", "8", "5", "3", "10", "10", "10", "10"],
        "17.0": ["5(4)", "2", "1", "17", "13", "9", "6", "17", "17", "17", "17"],
        "25.5": ["9(8)", "3", "1", "25", "19", "13", "9", "25", "25", "25", "25"],
    }
    for row, values in expected_accessories.items():
        assert list(compressor[row].values()) == values, (row, compressor[row])

    field = next(item for item in spec["inputs"] if item["name"] == "machine_category")
    routes = field["source_table_map"]
    assert routes["공기압축기(이동식)"] == ["p308-t1", "p308-t3"]
    citation_count = 0
    for category, selected in routes.items():
        expected_ids = selected if isinstance(selected, list) else [selected]
        result = lookup(spec, {"machine_category": category})
        assert result["status"] == "computed" and result.get("table_reference"), (category, result)
        received = result["value"] if len(expected_ids) == 1 else result["value"]
        expected_map = {table_id: tables[table_id]["values"] for table_id in expected_ids}
        if len(expected_ids) == 1:
            assert received == expected_map[expected_ids[0]], category
        else:
            assert received == expected_map, (category, received.keys(), expected_map.keys())
        citations = result["provenance"]["citations"]
        expected_citation_tuples = {
            (table_id, row, column, value)
            for table_id in expected_ids
            for row, columns in expected_map[table_id].items()
            for column, value in columns.items()
        }
        actual_citation_tuples = {
            (item["internal_id"], item["row"], item["column"], item["value"])
            for item in citations
        }
        assert actual_citation_tuples == expected_citation_tuples, category
        citation_count += len(citations)

    validation = validate_one(SPEC_PATH, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "source_tables": len(source),
                      "source_value_cells": checked_cells, "exact_category_routes": len(routes),
                      "runtime_cell_citations": citation_count, "p309-t0_rendered_cells": 2,
                      "p308-t3_accessory_matrix_cells": 55, "citation_preflight": "pass"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
