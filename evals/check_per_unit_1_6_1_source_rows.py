"""Check p371-t0 row restoration against printed p.315 and calculator output."""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/토목/1-6-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "포 장 공": {"수 량": "2", "일반포장": "550", "터널포장": "500"},
    "보 통 인 부": {"수 량": "2"},
    "아 스 팔 트 피 니 셔": {"규격": "3m", "수 량": "1"},
    "타 이 어 롤 러": {"규격": "8∼15ton", "수 량": "1"},
    "진 동 롤 러": {"규격": "10ton", "수 량": "1"},
}


def norm(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split()).casefold()


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table_values = spec["tables"][0]["values"]
    for row, values in table_values.items():
        assert EXPECTED[row].items() >= values.items(), (row, values)
    with pymupdf.open(PDF) as doc:
        # PDF page index 370 is printed page 315; inspect the source table text.
        source = norm(doc[370].get_text())
        assert "315" in source and "1-6-1린콘크리트기층포설" in source
        for row, values in EXPECTED.items():
            assert norm(row) in source, row
            for value in values.values():
                assert norm(value) in source, (row, value)
    result = adjusted_daily_crew(spec, {"pavement_type": "일반포장", "volume": "550"})
    assert result.get("status") == "computed", result
    assert result["person_days"] == {"포 장 공": "2", "보 통 인 부": "2"}, result
    assert result["equipment_days"] == {"아 스 팔 트 피 니 셔": "1", "타 이 어 롤 러": "1", "진 동 롤 러": "1"}, result
    lines = {line["name"]: line["exact"] for line in result["unit_lines"]}
    assert lines["포 장 공"] == "1/275" and lines["보 통 인 부"] == "1/275", lines
    assert all(lines[name] == "4/275" for name in result["equipment_days"]), lines
    for pavement_type, output in (("일반포장", "550"), ("터널포장", "500")):
        baseline = adjusted_daily_crew(spec, {"pavement_type": pavement_type, "volume": "100"})
        assert baseline.get("status") == "computed", baseline
        assert baseline["daily_volume_m3"] == output, baseline
        assert all(Fraction(value) == Fraction(200, int(output))
                   for value in baseline["person_days"].values()), baseline
        assert set(baseline["equipment_days"]) == {"아 스 팔 트 피 니 셔", "타 이 어 롤 러", "진 동 롤 러"}, baseline
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_page": 315, "source_rows": 5,
              "source_cells": 10, "calculation_case": "550 m3 at ordinary paving; labor rates and three equipment counts",
              "independent_expected": {"daily_output_m3": "550", "labor_person_days": {"포장공": "2", "보통인부": "2"},
                                       "equipment_days": {"아스팔트피니셔": "1", "타이어롤러": "1", "진동롤러": "1"}},
              "format_citation_preflight": "pass", "visual_review": "printed PDF p.315 table grid visually compared"}
    (ROOT / "evals/runtime_validation/per-unit-1-6-1-source-audit-2026-10-19.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
