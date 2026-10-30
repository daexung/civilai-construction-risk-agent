"""Coordinate-check machine coefficient rows against the original PDF tables."""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
CODE = re.compile(r"(?:\d{4}-)?\d{4}$")


def norm(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).replace(",", "")


def _verticals(page, bbox: pymupdf.Rect) -> list[float]:
    xs = {round(bbox.x0, 1), round(bbox.x1, 1)}
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] != "l":
                continue
            a, b = item[1], item[2]
            if (abs(a.x - b.x) < 1 and bbox.x0 - 1 <= a.x <= bbox.x1 + 1
                    and min(a.y, b.y) <= bbox.y1 and max(a.y, b.y) >= bbox.y0
                    and abs(a.y - b.y) > 20):
                xs.add(round(a.x, 1))
    return sorted(xs)


def extract_rows(page, bbox: pymupdf.Rect, expected_rows: set[str], data_columns: int) -> dict:
    """Read cell text by PDF word coordinates and table grid; never use chunks/spec values."""
    xs = _verticals(page, bbox)
    if len(xs) != data_columns + 2:  # machine-code column plus the declared data columns
        raise AssertionError({"grid_columns": len(xs) - 1, "expected": data_columns + 1,
                              "x_boundaries": xs, "bbox": tuple(bbox)})
    words = [w for w in page.get_text("words")
             if bbox.x0 <= (w[0] + w[2]) / 2 <= bbox.x1
             and bbox.y0 <= (w[1] + w[3]) / 2 <= bbox.y1]
    code_tokens = []
    prefix = None
    for word in words:
        center_x, center_y, token = (word[0] + word[2]) / 2, (word[1] + word[3]) / 2, word[4]
        if not xs[0] <= center_x < xs[1] or not CODE.fullmatch(token):
            continue
        if "-" in token:
            prefix, suffix = token.split("-", 1)
        else:
            suffix = token
        if prefix is None:
            continue
        full_code = f"{prefix}-{suffix}"
        expected_key = full_code if full_code in expected_rows else suffix if suffix in expected_rows else None
        if expected_key is not None:
            code_tokens.append((expected_key, center_y))
    observed = {}
    for code, center_y in code_tokens:
        cells = []
        for i in range(data_columns):
            x0, x1 = xs[i + 1], xs[i + 2]
            tokens = [w[4] for w in words if x0 <= (w[0] + w[2]) / 2 < x1
                      and abs((w[1] + w[3]) / 2 - center_y) <= 3.2]
            cells.append("".join(tokens))
        if code in observed:
            raise AssertionError(("duplicate source code row", code, observed[code], cells))
        observed[code] = cells
    return observed


def check_spec(division: str, section: str) -> tuple[int, dict]:
    package = json.loads((ROOT / "data/drafts/specs" / division / f"{section}.json")
                         .read_text(encoding="utf-8"))
    spec = package["draft"]
    pdf = pymupdf.open(PDF)
    chunks = [json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl")
              .read_text(encoding="utf-8").splitlines() if line.strip()]
    chunk_by_table = {c.get("source", {}).get("table_id"): c for c in chunks
                      if c.get("kind") == "table"}
    checked = 0
    table_reports = {}
    for table in spec.get("tables", []):
        table_id = table["id"]
        match = re.fullmatch(r"p(\d+)-t\d+", table_id)
        if not match:
            continue
        page_no = int(match.group(1))
        rows = table.get("values", {})
        if not rows:
            continue
        column_names = list(next(iter(rows.values())))
        expected = {row: list(cells.values()) for row, cells in rows.items()}
        chunk = chunk_by_table[table_id]
        bbox = pymupdf.Rect(chunk["source"]["bbox"])
        actual = extract_rows(pdf[page_no - 1], bbox, set(expected), len(column_names))
        missing = set(expected) - set(actual)
        differences = []
        for row, cells in expected.items():
            if row not in actual:
                continue
            if len(actual[row]) != len(cells):
                differences.append({"row": row, "source": actual[row], "spec": cells,
                                    "reason": "column count differs"})
                continue
            for column, source_value, spec_value in zip(column_names, actual[row], cells):
                if norm(source_value) != norm(spec_value):
                    differences.append({"row": row, "column": column,
                                        "source": source_value, "spec": spec_value})
                checked += 1
        table_reports[table_id] = {"pdf_page": page_no, "rows_expected": len(expected),
                                   "rows_found": len(actual), "missing_rows": sorted(missing),
                                   "cells_checked": sum(len(v) for v in expected.values()),
                                   "differences": differences}
    return checked, table_reports


def main() -> int:
    # 8-3-2's 25 currently offered machine codes span multiple extracted table fragments.
    checked, report = check_spec("공통", "8-3-2")
    out = {"method": "PyMuPDF source-page vector grid + word coordinates, compared to independent spec matrix; no text fuzzy matching",
           "section": "공통/8-3-2", "table_reports": report,
           "cells_checked": checked,
           "status": "pass" if checked and all(not x["differences"] and not x["missing_rows"]
                                                for x in report.values()) else "mismatch"}
    path = ROOT / "evals/runtime_validation/machine-row-source-cells-2026-10-19.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": out["status"], "cells_checked": checked,
                      "tables": {k: {"rows_expected": v["rows_expected"], "rows_found": v["rows_found"],
                                     "missing_rows": v["missing_rows"], "differences": len(v["differences"])}
                                 for k, v in report.items()}}, ensure_ascii=False, indent=2))
    return 0 if out["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
