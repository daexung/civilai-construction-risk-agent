"""Independently compare the recovered 8-4-4 lookup matrix to the PDF table."""
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

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SPEC = ROOT / "data/drafts/specs/공통/8-4-4.json"
FIELDS = ["기계명", "규격", "주연료\n(ℓ/hr)", "잡재료\n(주연료의%)", "조종원\n(인/일)"]


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or "")).replace(",", "")


def main() -> int:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p336-t0")
    values = table["values"]
    pdf = pymupdf.open(PDF)
    # Independent extractor: PyMuPDF's table-grid extraction, rather than the
    # word-center row reconstruction used to author the recovered matrix.
    extracted = pdf[335].find_tables().tables[0].extract()
    assert len(extracted) == 2 and len(extracted[0]) == 6, "expected one six-column source table"
    source_columns = {field: normalize("\n".join(row[i] or "" for row in extracted[1:]))
                      for i, field in enumerate(FIELDS, start=1)}
    code_lines = [line.strip() for line in (extracted[1][0] or "").splitlines() if line.strip()]
    expanded_codes = []
    prefix = None
    for code in code_lines:
        if "-" in code:
            prefix = code.split("-", 1)[0] + "-"
            expanded_codes.append(code)
        else:
            assert prefix is not None and code.isdigit(), ("invalid abbreviated source code", code)
            expanded_codes.append(prefix + code)
    assert expanded_codes == list(values), (expanded_codes, list(values))

    checked = 0
    cursors = {field: 0 for field in FIELDS}
    for code, row in values.items():
        result = lookup(spec, {"machine_code": code})
        assert result["status"] == "computed", (code, result)
        assert result["value"] == row, (code, result["value"], row)
        for field, value in row.items():
            target = normalize(str(value))
            pos = source_columns[field].find(target, cursors[field])
            assert target and pos >= 0, (code, field, value, "not found in source column order")
            cursors[field] = pos + len(target)
            checked += 1

    # A manually transcribed bottom-row check anchors the independent extractor
    # to the rendered original, including the numeric cells used for this lookup.
    expected = {
        "기계명": "슬러리실 기계", "규격": "3.0~3.8m", "주연료\n(ℓ/hr)": "23.4",
        "잡재료\n(주연료의%)": "29", "조종원\n(인/일)": "1",
    }
    assert values["3901-0300"] == expected, (values["3901-0300"], expected)
    print(json.dumps({"status": "pass", "pdf_printed_page": 280, "table_id": "p336-t0",
                      "source_rows": len(values), "source_cells_checked": checked,
                      "lookup_paths_checked": len(values), "independent_bottom_row_cells": 5},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
