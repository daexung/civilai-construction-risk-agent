"""Compare every 3-2-2 rate cell with the printed PDF and exercise labor outputs."""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path
from fractions import Fraction

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/3-2-2.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "풍 화 암": ["0.33", "0.16", "0.30", "1.26"],
    "연 암": ["0.41", "0.21", "0.48", "1.68"],
    "보 통 암": ["0.58", "0.29", "0.60", "2.40"],
    "경 암": ["0.94", "0.48", "0.96", "3.90"],
}
COLUMNS = ["착암공\n(인)", "보통인부\n(인)", "공기압축기\n(시간)", "소형브레이커\n(시간)"]


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = spec["tables"][0]
    assert table["id"] == "p124-t0" and list(table["values"]) == list(EXPECTED)
    assert list(table["values"].values())[0].keys() == dict.fromkeys(COLUMNS).keys()
    checked = 0
    with pymupdf.open(PDF) as doc:
        page = doc[123]
        text = norm(page.get_text())
        assert "3-2-2굴착(인력/암반)" in text
        for row, values in EXPECTED.items():
            assert norm(row) in text
            for column, value in zip(COLUMNS, values):
                for token in re.findall(r"[가-힣a-z]+|[0-9.]+", norm(column + " " + value)):
                    assert token in text, (row, column, value, token)
                assert table["values"][row][column] == value
                citation = {"table_id": "p124-t0", "row": row, "column": column, "value": value}
                assert citation in package["citations"]
                checked += 1
    results = []
    for rock, row in zip(["풍화암", "연암", "보통암", "경암"], EXPECTED):
        result = per_unit(spec, {"rock_type": rock, "volume": "10"})
        assert result["status"] == "computed", (rock, result)
        outputs = {line["name"]: line for line in result["unit_lines"]}
        expected_names = COLUMNS
        assert set(outputs) == set(expected_names), (rock, outputs.keys())
        rates = {}
        for column, raw in zip(COLUMNS, EXPECTED[row]):
            line = outputs[column]
            assert line["exact"] == str(Fraction(raw)), (rock, column, line)
            assert line["unit"] in ("인/㎥", "hr/㎥"), (rock, column, line["unit"])
            assert line["kind"] == ("equipment" if "시간" in column else "labor")
            rates[column] = line["exact"]
        totals_at_10m3 = {column: str(Fraction(raw) * 10) for column, raw in zip(COLUMNS, EXPECTED[row])}
        results.append({"rock": rock, "source_unit_rates": rates,
                        "independent_totals_at_10m3": totals_at_10m3})
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_page": 68, "independent_source_cells": checked,
              "reconstructed_source_rows": len(EXPECTED), "exact_cell_citations": checked,
              "labor_calculation_cases": results,
              "equipment_hours": "equipment-hour unit rates are emitted; monetary equipment pricing was not checked here",
              "format_citation_preflight": "pass"}
    out = ROOT / "evals/runtime_validation/per-unit-3-2-2-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
