"""Source-cell and hourly equipment price check for the newly registered scraper."""
import json
from pathlib import Path

from backend.agent.tools.calc.price import _machine_rows, select_equipment_version
from pipeline.equipment_rates_general import parse_pages

ROOT = Path(__file__).resolve().parents[1]
MACHINE_CODE = "0406-0054"  # PDF 6쪽: 자주식 스크레이퍼, 5.4㎥


def main():
    parsed = parse_pages(range(6, 7))[MACHINE_CODE]
    expected = {
        "spec": "5.4㎥", "price": "100,891", "depr": "18,271",
        "fuel": "19.5", "misc": "22", "operator": "1",
    }
    for key, value in expected.items():
        assert parsed[key] == value, (key, parsed[key], value)

    rates = json.loads((ROOT / "data/rates/equipment_rates.json").read_text(encoding="utf-8"))
    machine = rates["machines"][MACHINE_CODE]
    assert machine["hourly_depreciation"] == 18_271
    assert machine["fuel_l_per_hr"] == "19.5"
    assert machine["pdf_page"] == 6

    spec = {"inputs": [{"name": "machine_size", "machine_codes": {"5.4㎥": MACHINE_CODE}}],
            "quantity_model": {"params": {"equipment": {
                "label": "스크레이퍼", "machine_code_input": "machine_size",
                "operator_rate_code": "301"}}}}
    line = {"unit": "hr", "applied": "10", "citations": []}
    rows = _machine_rows(spec, line, None, select_equipment_version("2026-06-01"),
                         {"machine_size": "5.4㎥"})
    depreciation = next(row for row in rows if row["category"] == "경비")
    assert depreciation["unit_price"] == "18271"
    assert depreciation["amount_exact"] == "182710"
    assert depreciation["amount"] == "182710.0"
    print("PASS 0406-0054 PDF fields and 10 hr machinery depreciation: 182,710 KRW")


if __name__ == "__main__":
    main()
