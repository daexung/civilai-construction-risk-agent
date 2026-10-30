"""Verify the 13-11-4 source rows, expiry gate, lookup result and citations."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/기계설비/13-11-4.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == "p909-t0")
    source = pymupdf.open(PDF)[908].find_tables().tables[0].extract()
    categories = [x.strip() for x in source[1][1].splitlines() if x.strip()]
    rates = [x.strip() for x in source[1][2].splitlines() if x.strip()]
    notes = [x.strip() for x in source[1][3].splitlines() if x.strip()]
    assert len(categories) == 8 and len(rates) == len(notes) == 7
    expected_categories = categories[:5] + categories[6:]
    assert list(table["values"]) == expected_categories
    assert [table["values"][name]["손료율(%/월)"] for name in expected_categories] == rates
    assert [table["values"][name]["비고"] for name in expected_categories] == notes

    checked = 0
    for name in expected_categories:
        result = lookup(spec, {"material_type": name, "is_expired": False})
        expected = table["values"][name]
        assert result["status"] == "computed" and result["value"] == expected, (name, result)
        assert len(result["provenance"]["citations"]) == 2
        assert all(c["internal_id"] == "p909-t0" and c["row"] == name
                   for c in result["provenance"]["citations"])
        checked += len(expected)
    blocked = lookup(spec, {"material_type": expected_categories[0], "is_expired": True})
    assert blocked["status"] == "blocked", blocked
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    print(json.dumps({"status": "pass", "source_table": "p909-t0", "printed_page": 853,
                      "source_cells_checked": checked, "noncalculable_group_heading_preserved": categories[5],
                      "lookup_paths": len(expected_categories), "expired_material": "blocked",
                      "citation_preflight": "pass"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
