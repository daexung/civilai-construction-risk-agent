"""공표 노임, 1-2-2 버림, 일위대가의 부분 금액을 오프라인 검사한다."""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pymupdf

os.environ["AGENT_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402
from agent.nodes.fill import extract_inputs  # noqa: E402
from api.main import app  # noqa: E402
from pipeline.labor_rates import build  # noqa: E402


def main() -> int:
    checks = []
    generated, summary = build()
    saved = json.loads((ROOT / "data/rates/labor_rates.json").read_text(encoding="utf-8"))
    checks.append(("P1 단가 재생성과 132개 직종", generated == saved and summary["h2_rows"] == 132
                   and summary["matched_codes_and_names"] == 132))
    checks.append(("P2 보고서 공표 평균", summary["published_average"] == 282737
                   and saved["versions"][0]["published_average"] == "282737"))
    checks.append(("P2a 변동률 분포와 이상치", sum(summary["change_distribution"].values()) == 108
                   and summary["outliers_abs_over_10_percent"] == [
                       {"code": "3007", "name": "한식와공", "percent": "12.24"}]))
    expected_h2 = {"1013": "276285", "1003": "228717", "1007": "275379", "1002": "172698"}
    checks.append(("P3 현장 직종 4개 PDF 10쪽", all(
        saved["versions"][0]["rates"][code]["daily"] == value
        and saved["versions"][0]["rates"][code]["pdf_page"] == 10
        for code, value in expected_h2.items())))
    checks.append(("P4 적용 기간", select_rate_version("2026-06-01")["id"] == "2026H1"
                   and select_rate_version("2026-10-01")["id"] == "2026H2"
                   and select_rate_version("2025-12-01") is None))

    rule = json.loads((ROOT / "agent/rules/common/1-2-2_amount_units.json").read_text(encoding="utf-8"))
    with pymupdf.open(ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf") as pdf:
        source = pdf[61].get_text("text")
    amounts = {item["item"]: item["truncate_below"] for item in rule["rules"]}
    checks.append(("P5 1-2-2 원문 자리와 소액 예외", amounts == {
        "설계서의 총액": "1000", "설계서의 소계": "1", "설계서의 금액란": "1",
        "일위대가표의 계금": "1", "일위대가표의 금액란": "0.1",
    } and rule["small_amount_exception"]["quote"] in source))

    spec = json.loads((ROOT / "agent/rules/specs/common/6-1-4_pump.json").read_text(encoding="utf-8"))
    cases = json.loads((ROOT / "evals/cases/common_6-1-4_pump.json").read_text(encoding="utf-8"))
    units = adjusted_daily_crew(spec, cases["cases"][0]["input"])["unit_lines"]
    priced = price_unit(spec, units, select_rate_version("2026-06-01"))
    lines = {line["name"]: line for line in priced["lines"]}
    expected_lines = {
        "콘크리트공": ("273540", "8425.032", "8425.0"),
        "특별인부": ("226122", "1741.1394", "1741.1"),
        "형틀목공": ("275790", "2123.583", "2123.5"),
        "보통인부": ("172068", "1324.9236", "1324.9"),
    }
    checks.append(("P6 상반기 손계산 4개 노무 줄", all(
        (lines[name]["unit_price"], lines[name]["amount_exact"], lines[name]["amount"]) == values
        for name, values in expected_lines.items())))
    costs = {item["name"]: item for item in priced["cost_lines"]}
    checks.append(("P7 두 5% 비용", priced["labor_subtotal"] == "13614.5"
                   and len(costs) == 2 and all(item["amount_exact"] == "680.725"
                                                   and item["amount"] == "680.7" for item in costs.values())
                   and {item["category"] for item in costs.values()} == {"경비", "재료비"}))
    checks.append(("P8 미산정 제외 부분 계금", priced["total_exact"] == "14975.9"
                   and priced["unit_prices"] == {"재료비": "680", "노무비": "13614", "경비": "680"}
                   and priced["total"] == "14974" and priced["partial"]
                   and priced["status"] == "PARTIAL"
                   and lines["콘크리트펌프차"]["amount"] is None
                   and any("레미콘" in item["name"] for item in priced["unpriced"])))
    checks.append(("P9 각 산정 금액의 인용", all(
        any("노임단가" == citation["item"] for citation in line["citations"])
        and any(citation["section_no"] == "1-2-2" for citation in line["citations"])
        for line in lines.values() if line["kind"] == "labor")
        and all(any(citation["item"].startswith("[주]") for citation in cost["citations"])
                for cost in costs.values())))

    missing_version = price_unit(spec, units, None)
    checks.append(("P10 적용 버전 없음은 0원이 아님", missing_version["total"] is None
                   and missing_version["labor_subtotal"] is None
                   and all(line["amount"] is None for line in missing_version["lines"])))
    missing_wage = copy.deepcopy(select_rate_version("2026-06-01"))
    missing_wage["rates"]["1013"]["daily"] = None
    incomplete = price_unit(spec, units, missing_wage)
    checks.append(("P11 빠진 직종 단가 미산정", next(
        line for line in incomplete["lines"] if line["name"] == "콘크리트공")["amount"] is None
                   and all(item["amount"] is None for item in incomplete["cost_lines"])))

    case_input = cases["cases"][0]["input"]
    reference_case = price_unit(spec, adjusted_daily_crew(spec, case_input)["unit_lines"],
                                select_rate_version("2026-10-01"), case_input, "2026-10-01")
    checks.append(("P11a 재료비·노무비·경비별 원 미만 버림 및 참고 금액",
                   reference_case["unit_prices"] == {"재료비": "686", "노무비": "15898", "경비": "5150"}
                   and reference_case["total"] == "21734"
                   and reference_case["reference_amounts"] == {
                       "volume": "260",
                       "subtotals": {"재료비": "178360", "노무비": "4133480", "경비": "1339000"},
                       "total": "5650840"}))

    allowance_data = json.loads((ROOT / "data/rates/material_allowance.json").read_text(encoding="utf-8"))
    allowances = {(row["material"], row["structure"]): row for row in allowance_data["rules"]}
    checks.append(("P11b 품셈 1-3-1 재료 할증률 6개와 출처",
                   len(allowances) == 6
                   and {key: row["allowance"] for key, row in allowances.items()} == {
                       ("레디믹스트 콘크리트 타설(현장플랜트 포함)", "무근"): "0.02",
                       ("레디믹스트 콘크리트 타설(현장플랜트 포함)", "철근"): "0.01",
                       ("레디믹스트 콘크리트 타설(현장플랜트 포함)", "철골"): "0.01",
                       ("현장 혼합 콘크리트 타설(인력 및 믹서)", "무근"): "0.03",
                       ("현장 혼합 콘크리트 타설(인력 및 믹서)", "철근"): "0.02",
                       ("현장 혼합 콘크리트 타설(인력 및 믹서)", "소형"): "0.05",
                   }
                   and all(row["source"]["section_no"] == "1-3-1"
                           and row["source"]["pdf_page"] == 78
                           and row["source"]["printed_page"] == 22
                           and row["source"]["item"] == "8. 기타재료"
                           and row["source"]["row"] and row["source"]["value"] for row in allowances.values())))
    parsed_prices = [extract_inputs(query, spec)[0].get("ready_mix_price") for query in
                     ("레미콘 9만원", "㎥당 90,000원", "모름")]
    checks.append(("P11c 사급 레미콘 단가 입력 규칙", parsed_prices == ["90000", "90000", "모름"]))

    sagup_inputs = {**case_input, "concrete_supply": "사급", "ready_mix_price": "90000"}
    sagup = price_unit(spec, units, select_rate_version("2026-10-01"), sagup_inputs, "2026-10-01")
    ready_mix = next(line for line in sagup["supply_lines"] if line["name"] == "레미콘(사급)")
    checks.append(("P11d 사급 레미콘 입력 단가와 1% 할증",
                   ready_mix["status"] == "산정" and ready_mix["quantity"] == "1.01"
                   and ready_mix["unit_price"] == "90000" and ready_mix["amount_exact"] == "90900"
                   and ready_mix["amount"] == "90900.0"
                   and any(citation.get("internal_id") == "p78" for citation in ready_mix["citations"])
                   and any(citation.get("item") == "사용자 입력 단가" and citation.get("quote")
                           and "입력 시각" in citation["quote"] for citation in ready_mix["citations"])
                   and sagup["unit_prices"] == {"재료비": "91586", "노무비": "15898", "경비": "5150"}
                   and sagup["total"] == "112634"
                   and sagup["reference_amounts"] == {
                       "volume": "260",
                       "subtotals": {"재료비": "23812360", "노무비": "4133480", "경비": "1339000"},
                       "total": "29284840"}))
    unknown_inputs = {**case_input, "concrete_supply": "사급", "ready_mix_price": "모름"}
    unknown_price = price_unit(spec, units, select_rate_version("2026-10-01"),
                               unknown_inputs, "2026-10-01")
    unknown_mix = next(line for line in unknown_price["supply_lines"] if "레미콘" in line["name"])
    checks.append(("P11e 사급 단가 모름은 미산정",
                   unknown_mix["status"] == "미산정" and unknown_mix["amount"] is None
                   and unknown_mix["reason"] == "사급 레미콘 단가 미입력"
                   and unknown_price["unit_prices"] == {"재료비": "686", "노무비": "15898", "경비": "5150"}
                   and unknown_price["total"] == "21734"
                   and any("사급 레미콘 단가 미입력" == item["reason"]
                           for item in unknown_price["unpriced"])))

    client = TestClient(app)
    question = "철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"
    answers = {"pump_size": "32m", "slump_band": "15㎝", "facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ",
               "placement": "붐", "vibrator_used": True, "reset_status": "없음", "concrete_supply": "관급",
               "work_category": "기타 토목공사", "duration": "1~6개월", "contractor_type": "종합건설업",
               "project_scale": "이 견적만"}
    first = client.post("/api/chat", json={"message": question}).json()
    response = client.post("/api/chat", json={"thread_id": first["thread_id"], "answers": answers}).json()
    checks.append(("P12 기본 API 최신 하반기·부분 상태", response["status"] == "PARTIAL"
                   and response["priced"]["rate_version"]["id"] == "2026H2"
                   and all(line["citations"] for line in response["priced"]["lines"])
                   and response["priced"]["partial"]))
    first_h1 = client.post("/api/chat", json={"message": question, "basis_date": "2026-06-01"}).json()
    h1 = client.post("/api/chat", json={"thread_id": first_h1["thread_id"], "answers": answers}).json()
    checks.append(("P13 API 기준일 상반기", h1["priced"]["rate_version"]["id"] == "2026H1"
                   and h1["priced"]["total_exact"] == "21618.6"
                   and h1["priced"]["total"] == "21617"))
    first_old = client.post("/api/chat", json={"message": question, "basis_date": "2025-12-01"}).json()
    old = client.post("/api/chat", json={"thread_id": first_old["thread_id"], "answers": answers}).json()
    checks.append(("P14 API 적용 기간 없음", old["status"] == "PARTIAL"
                   and old["priced"]["rate_version"] is None
                   and old["priced"]["total"] is None
                   and "적용 가능한 노임단가 없음" in old["message"]))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
