"""Verify the previously omitted 3611-0142 coefficient row from PDF p.242."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/3611-0142.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = ["3611-0142", "105.9", "8,000", "890", "0.9", "0.5", "0.1",
            "1,125", "625", "674", "2,424"]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    source = pymupdf.open(PDF)[297].find_tables().tables[1].extract()
    observed = source[2]
    assert observed == EXPECTED, (observed, EXPECTED)
    result = lookup(spec, {"machine_spec": "105.9"})
    expected_cells = spec["tables"][0]["values"]["105.9"]
    assert result["status"] == "computed" and result["value"] == expected_cells, result
    assert len(result["provenance"]["citations"]) == 10
    assert all(c["internal_id"] == "p298-t1" and c["row"] == "105.9"
               for c in result["provenance"]["citations"])
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "source_table": "p298-t1", "printed_page": 242,
                      "independent_source_cells": 10, "lookup_cells": 10,
                      "source_unit": "㎾", "citation_preflight": "pass"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
