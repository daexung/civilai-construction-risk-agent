"""Verify the source-oriented row/column mapping for lookup 8-4-5."""
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

SPEC = ROOT / "data/drafts/specs/공통/8-4-5.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED_SPECS = ["60㎥/hr(96㎾)", "90 (144)", "120 (160)", "150 (177)", "180 (213)"]


def norm(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p336-t1")
    assert list(table["values"]) == ["콘크리트배치플랜트"]
    assert spec["inputs"][1]["allowed_values"] == EXPECTED_SPECS

    # Read the original printed matrix independently from the draft's row data.
    pdf = pymupdf.open(PDF)
    source_table = pdf[335].find_tables().tables[1].extract()
    assert len(source_table) == 2 and len(source_table[0]) == 6
    source_name = norm(source_table[1][1])
    source_specs = [norm(v) for v in (source_table[1][2] or "").splitlines() if v.strip()]
    source_crew = [v.strip() for v in (source_table[1][5] or "").splitlines() if v.strip()]
    assert source_name == norm("콘크리트배치플랜트")
    assert source_specs == [norm(v) for v in EXPECTED_SPECS], (source_specs, EXPECTED_SPECS)
    assert source_crew == ["1"] * 5

    checks = 0
    for expected_spec in EXPECTED_SPECS:
        result = lookup(spec, {"machine_name": "콘크리트배치플랜트", "spec": expected_spec})
        assert result["status"] == "computed" and result["value"] == "1", (expected_spec, result)
        assert result["unit"] == "인/일", (expected_spec, result)
        citation = result["provenance"]["citations"][0]
        assert (citation["internal_id"], citation["row"], citation["column"], citation["value"]) == (
            "p336-t1", "콘크리트배치플랜트", expected_spec, "1")
        checks += 1

    chunks = load_chunks(ROOT / "data/processed/chunks.all.jsonl")
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", chunks, None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "source_table": "p336-t1", "printed_page": 280,
                      "orientation": "machine name row × specification columns",
                      "independent_source_cells": 5, "lookup_cases": checks,
                      "citation_preflight": "pass"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
