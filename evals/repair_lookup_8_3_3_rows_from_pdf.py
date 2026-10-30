"""Restore 8-3-3 equipment table rows using printed PDF cell grids."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/공통/8-3-3.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
ROUTES = {
    "크레인(무한궤도)": "p292-t2", "크레인(타이어)": "p293-t0",
    "트럭탑재형 크레인": "p293-t1", "고소작업차": "p294-t0",
    "터널용고소작업차": "p294-t1", "리더(고정형)": "p294-t2",
    "리더(회전형)": "p294-t3", "케이싱": "p294-t4",
    "스킵버킷": "p294-t5", "타워크레인": "p295-t0",
}


def lines(value: object) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines() if part.strip()]


def grouped_specs(value: object, expected: int) -> list[str]:
    groups = []
    for token in lines(value):
        if token.startswith("(") and groups:
            groups[-1] += "\n" + token
        else:
            groups.append(token)
    if len(groups) != expected:
        raise ValueError(f"규격 셀을 행별로 분리할 수 없음: rows={expected}, groups={len(groups)}")
    return groups


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    field = next(item for item in spec["inputs"] if item["name"] == "machine_type")
    if set(field["allowed_values"]) != set(ROUTES):
        raise AssertionError((field["allowed_values"], ROUTES))
    tables = {table["id"]: table for table in spec["tables"]}
    pdf = pymupdf.open(PDF)
    total_rows = total_cells = 0
    for table_id, table in tables.items():
        match = re.fullmatch(r"p(\d+)-t(\d+)", table_id)
        if not match:
            raise ValueError(table_id)
        page_no, table_index = map(int, match.groups())
        source_tables = pdf[page_no - 1].find_tables().tables
        grid = source_tables[table_index].extract()
        if len(grid) < 3 or len(grid[2]) != 11:
            raise ValueError(f"원문 표 열 구조 불일치 {table_id}")
        source_row = grid[2]
        source_codes = lines(source_row[0])
        prefix = next((code.split("-")[0] + "-" for code in source_codes if "-" in code), None)
        row_keys = [code if "-" in code or prefix is None else prefix + code for code in source_codes]
        specs = grouped_specs(source_row[1], len(row_keys))
        numeric = [lines(source_row[index]) for index in range(2, 11)]
        if any(len(column) != len(row_keys) for column in numeric):
            raise ValueError(f"행별 원문 값 수 불일치 {table_id}: {[len(c) for c in numeric]}")
        columns = list(next(iter(table["values"].values())))
        if len(columns) != 10:
            raise ValueError(f"초안 열 수 불일치 {table_id}: {columns}")
        rows = {}
        for index, row_key in enumerate(row_keys):
            cells = {columns[0]: specs[index]}
            cells.update({column: numeric[source_index][index]
                          for source_index, column in enumerate(columns[1:])})
            rows[row_key] = cells
        table["values"] = rows
        total_rows += len(rows)
        total_cells += sum(len(row) for row in rows.values())
    field["source_table_map"] = ROUTES
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"updated_tables": len(tables), "restored_source_rows": total_rows,
                      "draft_value_cells": total_cells, "exact_category_routes": len(ROUTES),
                      "spec_cell_line_wrapping_preserved": True}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
