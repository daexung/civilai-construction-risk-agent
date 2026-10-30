"""Remove non-source fixed axes from the single-column sink-faucet rate table."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one  # noqa: E402

SPEC_PATH = ROOT / "data/drafts/specs/기계설비/7-2-4.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
AUDIT = ROOT / "evals/runtime_validation/per-unit-sink-faucet-7-2-4-2026-10-19.json"
TABLE_ID = "p742-t0"
SOURCE = {"위생공": "0.164", "보통인부": "0.033"}


def main() -> int:
    package = json.loads(SPEC_PATH.read_text(encoding="utf8"))
    spec = package["draft"]
    rate = spec["quantity_model"]["params"]["unit_rate_table"]
    table = next(item for item in spec["tables"] if item["id"] == TABLE_ID)
    assert table["values"] == {trade: {"수량": value} for trade, value in SOURCE.items()}
    assert rate["trades"] == list(SOURCE)
    rate["row_input"] = None
    rate["column_input"] = None
    SPEC_PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

    routes = outputs = 0
    for quantity in ["1", "5"]:
        result = per_unit(spec, {"quantity": quantity})
        assert result["status"] == "computed", result
        got = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
        expected = {trade: Fraction(value) for trade, value in SOURCE.items()}
        assert got == expected, (quantity, got, expected)
        for line in result["unit_lines"]:
            cites = [cite for cite in line["citations"] if cite.get("internal_id") == TABLE_ID]
            assert len(cites) == 1
            assert cites[0].get("row") == line["name"] and cites[0].get("column") == "수량"
            assert cites[0].get("value") == SOURCE[line["name"]]
            assert Fraction(line["exact"]) * Fraction(quantity) == (
                Fraction(SOURCE[line["name"]]) * Fraction(quantity))
        routes += 1
        outputs += len(got)
    validation = validate_one(SPEC_PATH, ROOT / "data/drafts", load_chunks(CHUNKS),
                              file_sha256(CHUNKS))
    assert not validation["format_issues"], validation["format_issues"]
    assert not validation["citation_issues"], validation["citation_issues"]
    record = {"status": "pass", "section": "기계설비/7-2-4", "table_id": TABLE_ID,
              "source": "Original PDF p.742, printed p.686, visually inspected",
              "independent_source_cells": 2, "exact_quantity_routes": routes,
              "exact_rate_outputs_with_citations": outputs,
              "quantity_values": ["1", "5"], "format_preflight": "pass",
              "citation_preflight": "pass", "full_rule_verification": False,
              "open_note": "source equipment cost rule is not covered by this labor-rate check"}
    AUDIT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
