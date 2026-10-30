"""원문 톤당 품과 SI ton 입력을 공통 환산하는 결함의 최소 재현 및 회귀 검사."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pypdf import PdfReader  # noqa: E402
from backend.agent.tools.calc.per_unit import conversion, per_unit  # noqa: E402


EXPECTED = {
    "13-7-2": {
        "기계기사": "0.47", "플랜트기계설치공": "3.14", "플랜트제관공": "0.54",
        "플랜트용접공": "1.10", "측량사": "0.02", "철골공": "0.47",
        "비계공": "1.26", "특별인부": "2.96",
    },
    "13-7-3": {
        "기계기사": "0.42", "플랜트기계설치공": "1.50", "플랜트제관공": "1.43",
        "플랜트용접공": "0.64", "철골공": "0.74", "비계공": "1.78", "특별인부": "2.13",
    },
}


def main() -> int:
    relations = (("ton", "톤", Fraction(1)), ("t", "톤", Fraction(1)),
                 ("톤", "ton", Fraction(1)), ("kg", "톤", Fraction(1, 1000)),
                 ("ton", "kg", Fraction(1000)))
    for source, target, expected in relations:
        assert conversion(source, target) == expected, (source, target, conversion(source, target))
    assert conversion("m", "톤") is None

    pdf = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf")))
    page = "".join((pdf.pages[879].extract_text() or "").split())
    assert "824기계설비부문13-7-2노정장입장치기기설치(톤당)" in page
    assert "13-7-3노체4본주및DECK설치(톤당)" in page

    for section, expected_rates in EXPECTED.items():
        package = json.loads((ROOT / f"data/drafts/specs/기계설비/{section}.json").read_text(encoding="utf-8"))
        spec = package["draft"]
        rates = spec["quantity_model"]["params"]["unit_rate_table"]
        table = next(table for table in spec["tables"] if table["id"] == rates["table"])
        assert table["unit"] == "인/톤" and set(rates["trades"]) == set(expected_rates)
        result = per_unit(spec, {"quantity": "5/2"}, labor_only=True)
        assert result["status"] == "computed", (section, result)
        actual = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]
                  if line["kind"] == "labor"}
        # unit_lines report source labor per ton; price/aggregate later apply the entered 2.5t.
        wanted = {trade: Fraction(rate) for trade, rate in expected_rates.items()}
        assert actual == wanted, (section, actual, wanted)
        assert all(line["citations"] for line in result["unit_lines"] if line["kind"] == "labor")
    print("PASS Korean 톤 ↔ t/ton 환산, 원문 p.824 톤당 표 2종 독립 산출값 및 표 인용")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
