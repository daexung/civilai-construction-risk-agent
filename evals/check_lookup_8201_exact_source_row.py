"""Check p326-t0's single exact equipment row, ten cells and fail-closed guard."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/8201-0100.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"


def lines(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").splitlines() if item.strip()]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = spec["tables"][0]
    assert table["id"] == "p326-t0" and list(table["values"]) == ["8205-0100"]
    with pymupdf.open(PDF) as doc:
        raw = doc[325].find_tables().tables[0].extract()[2]
    codes = lines(raw[0])
    source_columns = [lines(cell) for cell in raw[1:]]
    assert codes == ["8205-0100"]
    row = table["values"][codes[0]]
    assert len(source_columns) == len(row) == 10
    for column, (field, expected) in enumerate(row.items()):
        assert "".join("".join(source_columns[column]).split()) == "".join(expected.split()), (
            field, source_columns[column], expected)

    result = lookup(spec, {"equipment_code": "8205-0100"})
    assert result["status"] == "computed" and result["row_reference"]
    assert result["value"] == row
    expected = {("p326-t0", "8205-0100", field, value) for field, value in row.items()}
    actual = {(c["internal_id"], c["row"], c["column"], c["value"])
              for line in result["unit_lines"] for c in line["citations"]}
    assert actual == expected and len(actual) == 10

    bad_spec = copy.deepcopy(spec)
    next(f for f in bad_spec["inputs"] if f["name"] == "equipment_code")["machine_codes"] = {
        "8205-0100": "8205-9999"
    }
    bad = lookup(bad_spec, {"equipment_code": "8205-0100"})
    assert bad["status"] == "unresolvable", bad
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "source_rows": 1, "source_value_cells": 10,
              "runtime_row_citations": 10, "exact_mapped_row": "8205-0100",
              "incorrect_explicit_mapping": "unresolvable", "citation_preflight": "pass"}
    out = ROOT / "evals/runtime_validation/lookup-8201-exact-source-row-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
