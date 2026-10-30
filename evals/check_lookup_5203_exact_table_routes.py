"""Check the exact 5203 machine-category-to-source-table routes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/5203-1800.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
PAGE_BY_TABLE = {
    "p308-t0": 307, "p308-t1": 307, "p308-t2": 307, "p308-t3": 307,
    "p309-t0": 308, "p309-t1": 308, "p309-t2": 308, "p309-t3": 308, "p309-t4": 308,
    "p310-t0": 309, "p310-t1": 309, "p310-t2": 309, "p310-t3": 309, "p310-t4": 309,
}


def key(text: str) -> str:
    return "".join(text.split())


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    field = spec["inputs"][0]
    table_map = field["source_table_map"]
    assert set(table_map) == set(field["allowed_values"])
    tables = {table["id"]: table for table in spec["tables"]}
    document = pymupdf.open(PDF)
    route_details = []
    citations_total = 0
    for category, selected in table_map.items():
        table_ids = selected if isinstance(selected, list) else [selected]
        assert all(table_id in PAGE_BY_TABLE and table_id in tables for table_id in table_ids), (category, selected)
        for table_id in table_ids:
            source_page = document[PAGE_BY_TABLE[table_id]]
            assert key(category) in key(source_page.get_text()), (category, table_id, PAGE_BY_TABLE[table_id])
        result = lookup(spec, {"machine_category": category})
        assert result["status"] == "computed" and result.get("table_reference")
        expected_values = {table_id: tables[table_id]["values"] for table_id in table_ids}
        if len(table_ids) == 1:
            assert result["provenance"]["table"] == table_ids[0]
            assert result["value"] == expected_values[table_ids[0]]
        else:
            assert result["provenance"]["tables"] == table_ids
            assert result["value"] == expected_values
        cells = sum(sum(len(row) for row in tables[table_id]["values"].values()) for table_id in table_ids)
        citations = result["provenance"]["citations"]
        assert len(citations) == cells and all(c["internal_id"] in table_ids for c in citations)
        assert {citation["internal_id"] for citation in citations} == set(table_ids)
        citations_total += cells
        route_details.append({"category": category, "table_ids": table_ids,
                              "source_pages": [PAGE_BY_TABLE[table_id] + 1 for table_id in table_ids],
                              "rows_returned": {table_id: len(tables[table_id]["values"]) for table_id in table_ids},
                              "cell_citations": cells})
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "exact_heading_routes": len(route_details),
                      "runtime_cell_citations": citations_total,
                      "source_heading_binding": "pass", "citation_preflight": "pass",
                      "routes": route_details,
                      "source_accuracy": "heading-to-table links checked; table value cells remain a separate audit"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
