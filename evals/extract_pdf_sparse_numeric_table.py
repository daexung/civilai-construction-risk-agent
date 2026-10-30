"""Rebuild sparse numeric tables whose PDF text extractor flattened row cells.

The helper uses detected table column bounds plus text coordinates. It does not
guess blank cells: absent source numerals remain absent from the returned row.
"""
from __future__ import annotations

import re
from pathlib import Path

import pymupdf as fitz


def extract_sparse_numeric_table(pdf_path: str | Path, page_number: int,
                                 table_index: int = 0,
                                 row_label_column: int = 0) -> dict:
    doc = fitz.open(pdf_path)
    page = doc[page_number - 1]
    # The layout detector writes advisory text to stdout; keep CLI output JSON.
    from contextlib import redirect_stdout
    from io import StringIO
    with redirect_stdout(StringIO()):
        detected = page.find_tables().tables
    if table_index < 0 or table_index >= len(detected):
        raise ValueError(f"table index {table_index} outside detected table count {len(detected)}")
    table = detected[table_index]
    grid = table.extract()
    if (not grid or len(grid[0]) < 2 or row_label_column < 0
            or row_label_column >= len(grid[0]) - 1):
        raise ValueError("table has no numeric columns")
    x0, _, x1, _ = table.bbox
    x_bounds = sorted({round(cell[0], 3) for cell in table.cells
                       if x0 - 1 <= cell[0] <= x1 + 1} | {round(x1, 3)})
    if len(x_bounds) != len(grid[0]) + 1:
        raise ValueError("detected table column bounds do not match extracted header count")
    label_x = x_bounds[row_label_column]
    label_column_cells = [cell for cell in table.cells if abs(cell[0] - label_x) < 1]
    first_data_row = next((i for i, row in enumerate(grid)
                           if row and re.fullmatch(r"\s*φ?\s*\d+(?:\.\d+)?\s*",
                                                  str(row[row_label_column] or ""))), None)
    if first_data_row is not None and len(label_column_cells) == len(grid):
        body_cells = label_column_cells[first_data_row:]
    else:
        body_cells = [cell for cell in label_column_cells
                      if cell[3] - cell[1] >= max((c[3] - c[1] for c in label_column_cells), default=0) * .8]
    if not body_cells:
        raise ValueError("could not identify the table body region")
    body_top = min(cell[1] for cell in body_cells)
    body_bottom = max(cell[3] for cell in body_cells)
    words = page.get_text("words")
    labels: list[tuple[str, float]] = []
    for word in words:
        wx0, wy0, wx1, wy1, text, *_ = word
        cy = (wy0 + wy1) / 2
        if x_bounds[row_label_column] <= wx0 < x_bounds[row_label_column + 1] and body_top <= cy <= body_bottom:
            normalized = text.replace("φ", "").replace("Φ", "").strip()
            if re.fullmatch(r"\d+(?:\.\d+)?", normalized):
                labels.append((normalized, cy))
    labels.sort(key=lambda item: item[1])
    if not labels or len({value for value, _ in labels}) != len(labels):
        raise ValueError("row labels are missing or duplicated; refusing ambiguous reconstruction")
    rows = {value: {} for value, _ in labels}
    column_labels = []
    header_depth = first_data_row if first_data_row is not None else len(grid) - 1
    inherited_headers = [None] * header_depth
    for col in range(row_label_column + 1, len(grid[0])):
        parts = []
        for level, header_row in enumerate(grid[:header_depth]):
            value = header_row[col] if col < len(header_row) else None
            if value:
                inherited_headers[level] = str(value).replace("\n", " ").strip()
            group = inherited_headers[level]
            if group and (not parts or group != parts[-1]):
                parts.append(group)
        label = " ".join(dict.fromkeys(" ".join(part.split()) for part in parts))
        label = re.sub(r"\s*\([^)]*\)\s*", " ", label)
        label = " ".join(label.split())
        if not label:
            raise ValueError(f"source column {col} has no header")
        column_labels.append(label)
    numeric = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
    for word in words:
        wx0, wy0, wx1, wy1, text, *_ = word
        cy = (wy0 + wy1) / 2
        if not body_top <= cy <= body_bottom or not numeric.fullmatch(text.replace(",", "")):
            continue
        col = next((i for i in range(row_label_column + 1, len(x_bounds) - 1)
                    if x_bounds[i] <= wx0 < x_bounds[i + 1]), None)
        if col is None:
            continue
        row, row_y = min(labels, key=lambda item: abs(item[1] - cy))
        if abs(row_y - cy) > 5:
            continue
        column = column_labels[col - row_label_column - 1]
        if column in rows[row]:
            raise ValueError(f"duplicate value at row={row!r}, column={column!r}")
        rows[row][column] = text
    return {"page_number": page_number, "table_index": table_index,
            "row_label_column": row_label_column,
            "headers": column_labels,
            "rows": rows, "body_bbox": [round(x0, 2), round(body_top, 2),
                                        round(x1, 2), round(body_bottom, 2)]}


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("page", type=int, help="one-based PDF page number")
    parser.add_argument("--table", type=int, default=0)
    parser.add_argument("--row-label-column", type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(extract_sparse_numeric_table(args.pdf, args.page, args.table,
                                                 args.row_label_column),
                     ensure_ascii=False, indent=2))
