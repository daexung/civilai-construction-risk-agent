"""Independent full-cell PDF audit and exact route/citation check for common 8-3-1."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/8-3-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
MANUAL_P287 = {
    "codes": ["0230-0002", "0230-0004", "0230-0006", "0230-0007", "0230-0008", "0230-0010"],
    "columns": [
        ["0.2", "0.4", "0.6", "0.7", "0.8", "1.0"], ["3,000"] * 6, ["890"] * 6,
        ["0.9"] * 6, ["0.85"] * 6, ["0.1"] * 6, ["3,000"] * 6,
        ["2,833"] * 6, ["768"] * 6, ["6,601"] * 6,
    ],
}
MANUAL_P285_T3 = {
    "codes": ["0103-0016", "0103-0019", "0103-0023", "0103-0027", "0103-0032"],
    "columns": [["16", "19", "23", "27", "32"], ["12,000"] * 5, ["795"] * 5],
}


def lines(cell: str | None) -> list[str]:
    return [value.strip() for value in (cell or "").splitlines() if value.strip()]


def expand_codes(values: list[str]) -> list[str]:
    if not values:
        return []
    prefix = values[0].split("-", 1)[0] + "-"
    return [values[0], *(value if "-" in value else prefix + value for value in values[1:])]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    tables = {table["id"]: table for table in spec["tables"]}
    category = next(field for field in spec["inputs"] if field["name"] == "machine_category")
    route = category["source_table_map"]
    assert len(route) == 19 and set(route.values()) == set(tables)
    pdf = pymupdf.open(PDF)
    audited_cells = 0
    table_report = {}
    for table_id, table in tables.items():
        page_num, table_num = map(int, re.fullmatch(r"p(\d+)-t(\d+)", table_id).groups())
        if table_id == "p287-t0":
            codes, columns = MANUAL_P287["codes"], MANUAL_P287["columns"]
            method = "rendered source page 231 crop; independently transcribed six code rows and ten columns"
        elif table_id == "p285-t3":
            codes, columns = MANUAL_P285_T3["codes"], MANUAL_P285_T3["columns"]
            method = "rendered source page 229 crop; independently transcribed five rows and three value columns"
        else:
            raw = pdf[page_num - 1].find_tables().tables[table_num].extract()
            source_row = raw[2]
            codes = expand_codes(lines(source_row[0]))
            columns = [lines(cell) for cell in source_row[1:]]
            method = "PDF table grid extraction; exact printed row/column order"
        draft_row_keys = list(table["values"])
        assert codes == expand_codes(draft_row_keys), (table_id, "row/code order", codes, draft_row_keys)
        assert len(columns) == len(next(iter(table["values"].values()))), (table_id, "column count", len(columns))
        for column_index, field in enumerate(next(iter(table["values"].values()))):
            actual = [row[field] for row in table["values"].values()]
            assert columns[column_index] == actual, (table_id, field, columns[column_index], actual)
        n = len(codes) * len(columns)
        audited_cells += n
        table_report[table_id] = {"rows": len(codes), "value_cells": n, "method": method}

    chunk_by_id = {
        chunk["chunk_id"]: chunk
        for chunk in load_chunks(ROOT / "data/processed/chunks.all.jsonl").values()
        if chunk.get("chunk_id") in {"p287-t0", "p289-t3"}
    }
    assert set(chunk_by_id) == {"p287-t0", "p289-t3"}
    for table_id, chunk in chunk_by_id.items():
        assert chunk.get("structure") == "ok" and not chunk.get("issues") and not chunk.get("uncertain_record_ids"), (table_id, chunk)

    citation_cells = 0
    for category_name, table_id in route.items():
        rows = tables[table_id]["values"]
        domain = lookup(spec, {"machine_category": category_name})
        assert domain["status"] == "ask", (category_name, domain)
        options = domain["questions"][0]["allowed_values"]
        expected_options = [next(iter(row.values())) for row in rows.values()]
        assert options == expected_options, (category_name, options, expected_options)
        for row_code, expected_row in rows.items():
            selected_spec = next(iter(expected_row.values()))
            result = lookup(spec, {"machine_category": category_name, "spec": selected_spec})
            assert result["status"] == "computed" and result["value"] == expected_row, (category_name, row_code)
            expected = {
                (table_id, row_code, field, value) for field, value in expected_row.items()
            }
            actual = {
                (citation["internal_id"], citation["row"], citation["column"], citation["value"])
                for line in result.get("unit_lines", [])
                for citation in line.get("citations", [])
            }
            assert actual == expected, (category_name, row_code, actual, expected)
            citation_cells += len(actual)

    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "tables": len(tables), "source_value_cells": audited_cells,
              "runtime_routes": len(route), "runtime_cell_citations": citation_cells,
              "citation_preflight": "pass", "table_audit": table_report}
    out = ROOT / "evals/runtime_validation/lookup-8-3-1-source-matrix-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
