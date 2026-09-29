"""오프라인으로 채팅 API의 상태 전환과 thread_id 규칙을 검사한다."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["AGENT_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

CLIENT = TestClient(app)

PUMP_ANSWERS = {"pump_size": "32m", "slump_band": "15㎝", "facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ",
                "placement": "붐", "vibrator_used": True, "reset_status": "없음", "concrete_supply": "관급",
                "work_category": "기타 토목공사", "duration": "1~6개월", "contractor_type": "종합건설업",
                "project_scale": "이 견적만"}


def main() -> int:
    checks = []

    outside = CLIENT.post("/api/chat", json={"message": "오늘 현장 날씨 어때?"}).json()
    checks.append(("A1", outside["status"] == "OUT_OF_SCOPE" and not outside["questions"]))

    evidence = CLIENT.post("/api/chat", json={"message": "합판거푸집 설치 인건비"}).json()
    checks.append(("A2", evidence["status"] == "EVIDENCE_ONLY" and len(evidence["evidence"]) == 3))

    missing = CLIENT.post("/api/chat", json={"message": "철근콘크리트 벽체 260㎥ 펌프차로 타설 비용",
                                              "basis_date": "2026-10-01"}).json()
    thread_id = missing["thread_id"]
    checks.append(("A3", missing["status"] == "MISSING_INFO" and len(missing["questions"]) == 8
                   and missing["work"]["section_no"] == "6-1-4"))

    computed = CLIENT.post("/api/chat", json={"thread_id": thread_id, "answers": PUMP_ANSWERS}).json()
    computed_lines = {line["name"]: line for line in computed.get("result", {}).get("lines", [])}
    checks.append(("A4", computed["status"] == "PARTIAL" and len(computed["inputs"]) == 14
                   and all(item["source"] in ("질문", "답변", "선택", "기본값") for item in computed["inputs"])
                   and computed_lines.get("콘크리트공", {}).get("value") == "8"
                   and computed_lines.get("콘크리트펌프차", {}).get("kind") == "equipment"
                   and computed_lines.get("콘크리트펌프차", {}).get("value") == "2"
                   and computed["result"]["review_status"] == "미완료"
                   and computed["statement"]["totals"] == {
                       "materials": 178360, "labor": 4922974, "expenses": 2263523,
                       "net_cost": 7364857, "management": 589188, "profit": 1166352,
                       "total_cost": 9120397, "vat": 912039, "contract_amount": 10032436
                   }))

    reused = CLIENT.post("/api/chat", json={"thread_id": thread_id, "message": "새 질문"}).json()
    checks.append(("A5", reused["thread_id"] != thread_id))

    health = CLIENT.get("/api/health").json()
    checks.append(("A6", health == {"status": "ok"}))

    blocked_start = CLIENT.post("/api/chat", json={"message": "철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"}).json()
    blocked_answers = {**PUMP_ANSWERS, "reset_status": "있음"}
    blocked = CLIENT.post("/api/chat", json={"thread_id": blocked_start["thread_id"], "answers": blocked_answers}).json()
    checks.append(("A7", blocked["status"] == "BLOCKED" and blocked["result"]["input"] == "reset_status"
                   and bool(blocked["result"]["source"]) and blocked["message"] == blocked["result"]["reason"]))

    unit_lines = {line["name"]: line for line in computed["result"].get("unit_lines", [])}
    checks.append(("A8", computed["result"].get("unit_basis", {}).get("per") == "1㎥"
                   and computed["result"]["unit_basis"]["places"] == 4
                   and unit_lines.get("콘크리트공", {}).get("applied") == "0.0308"
                   and unit_lines.get("콘크리트펌프차", {}).get("exact") == "4/65"
                   and computed_lines["콘크리트공"]["value"] == "8"))

    checks.append(("A9 응답에 llm_info 포함",
                   computed.get("llm_info", {}).get("provider") == "vertex"
                   and computed["llm_info"].get("model") == "gemini-3.5-flash-lite"
                   and computed["llm_info"].get("attempts") == 0
                   and "VERTEX_API_KEY" not in str(computed["llm_info"])))

    # 조건 없이 계산: 기본값으로 바로 도급액이 나온다.
    start = CLIENT.post("/api/chat", json={"message": "철근콘크리트 벽체 260㎥ 펌프차로 타설 비용",
                                             "basis_date": "2026-10-01"}).json()
    answers = {k: v for k, v in PUMP_ANSWERS.items()
               if k not in ("work_category", "duration", "contractor_type", "project_scale")}
    base = CLIENT.post("/api/chat", json={"thread_id": start["thread_id"], "answers": answers}).json()
    condition_sources = {c["name"]: c["source"] for c in base["conditions"]}
    checks.append(("A10 기본값 도급액", base["status"] == "PARTIAL"
                   and base["statement"]["totals"]["contract_amount"] == 10032436
                   and set(condition_sources.values()) == {"기본값"}
                   and base["conditions"][0]["group"] == "토목"
                   and bool(base["conditions"][0]["help"]["기타 토목공사"])))

    exported = CLIENT.get(f"/api/export/{base['thread_id']}.xlsx")  # 조건을 바꾸기 전 상태
    changed = CLIENT.post("/api/chat", json={"thread_id": base["thread_id"], "conditions": {
        "work_category": "주택 외 건축", "duration": "13~36개월", "contractor_type": "전문건설업"}}).json()
    changed_sources = {c["name"]: c["source"] for c in changed["conditions"]}
    checks.append(("A11 조건 바꾸기", changed["statement"]["totals"]["contract_amount"] == 9947033
                   and changed["status"] == "PARTIAL" and changed_sources["duration"] == "선택"
                   and changed_sources["project_scale"] == "기본값"
                   and changed["result"] == base["result"]
                   and any(i["name"] == "volume" and i["value"] == "260" for i in changed["inputs"])))
    group_only = CLIENT.post("/api/chat", json={"thread_id": base["thread_id"],
                                                  "conditions": {"group": "건축"}}).json()
    bad = CLIENT.post("/api/chat", json={"thread_id": base["thread_id"],
                                           "conditions": {"duration": "없는 기간"}})
    checks.append(("A12 묶음만 바꾸기·잘못된 값", group_only["conditions"][0]["value"] == "주택 외 건축"
                   and bad.status_code == 422 and CLIENT.post("/api/chat", json={
                       "thread_id": "nothing", "conditions": {"duration": "1~6개월"}}).status_code == 404))

    from io import BytesIO
    from openpyxl import load_workbook
    book = load_workbook(BytesIO(exported.content))
    first = book["원가계산서"] if "원가계산서" in book.sheetnames else None
    cost_rows = list(first.iter_rows(values_only=True)) if first else []
    cost_header = next((row for row in cost_rows if row[0] == "비목"), None)
    contract = next((row for row in cost_rows if row[0] == "도급액"), None)
    net_cost = next((row for row in cost_rows if row[0] == "순공사원가"), None)
    excluded_rows = [row for row in cost_rows if isinstance(row[4], str) and row[4].startswith("제외 ·")]
    footer_present = any(isinstance(cell.value, str) and "검토 전 참고용" in cell.value
                         for row in first.iter_rows() for cell in row) if first else False
    checks.append(("A13 엑셀 시트·열", exported.status_code == 200
                   and len(book.sheetnames) == 5
                   and book.sheetnames == ["원가계산서", "내역서", "일위대가", "단가대비표", "산출근거"]
                   and cost_header is not None and footer_present
                   and CLIENT.get("/api/export/nothing.xlsx").status_code == 404))
    checks.append(("A14 원가계산서 고정 셀", contract is not None and contract[2] == 10032436
                   and net_cost is not None and net_cost[2] == 7364857))
    checks.append(("A15 제외 줄 열 정렬", bool(excluded_rows)
                   and all(row[2] is None and row[4].startswith("제외 ·") for row in excluded_rows)
                   and all(len(row) == 5 for row in cost_rows)))
    unit_sheet = book["일위대가"] if "일위대가" in book.sheetnames else None
    unit_values = list(unit_sheet.iter_rows(values_only=True)) if unit_sheet else []
    unit_headers = next((row for row in unit_values if row[4] == "계"), None)
    unit_title = next((row for row in unit_values if isinstance(row[0], str)
                       and row[0].startswith("제 1호표 ")), None)
    checks.append(("A16 일위대가 호표 합계·열순서", unit_headers is not None and unit_title is not None
                   and unit_title[5] == 21734 and unit_headers.index("노무비") < unit_headers.index("재료비")))

    from urllib.parse import unquote
    disposition = exported.headers.get("content-disposition", "")
    encoded_name = disposition.partition("filename*=UTF-8''")[2]
    decoded_name = unquote(encoded_name)
    checks.append(("A17 공종명 파일명 헤더", 'filename="estimate.xlsx"; filename*=UTF-8\'\'' in disposition
                   and decoded_name.endswith("_견적서.xlsx")
                   and "/" not in decoded_name and "\\" not in decoded_name))

    bill_sheet = book["내역서"]
    bill_numeric = all(cell.value is None or isinstance(cell.value, (int, float))
                       for row in bill_sheet.iter_rows(min_row=6, min_col=5, max_col=12)
                       for cell in row)
    rate_sheet = book["단가대비표"]
    rate_numeric = all(cell.value is None or isinstance(cell.value, (int, float)) or cell.value == "-"
                       for row in rate_sheet.iter_rows(min_row=5, min_col=5, max_col=5)
                       for cell in row)
    basis_sheet = book["산출근거"]
    basis_numeric = all(cell.value is None or isinstance(cell.value, (int, float))
                        or cell.value in ("미산정", "제외")
                        for row in basis_sheet.iter_rows(min_row=5, min_col=2, max_col=2)
                        for cell in row)
    checks.append(("A18 수량·금액 숫자 셀", bill_numeric and rate_numeric and basis_numeric))

    bill_values = list(bill_sheet.iter_rows(values_only=True))
    bill_total = next((row for row in bill_values if row[0] == "합계"), None)
    checks.append(("A19 내역서 합계 금액 칸", bill_total is not None
                   and [bill_total[index] for index in (4, 6, 8, 10)] == [None, None, None, None]
                   and [bill_total[index] for index in (5, 7, 9, 11)] == [178360, 4133480, 1339000, 5650840]))

    missing_title_row = next((index for index, row in enumerate(cost_rows) if row[0] == "빠진 항목"), None)
    rate_title_row = next((index for index, row in enumerate(cost_rows) if row[0] == "적용 요율 출처"), None)
    missing_items = set()
    missing_rows = []
    if missing_title_row is not None:
        missing_end = rate_title_row if rate_title_row is not None else len(cost_rows)
        missing_rows = [row for row in cost_rows[missing_title_row + 2:missing_end] if row[0]]
        missing_items = {row[0] for row in missing_rows}
    checks.append(("A20 원가계산서 빠진 항목 분리", contract is not None and missing_title_row is not None
                   and missing_title_row > cost_rows.index(contract)
                   and all(not row[0] for row in cost_rows[cost_rows.index(contract) + 1:missing_title_row])
                   and any("1-2-9" in item for item in missing_items)
                   and any("살수 양생" in item for item in missing_items)
                   and all(any(expected in item for item in missing_items) for expected in
                           ("레미콘", "펌프차 연료", "퇴직공제", "산업안전보건관리비",
                            "공사이행보증", "건설기계대여대금"))))

    contract_row = cost_rows.index(contract) + 1 if contract else 0
    checks.append(("A21 원가계산서 요약 행 병합", contract_row > 0
                   and f"A{contract_row}:B{contract_row}" in {str(rng) for rng in first.merged_cells.ranges}
                   and "-" in next((row[2] for row in cost_rows if row[1] == "간접재료비(-)"), None)))

    metadata_ok = all(sheet["A2"].value.startswith("공사명:") and sheet["A3"].value.startswith("기준일:")
                      for sheet in book.worksheets)
    checks.append(("A22 시트 공통 메타데이터", metadata_ok
                   and "금액 0.1원 미만 버림(품셈 1-2-2)" in [cell.value for row in unit_sheet.iter_rows() for cell in row]))
    labor_rows = [row for row in unit_sheet.iter_rows(min_row=6)
                  if isinstance(row[12].value, str) and "노임 코드" in row[12].value]
    driver_rows = [row for row in unit_sheet.iter_rows(min_row=6) if row[0].value == "펌프차 운전원"]
    driver_pay = [cell for row in driver_rows for cell in row[4:12] if cell.value == 35415.375]
    checks.append(("A23 일위대가 인력 규격·운전원 노임", bool(labor_rows) and bool(driver_pay)
                   and all(row[1].value in (None, "") for row in labor_rows)
                   and driver_pay[0].number_format == "#,##0.0"
                   and "일 283,323원 ÷ 8시간" in driver_rows[0][12].value))

    all_cells = [cell.value for sheet in book.worksheets for row in sheet.iter_rows() for cell in row]
    checks.append(("A24 내부 데이터 경로 비노출", not any(isinstance(value, str) and "data/raw/" in value
                                                        for value in all_cells)))

    rate_values = list(rate_sheet.iter_rows(values_only=True))
    driver_rate = next((row for row in rate_values if row[1] == "펌프차 운전원"), None)
    supplied = next((row for row in rate_values if row[0] == "자재"), None)
    wage_rows = [row for row in rate_values[4:] if row[0] == "노임"]
    machine_rows = [row for row in rate_values[4:] if row[0] == "기계경비"]
    checks.append(("A25 단가대비표 실무 열과 단가", rate_values[3] ==
                   ("구분", "품명", "규격", "단위", "적용 단가", "단가 근거", "적용 기간", "비고")
                   and driver_rate is not None and driver_rate[3] == "원/인" and driver_rate[4] == 283323
                   and "35,415.4원" in driver_rate[7]
                   and bool(wage_rows) and all(row[2] in (None, "") and row[3] == "원/인" for row in wage_rows)
                   and bool(machine_rows) and all(row[3] == "원/hr" for row in machine_rows)
                   and supplied is not None and supplied[4] == "-" and supplied[7] == "관급(발주처 지급)"
                   and all(row[0] != "제비율" for row in rate_values[4:])))

    basis_values = list(basis_sheet.iter_rows(values_only=True))
    checks.append(("A26 산출근거 범위와 적용 기준", not any(value in ("간접노무비", "산재보험료")
                   for row in basis_values for value in row)
                   and any(row[0] == "공구손료 및 경장비 기준액 (원)" and row[1] == 4922974
                           and "× 5%" in row[2] for row in basis_values)
                   and sum(row[0] == "적용 기준" for row in basis_values) == 1
                   and any(row[0] == "공사 규모 판정" for row in basis_values)
                   and any(row[0] == "안전관리비 기초액" for row in basis_values)))

    source_rows = []
    source_headers = None
    if rate_title_row is not None:
        source_headers = cost_rows[rate_title_row + 1]
        for row in cost_rows[rate_title_row + 2:]:
            if row[0] == "표준품셈 기준 금액 · 검토 전 참고용 · 품셈AI":
                break
            if row[0]:
                source_rows.append(row)
    source_names = {row[0] for row in source_rows}
    indirect = next((row for row in source_rows if row[0] == "간접노무비"), None)
    profit_rate = next((row for row in source_rows if row[0] == "이윤"), None)
    vat_row = next((row for row in source_rows if row[0] == "부가가치세"), None)
    checks.append(("A27 적용 요율 출처의 실제 적용 행", source_headers is not None
                   and source_headers[:4] == ("항목", "요율", "적용 구간", "출처")
                   and indirect is not None and indirect[1] == "19.1%"
                   and indirect[2] == "10억 미만·6개월 이하"
                   and indirect[3] == "조달청 제비율 2026.4.13., 토목"
                   and profit_rate is not None and profit_rate[2] == "50억 미만"
                   and vat_row is not None and vat_row[1] == "10%" and vat_row[3] == "부가가치세법"
                   and {"노임", "기계경비"} <= source_names
                   and not any(any(term in name for term in ("레미콘", "연료", "1-2-9", "살수 양생"))
                               for name in source_names)))

    missing_by_name = {row[0]: row[2] for row in missing_rows}
    reasons_ok = (any("레미콘" in name and "관급" in reason for name, reason in missing_by_name.items())
                  and any("연료" in name and "8-1-7" in reason for name, reason in missing_by_name.items())
                  and any("1-2-9" in name and "이번 계산 범위 밖" in reason
                          for name, reason in missing_by_name.items())
                  and any("살수 양생" in name and "6-1-4 사." in reason
                          for name, reason in missing_by_name.items()))
    checks.append(("A28 빠진 항목별 실제 근거", reasons_ok))
    required_reasons = (("퇴직공제", "추정금액 1억 미만"),
                        ("산업안전보건관리비", "총 공사금액 2천만원 미만"),
                        ("공사이행보증", "지방계약법 시행령 제51조"),
                        ("건설기계대여대금", "산정 방법 확인 필요"))
    reasons_present = all(any(keyword in name and token in reason
                              for name, reason in missing_by_name.items())
                          for keyword, token in required_reasons)
    checks.append(("A29 제외·미산정 사유", reasons_present))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    if not all(passed for _, passed in checks):
        print("A3:", missing)
        print("A4:", computed)
        print("A7:", blocked)
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
