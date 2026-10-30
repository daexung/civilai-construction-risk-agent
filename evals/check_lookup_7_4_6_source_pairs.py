"""Verify all 7-4-6 grain-size/loss-rate pairs and lookup citations."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/토목/7-4-6.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
PAIRS = [
    ("1.2이상", "없음"), ("1.2∼0.5", "5∼8"), ("0.6∼0.3", "10∼15"),
    ("0.3∼0.15", "20∼27"), ("0.15∼0.075", "30∼35"), ("0.075이하", "30∼100"),
]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = spec["tables"][0]
    source_text = pymupdf.open(PDF)[451].get_text()
    for particle, loss in PAIRS:
        assert particle in source_text and loss in source_text, (particle, loss)
        assert table["values"]["유실율(%)"][particle] == loss
        result = lookup(spec, {"particle_size": particle})
        assert result["status"] == "computed" and result["value"] == loss, (particle, result)
        citation = result["provenance"]["citations"][0]
        assert (citation["internal_id"], citation["row"], citation["column"], citation["value"]) == (
            "p452-t0", "유실율(%)", particle, loss)
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "table_id": "p452-t0", "printed_page": 396,
                      "independent_source_pairs": len(PAIRS), "lookup_cells": len(PAIRS),
                      "citation_preflight": "pass"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
