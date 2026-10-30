"""Audit all four 8-3-9 equipment tables against source page 269."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/8-3-9.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = [
    ("3D GNSS 머신 가이던스(굴착기용)", "p325-t1", ["8201-0100", "3D GNSS MG", "5,000", "1,250", "0.9", "0.8", "0.1", "1,800", "1,600", "530", "3,930"]),
    ("3D GNSS 머신 컨트롤(MC) (굴착기용)", "p325-t2", ["8202-0100", "1.0\n(3D GNSS MC)", "5,000", "1,250", "0.9", "0.8", "0.1", "1,800", "1,600", "530", "3,930"]),
    ("3D GNSS 머신 가이던스(MG) (불도저용)", "p325-t3", ["8203-0019", "19 ton\n(3D GNSS MG)", "5,000", "1,250", "0.9", "0.8", "0.1", "1,800", "1,600", "530", "3,930"]),
    ("3D GNSS 머신 컨트롤(불도저용)", "p325-t4", ["8204-0100", "3D GNSS MC", "5,000", "1,250", "0.9", "0.8", "0.1", "1,800", "1,600", "530", "3,930"]),
]
COLS = ["규격(㎾)", "내용시간", "연간표준가동시간", "상각비율", "정비비율", "연간관리비율",
        "시 간 당(10-7) 상각비계수", "시 간 당(10-7) 정비비계수", "시 간 당(10-7) 관리비계수", "시 간 당(10-7) 계"]


def norm(value: str) -> str:
    return " ".join(value.split())


def main() -> int:
    source_tables = pymupdf.open(PDF)[324].find_tables().tables
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    field = spec["inputs"][0]
    assert field["source_table_map"] == {category: table_id for category, table_id, _ in EXPECTED}
    checked = 0
    for index, (category, table_id, source_row) in enumerate(EXPECTED, start=1):
        grid = source_tables[index].extract()
        extracted = [norm(x or "") for x in grid[-1]]
        expected_norm = [norm(x) for x in source_row]
        assert extracted == expected_norm, (table_id, extracted)
        table = next(t for t in spec["tables"] if t["id"] == table_id)
        code, *values = source_row
        assert list(table["values"]) == [code]
        row_values = table["values"][code]
        columns = [next(key for key in row_values if key.startswith("규격")), *COLS[1:]]
        assert [norm(row_values[column]) for column in columns] == [norm(value) for value in values], (table_id, columns, row_values, values)
        result = lookup(spec, {"equipment_type": category})
        assert result["status"] == "computed" and result.get("table_reference")
        assert result["provenance"]["table"] == table_id
        assert result["value"] == table["values"]
        citations = result["provenance"]["citations"]
        assert len(citations) == len(values) and all(c["internal_id"] == table_id for c in citations)
        checked += len(values)
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "pdf_page": 325, "printed_page": 269,
                      "source_rows": len(EXPECTED), "source_cells": checked,
                      "exact_category_routes": len(EXPECTED), "citations": checked, "citation_preflight": "pass"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
