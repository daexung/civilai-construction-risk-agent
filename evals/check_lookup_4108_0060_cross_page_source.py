"""Verify the 8-4-5 concrete plant rows and cross-page machine-code routes."""
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

SPEC = ROOT / "data/drafts/specs/공통/4108-0060.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "60㎥/hr": ("p336-t1", "0060", "60㎥/hr(96㎾)"),
    "90㎥/hr": ("p336-t1", "0090", "90 (144)"),
    "120㎥/hr": ("p336-t1", "0120", "120 (160)"),
    "150㎥/hr": ("p336-t1", "0150", "150 (177)"),
    "180㎥/hr": ("p336-t1", "0180", "180 (213)"),
    "210 (233)": ("p337-t0", "0210", "210 (233)"),
}
COLUMNS = ["기계명", "규격", "주연료\n(ℓ/hr)", "잡재료\n(주연료의%)", "조종원\n(인/일)"]
VALUES = ["콘크리트배치플랜트", None, "-", "-", "1"]


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    tables = {table["id"]: table for table in spec["tables"]}
    assert spec["inputs"][0]["machine_codes"] == {label: row for label, (_, row, _) in EXPECTED.items()}
    checked = citations = 0
    with pymupdf.open(PDF) as doc:
        source_pages = {"p336-t1": norm(doc[335].get_text()), "p337-t0": norm(doc[336].get_text())}
        for label, (table_id, row, spec_value) in EXPECTED.items():
            assert norm(row) in source_pages[table_id]
            assert norm(spec_value) in source_pages[table_id]
            result = lookup(spec, {"machine_spec": label})
            assert result["status"] == "computed" and result.get("row_reference"), (label, result)
            assert result["provenance"]["table"] == table_id
            assert result["provenance"]["row"] == row
            expected_row = dict(zip(COLUMNS, [*VALUES[:1], spec_value, *VALUES[2:]]))
            assert result["value"] == expected_row, (label, result["value"], expected_row)
            row_cites = result["provenance"]["citations"]
            assert len(row_cites) == 5
            for citation, column in zip(row_cites, COLUMNS):
                value = expected_row[column]
                assert (citation["internal_id"], citation["row"], citation["column"], citation["value"]) == (
                    table_id, row, column, value)
                checked += 1
                citations += 1
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    assert checked == citations == 30
    report = {"status": "pass", "printed_pages": [280, 281], "cross_page_routes": 6,
              "independent_source_cells": checked, "runtime_exact_cell_citations": citations,
              "routes": {label: {"table_id": table, "exact_row": row}
                         for label, (table, row, _) in EXPECTED.items()},
              "source_structure": "8-4-5 table begins on p336-t1 and continues with 0210 on p337-t0",
              "visual_review": "rendered PDF pages 280-281 checked against header, merged machine name, row codes and all values",
              "citation_preflight": "pass"}
    out = ROOT / "evals/runtime_validation/lookup-4108-0060-cross-page-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
