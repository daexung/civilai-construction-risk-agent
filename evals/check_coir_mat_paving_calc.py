"""Source-derived checks for coir-fiber mat paving."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from pypdf import PdfReader

from backend.agent.tools.calc.daily_crew import adjusted_daily_crew

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    package = json.loads(next((ROOT / "data/drafts/specs").rglob("4-4-4.json")).read_text(encoding="utf-8"))
    spec = package["draft"]
    assert package["calc_type"] == "daily_crew"
    source = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))).pages[153].extract_text() or ""
    for value in ("90", "130", "1.5m", "2.0m", "2"):
        assert value in source, value

    widths = next(x for x in spec["inputs"] if x["name"] == "width_band")["allowed_values"]
    trade_names = list(spec["tables"][0]["values"])
    for width, rate in zip(widths, (90, 130)):
        result = adjusted_daily_crew(spec, {"width_band": width, "area": "260"}, labor_only=True)
        assert result["status"] == "computed", result
        days = Fraction(260, rate)
        assert Fraction(result["daily_volume_m3"]) == rate
        assert Fraction(result["work_days"]) == days
        assert {trade: Fraction(result["person_days"][trade]) for trade in trade_names} == {
            trade_names[0]: 2 * days, trade_names[1]: days}
        assert result["provenance"]["daily_volume_m3"]["base_output"]["citations"]

    invalid = adjusted_daily_crew(spec, {"width_band": "wider than source table", "area": "260"}, labor_only=True)
    assert invalid["status"] == "rejected", invalid
    print("PASS p.98 source width columns, 90/130㎡ daily output, two trades, citations, and out-of-band rejection; earthwork remains separate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
