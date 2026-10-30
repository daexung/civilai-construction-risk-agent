"""Check p342-t0's merged row labels and values against its PDF table grid."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/8-4-9.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
LABELS = ["주연료", "잡재료", "선원"]
UNITS = ["ℓ/hr", "%", "인"]
SPECS = ["1ton\n7.5\n㎾", "2t\n22.4\n㎾", "3t\n37.3\n㎾", "4t\n44.8\n㎾", "10t\n74.6\n㎾", "12t\n89.5\n㎾", "20t\n149.2㎾", "25t\n186.5㎾", "30t\n223.8㎾", "40t\n283.5㎾", "70t\n507.3㎾"]
ROWS = [
    ["1.3", "3.8", "7.1", "7.6", "12.7", "15.3", "25.5", "31.8", "38.1", "48.3", "86.3"],
    ["63"] * 11,
    ["2", "2", "2", "2", "2", "2", "3", "3", "3", "3", "3"],
]


def main() -> int:
    page = pymupdf.open(PDF)[341]
    grid = page.find_tables().tables[0].extract()
    assert [" ".join(x.split()) for x in grid[1][2:13]] == [" ".join(x.split()) for x in SPECS]
    assert [" ".join(x.split()) for x in grid[2][1].splitlines()] == UNITS
    columns = [[x.strip() for x in grid[2][col].splitlines() if x.strip()] for col in range(2, 13)]
    source_values = [[columns[col][row] for col in range(11)] for row in range(3)]
    assert source_values == ROWS, source_values
    source_text = page.get_text()
    # The source image shows "선 원" in a narrow merged cell; text extraction
    # splits that label across lines, while the source-backed spec normalizes it.
    assert source_text.index("주연료\nℓ/hr") < source_text.index("잡재료\n%")
    assert "선\n원\n인\n2\n2" in source_text

    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p342-t0")
    expected = {label: dict(zip(SPECS, values)) for label, values in zip(LABELS, ROWS)}
    assert table["values"] == expected
    result = lookup(spec, {"machine_type": "양묘선(앵커바지)"})
    assert result["status"] == "computed" and result["value"] == expected
    assert result["provenance"]["table"] == "p342-t0"
    citations = [c for line in result["unit_lines"] for c in line["citations"]]
    assert len(citations) == 33 and all(c["internal_id"] == "p342-t0" for c in citations)
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    chunks = load_chunks(ROOT / "data/processed/chunks.all.jsonl")
    assert all(label in chunks["p342-t0"]["text"] for label in LABELS)
    print(json.dumps({"status": "pass", "pdf_page": 342, "printed_page": 286,
                      "source_row_labels": len(LABELS), "source_cells": 33,
                      "lookup_cells": 33, "citations": len(citations), "citation_preflight": "pass"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
