"""Restore 5203-1800 lookup matrices from the exact printed PDF tables."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "data/drafts/specs/공통/5203-1800.json"
CHUNKS_PATH = ROOT / "data/processed/chunks.all.jsonl"
PDF_PATH = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
TABLE_LOCATIONS = {
    "p308-t0": (308, 0), "p308-t1": (308, 1), "p308-t2": (308, 2), "p308-t3": (308, 3),
    "p309-t0": (309, 0), "p309-t1": (309, 1), "p309-t2": (309, 2),
    "p309-t3": (309, 3), "p309-t4": (309, 4),
    "p310-t0": (310, 0), "p310-t1": (310, 1), "p310-t2": (310, 2),
    "p310-t3": (310, 3), "p310-t4": (310, 4),
}
CATEGORY_ACCESSORY_MATRIX = "공기압축기(이동식)"


def nonempty_lines(value: object) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def expand_codes(value: object) -> list[str]:
    lines = nonempty_lines(value)
    if not lines:
        return []
    match = re.fullmatch(r"(\d{4}-)(\d{4})", lines[0])
    if match:
        prefix = match.group(1)
        return [lines[0], *(prefix + line for line in lines[1:])]
    return lines


def header_keys(grid: list[list[str | None]]) -> list[str]:
    first = grid[0]
    second = grid[1]
    keys = []
    inherited_group = None
    for col, label in enumerate(first):
        if label:
            inherited_group = label
        sub = second[col] if col < len(second) else None
        parts = [inherited_group if col >= 7 else label, sub]
        lines = []
        for part in parts:
            lines.extend(nonempty_lines(part))
        key = "\n".join(lines)
        keys.append(key)
    return keys


def split_source_column(raw: object, row_count: int, table_id: str, column: int) -> list[str]:
    values = nonempty_lines(raw)
    if len(values) == row_count:
        return values
    # Source cells in the 5401 table put a parenthesized drill diameter on a
    # second visual line under each capacity. Preserve that printed pairing.
    if len(values) == row_count * 2 and all(values[i * 2 + 1].startswith("(")
                                          for i in range(row_count)):
        return [f"{values[i * 2]} {values[i * 2 + 1]}" for i in range(row_count)]
    raise AssertionError((table_id, column, row_count, values))


def equipment_matrix(document, table_id: str) -> dict:
    printed_page, table_index = TABLE_LOCATIONS[table_id]
    source_grid = document[printed_page - 1].find_tables().tables[table_index].extract()
    headers = header_keys(source_grid)
    codes = expand_codes(source_grid[-1][0])
    if table_id == "p309-t0":
        # The original PDF table detector drops the ruled first-column code and
        # last-column coefficient. Both are legible in the source page image.
        codes = ["5220-0015"]
        values = {
            codes[0]: {"규 격": "1.5㎾", "내용시간": "8,000", "시 간 당(10-7)": "2,500"}
        }
        return {"values": values, "pdf_table": source_grid, "source_cells": 3,
                "manual_cells_from_rendered_original": {"분류번호": "5220-0015", "시 간 당(10-7)": "2,500"}}
    if table_id == "p308-t3":
        # Exact group/spec/hose labels read from the rendered printed matrix;
        # row values come from the PDF's extracted cell text and are checked
        # against the rendered page in the paired source checker.
        data_row = source_grid[-1]
        capacity = nonempty_lines(data_row[0])
        assert len(capacity) == 5, (table_id, capacity)
        group = ["", "", "",
                 "래그\n해머", "드릴\n웨곤", "드릴\n무한궤도",
                 "소형브레이커", "소형브레이커", "소형브레이커", "소형브레이커",
                 "바이브레이터", "바이브레이터", "바이브레이터", "바이브레이터"]
        spec = ["", "", "",
                "2.7\n㎥/min", "(100㎜)\n74\n〃", "(120㎜)\n15\n〃",
                "1.0\n㎥/min", "1.3\n㎥/min", "1.9\n㎥/min", "2.7\n㎥/min",
                "25\n㎜", "37\n㎜", "45\n㎜", "60\n㎜"]
        hose = ["", "", "",
                "19", "38", "50", "19", "19", "19", "19", "", "", "", ""]
        col_keys = []
        for c in range(3, 14):
            descriptor = "\n".join(x for x in (group[c], spec[c]) if x)
            if hose[c]:
                descriptor += f"\n사용에어호스경(㎜) {hose[c]}"
            col_keys.append(descriptor)
        columns = [split_source_column(data_row[c], len(capacity), table_id, c) for c in range(3, 14)]
        values = {row: {col_keys[c]: columns[c][r] for c in range(len(col_keys))}
                  for r, row in enumerate(capacity)}
        return {"values": values, "pdf_table": source_grid,
                "source_cells": sum(map(len, values.values())),
                "manual_headers_from_rendered_original": col_keys}

    if not codes:
        raise AssertionError((table_id, "missing source row codes"))
    if len(headers) != len(source_grid[-1]):
        raise AssertionError((table_id, "header width", headers, len(source_grid[-1])))
    values = {}
    for col in range(1, len(headers)):
        if not headers[col]:
            raise AssertionError((table_id, "empty source header", col, source_grid[0], source_grid[1]))
        column_values = split_source_column(source_grid[-1][col], len(codes), table_id, col)
        for row_index, code in enumerate(codes):
            values.setdefault(code, {})[headers[col]] = column_values[row_index]
    return {"values": values, "pdf_table": source_grid,
            "source_cells": sum(map(len, values.values()))}


def matrix_chunk_text(matrix: dict) -> str:
    rows = list(matrix["values"].items())
    columns = list(rows[0][1])
    lines = ["규격 (㎥/min) | " + " | ".join(columns)]
    lines.extend(f"{row} | " + " | ".join(cells[col] for col in columns) for row, cells in rows)
    return "5203-1800 180-195\n" + "\n".join(lines)


def main() -> int:
    spec_package = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    spec = spec_package["draft"]
    existing = {table["id"]: table for table in spec["tables"]}
    with pymupdf.open(PDF_PATH) as document:
        matrices = {table_id: equipment_matrix(document, table_id) for table_id in TABLE_LOCATIONS}
    for table_id, matrix in matrices.items():
        assert table_id in existing
        existing[table_id]["values"] = matrix["values"]
    route = next(item for item in spec["inputs"] if item["name"] == "machine_category")["source_table_map"]
    assert route[CATEGORY_ACCESSORY_MATRIX] == "p308-t1"
    route[CATEGORY_ACCESSORY_MATRIX] = ["p308-t1", "p308-t3"]

    chunks = [json.loads(line) for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    matrix_chunk = next(chunk for chunk in chunks if chunk.get("chunk_id") == "p308-t3")
    matrix_chunk["text"] = matrix_chunk_text(matrices["p308-t3"])
    matrix_chunk["structure"] = "ok"
    matrix_chunk["uncertain_record_ids"] = []
    matrix_chunk["issues"] = []

    spec_backup = ROOT / "tmp/5203-1800-spec-before-source-matrix-repair.json"
    chunks_backup = ROOT / "tmp/chunks-before-5203-1800-source-matrix-repair.jsonl"
    shutil.copy2(SPEC_PATH, spec_backup)
    shutil.copy2(CHUNKS_PATH, chunks_backup)
    SPEC_PATH.write_text(json.dumps(spec_package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CHUNKS_PATH.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in chunks) + "\n", encoding="utf-8")
    report = {
        "cause": "13 routed machine matrices were truncated to 1-2 source rows/columns; air-compressor accessory table p308-t3 had shifted duplicate labels and lacked full matrix routing",
        "reconstructed_tables": len(matrices),
        "reconstructed_source_value_cells": sum(item["source_cells"] for item in matrices.values()),
        "table_value_cells": {key: item["source_cells"] for key, item in matrices.items()},
        "accessory_route": route[CATEGORY_ACCESSORY_MATRIX],
        "manual_rendered_source_cells": matrices["p309-t0"].get("manual_cells_from_rendered_original"),
        "manual_rendered_source_headers": matrices["p308-t3"].get("manual_headers_from_rendered_original"),
        "backups": [str(spec_backup.relative_to(ROOT)), str(chunks_backup.relative_to(ROOT))],
        "spec_sha256": hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest(),
        "chunks_sha256": hashlib.sha256(CHUNKS_PATH.read_bytes()).hexdigest(),
    }
    report_path = ROOT / "evals/runtime_validation/repair-5203-1800-source-matrices-2026-10-19.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
