"""2026년 건설기계 경비산출표의 콘크리트 펌프차 8개 규격을 재현한다."""

from __future__ import annotations

import json
import re
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/equipment_rates/2026_machine_cost_table.pdf"
OUTPUT = ROOT / "data/rates/equipment_rates.json"
ROW = re.compile(
    r"(4504-\d{4})\s+(\d+m,\s*\d+~\d+㎥/hr)\s+([\d,]+)\s+([\d,]+)\s+([\d.]+)\s+(\d+)\s+(\d+)\s+(-|\d+)\s+(-|\d+)"
)


def build() -> dict:
    machines = {}
    with pdfplumber.open(ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf") as standard:
        coefficient_rows = "\n".join((standard.pages[page - 1].extract_text() or "") for page in (300, 301))
        if len(re.findall(r"8,400\s+1,070\s+0\.9\s+0\.65\s+0\.14\s+1,071\s+774\s+795\s+2,640", coefficient_rows)) != 8:
            raise ValueError("품셈 PDF 300~301쪽 4504 손료계수 8개 교차 검증 실패")
    with pdfplumber.open(PDF) as pdf:
        for page in (13, 14):
            for match in ROW.finditer(pdf.pages[page - 1].extract_text() or ""):
                code, spec, price, depreciation, fuel, misc, operator, assistant, foreman = match.groups()
                machines[code] = {
                    "name": "콘크리트 펌프차", "spec": spec,
                    "price_thousand_won": int(price.replace(",", "")),
                    "hourly_depreciation": int(depreciation.replace(",", "")),
                    "fuel_type": "경유", "fuel_l_per_hr": fuel,
                    "misc_pct_of_fuel": int(misc),
                    "operator_per_day": int(operator),
                    "assistant_per_day": None if assistant == "-" else int(assistant),
                    "foreman_per_day": None if foreman == "-" else int(foreman),
                    "pdf_page": page,
                }
    if len(machines) != 8:
        raise ValueError(f"4504 추출 수 불일치: {len(machines)}")
    for code, entry in machines.items():
        calculated = (Decimal(entry["price_thousand_won"]) * 1000
                      * Decimal(2640) / Decimal(10_000_000)).to_integral_value(rounding=ROUND_DOWN)
        if int(calculated) != entry["hourly_depreciation"]:
            raise ValueError(f"{code} 손료계수 불일치: {calculated} != {entry['hourly_depreciation']}")
    return {
        "version": "2026", "publisher": "대한건설협회", "published": "2026-01-08",
        "source_file": str(PDF.relative_to(ROOT)).replace("\\", "/"),
        "source_original_name": "2026년 건설기계의 기계경비 산출표.pdf",
        "source_pages": [2, 13, 14], "standard_coefficient_pages": [300, 301],
        "hourly_depreciation_coefficient_4504": "2640/10000000",
        "notes": {
            "price_unit": "천원", "hourly_depreciation_unit": "원/hr",
            "fuel_unit": "ℓ/hr", "exchange_rate_header": "1$= 1,118.10",
            "fuel_type": "주연료란에 휘발유 또는 중유로 표시되지 아니한 것은 경유를 말합니다. (해상장비 포함)",
            "fuel_price": "주연료 가격은 구입조건 또는 유가등락 등에 따라 달라지므로 게재하지 아니하였습니다.",
            "misc": "잡재료는 주연료에 대한 비율을 말하며, 자세한 사항은 표준품셈(공통부문) \"8-4 운전경비 산정\"을 참고하시기 바랍니다.",
        },
        "machines": machines,
    }


def main() -> None:
    data = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for code, entry in data["machines"].items():
        print(code, entry["spec"], entry["price_thousand_won"], entry["hourly_depreciation"],
              entry["fuel_l_per_hr"], entry["misc_pct_of_fuel"], entry["operator_per_day"])


if __name__ == "__main__":
    main()
