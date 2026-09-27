"""대한건설협회 임금 보고서와 보존한 상반기 CSV에서 직종별 노임을 재현한다."""

from __future__ import annotations

import csv
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/labor_rates"
PDF = RAW / "2026H2_wage_survey.pdf"
CSV = RAW / "2026H1_v1_team.csv"
OUTPUT = ROOT / "data/rates/labor_rates.json"
ORIGINAL_NAME = "[붙임]_2026년_하반기_적용_건설업_임금실태조사_보고서.pdf"
CODE = re.compile(r"(?m)^\*{0,2}([1-5]\d{3})\s*$")
MONEY = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|-)$")


def extract_h2() -> tuple[dict, int]:
    rates = {}
    with pymupdf.open(PDF) as doc:
        for page_index in range(9, 13):
            text = doc[page_index].get_text("text")
            matches = list(CODE.finditer(text))
            for index, match in enumerate(matches):
                body = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
                lines = [line.strip() for line in body.splitlines() if line.strip()]
                first_rate = next((i for i, line in enumerate(lines) if MONEY.fullmatch(line)), None)
                if first_rate is None or len(lines[first_rate:first_rate + 4]) < 4:
                    raise ValueError(f"PDF {page_index + 1}쪽 {match.group(1)} 직종/단가 추출 실패")
                values = lines[first_rate:first_rate + 4]
                if not all(MONEY.fullmatch(value) for value in values):
                    raise ValueError(f"PDF {page_index + 1}쪽 {match.group(1)} 단가 열 오류: {values}")
                name = "".join(lines[:first_rate]).replace(" ", "")
                if not name or match.group(1) in rates:
                    raise ValueError(f"PDF {page_index + 1}쪽 직종명 또는 중복 코드: {match.group(1)}")
                rates[match.group(1)] = {"name": name,
                                         "daily": values[0].replace(",", "") if values[0] != "-" else None,
                                         "pdf_page": page_index + 1}
        match = re.search(r"2026\.\s*9\.\s*1\s*\([^)]*\)\s*([\d,]+)", doc[4].get_text("text"))
        if not match:
            raise ValueError("PDF 5쪽 공표 평균 추출 실패")
        published_average = int(match.group(1).replace(",", ""))
    if len(rates) != 132 or published_average != 282737:
        raise ValueError(f"하반기 직종/공표 평균 불일치: {len(rates)} / {published_average}")
    return rates, published_average


def extract_h1() -> dict:
    rates = {}
    with CSV.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            code, name = row["세부직종별(1)"].split("-", 1)
            daily = row["2026.1/2"].strip().replace(",", "")
            rates[code] = {"name": name.strip(), "daily": daily if daily and daily != "-" else None}
    if len(rates) != 132:
        raise ValueError(f"상반기 직종 수 불일치: {len(rates)}")
    return rates


def build() -> tuple[dict, dict]:
    h2, published_average = extract_h2()
    h1 = extract_h1()
    if h2.keys() != h1.keys():
        raise ValueError(f"상·하반기 코드 차이: {sorted(h2.keys() ^ h1.keys())}")
    name_mismatches = [(code, h1[code]["name"], h2[code]["name"]) for code in h1
                       if re.sub(r"\s", "", h1[code]["name"]) != re.sub(r"\s", "", h2[code]["name"])]
    if name_mismatches:
        raise ValueError(f"상·하반기 직종명 차이: {name_mismatches}")
    data = {"versions": [
        {"id": "2026H2", "title": "2026년 하반기 적용 건설업 임금실태조사",
         "publisher": "대한건설협회", "published": "2026-09-01",
         "effective_from": "2026-09-01", "effective_to": None,
         "source_file": str(PDF.relative_to(ROOT)).replace("\\", "/"),
         "source_original_name": ORIGINAL_NAME, "source_pages": [10, 11, 12, 13],
         "average_source_page": 5, "published_average": str(published_average),
         "unit": "원/일(8시간)", "rates": h2},
        {"id": "2026H1", "title": "2026년 상반기 적용 건설업 임금실태조사",
         "publisher": "대한건설협회", "published": None,
         "effective_from": "2026-01-01", "effective_to": "2026-08-31",
         "source_file": str(CSV.relative_to(ROOT)).replace("\\", "/"),
         "source_tag": "v1.0-team", "source_pages": [], "unit": "원/일(8시간)",
         "rates": h1},
    ]}
    changes = []
    for code, current in h2.items():
        before = h1[code]["daily"]
        after = current["daily"]
        if before and after and int(before):
            percent = (Decimal(after) / Decimal(before) - 1) * 100
            changes.append((code, current["name"], percent))
    wages = [Decimal(item["daily"]) for item in h2.values() if item["daily"]]
    arithmetic_mean = (sum(wages) / len(wages)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    distribution = {"-10% 미만": 0, "-10%~-5%": 0, "-5%~0%": 0,
                    "0%~5%": 0, "5%~10%": 0, "10% 초과": 0}
    for _, _, percent in changes:
        if percent < -10:
            distribution["-10% 미만"] += 1
        elif percent < -5:
            distribution["-10%~-5%"] += 1
        elif percent < 0:
            distribution["-5%~0%"] += 1
        elif percent <= 5:
            distribution["0%~5%"] += 1
        elif percent <= 10:
            distribution["5%~10%"] += 1
        else:
            distribution["10% 초과"] += 1
    summary = {"h2_rows": len(h2), "h2_available": len(wages),
               "published_average": published_average,
               "arithmetic_mean_of_available_rates_half_up": str(arithmetic_mean),
               "average_note": "공표 평균은 조사 인원/임금 기반 평균이다. 개별 직종 공표값의 단순 평균과 다르다.",
               "matched_codes_and_names": len(h2), "comparable": len(changes),
               "change_distribution": distribution,
               "change_percent_min": str(min(change[2] for change in changes).quantize(Decimal("0.01"))),
               "change_percent_max": str(max(change[2] for change in changes).quantize(Decimal("0.01"))),
               "outliers_abs_over_10_percent": [
                   {"code": code, "name": name, "percent": str(percent.quantize(Decimal("0.01")))}
                   for code, name, percent in changes if abs(percent) > 10],
               "target_rates": {code: h2[code] for code in ("1013", "1003", "1007", "1002")}}
    return data, summary


def main() -> None:
    data, summary = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
