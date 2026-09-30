"""원가계산서 조건별 금액, 제외 사유, 적용 기준일을 고정 정답과 대조한다."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.tools.calc.cost_statement import calculate_cost_statement  # noqa: E402


PRICED = {
    "reference_amounts": {
        "subtotals": {"재료비": 178360, "노무비": 4133480, "경비": 1339000},
        "total": 5650840,
        "volume": 260,
    },
    "rate_version": {"id": "2026"},
    "unpriced": [{"name": "연료비", "reason": "단가 없음"}],
}
BASE_INPUTS = {
    "work_category": "기타 토목공사",
    "duration": "1~6개월",
    "contractor_type": "종합건설업",
    "project_scale": "이 견적만",
}

# 명세의 원 미만 버림 정답. 계산 결과로 기대값을 만들지 않는다.
BASE_LINES = {
    "재료비": (178360, "산정"), "직접노무비": (4133480, "산정"),
    "직접경비": (1339000, "산정"), "간접노무비": (789494, "산정"),
    "노무비 계": (4922974, "산정"), "산재보험료": (175257, "산정"),
    "고용보험료": (49722, "산정"), "건강보험료": (148598, "산정"),
    "노인장기요양보험료": (19525, "산정"), "연금보험료": (196340, "산정"),
    "환경보전비": (45206, "산정"), "기타경비": (280573, "산정"),
    "하도급대금 지급보증 수수료": (4577, "산정"),
    "석면분담금": (295, "산정"), "임금채권부담금": (4430, "산정"),
    "퇴직공제부금비": (0, "제외"), "산업안전보건관리비": (0, "제외"),
    "경비 계": (2263523, "산정"), "순공사원가": (7364857, "산정"),
    "일반관리비": (589188, "산정"), "이윤": (1166352, "산정"),
    "총원가": (9120397, "산정"), "부가가치세": (912039, "산정"),
    "도급액": (10032436, "산정"), "공사이행보증": (0, "제외"),
    "연료비": (None, "미산정"),
    "건설기계대여대금 지급보증 수수료": (None, "미산정"),
}
BASE_TOTALS = {
    "materials": 178360, "labor": 4922974, "expenses": 2263523,
    "net_cost": 7364857, "management": 589188, "profit": 1166352,
    "total_cost": 9120397, "vat": 912039, "contract_amount": 10032436,
}
CASES = {
    "C1": ({}, {}, BASE_TOTALS),
    "C2": (
        {"work_category": "주택 외 건축", "duration": "13~36개월", "contractor_type": "전문건설업"},
        {"간접노무비": (752293, "산정"), "노무비 계": (4885773, "산정"),
         "산재보험료": (173933, "산정"), "고용보험료": (49346, "산정"),
         "환경보전비": (28254, "산정"), "기타경비": (278527, "산정"),
         "하도급대금 지급보증 수수료": (0, "제외"),
         "석면분담금": (293, "산정"), "임금채권부담금": (4397, "산정"),
         "경비 계": (2238213, "산정"), "순공사원가": (7302346, "산정"),
         "일반관리비": (584187, "산정"), "이윤": (1156225, "산정"),
         "총원가": (9042758, "산정"), "부가가치세": (904275, "산정"),
         "도급액": (9947033, "산정")},
        {"materials": 178360, "labor": 4885773, "expenses": 2238213,
         "net_cost": 7302346, "management": 584187, "profit": 1156225,
         "total_cost": 9042758, "vat": 904275, "contract_amount": 9947033},
    ),
    "C3": (
        {"project_scale": "3000000000"},
        {"간접노무비": (781227, "산정"), "노무비 계": (4914707, "산정"),
         "산재보험료": (174963, "산정"), "고용보험료": (49638, "산정"),
         "기타경비": (295397, "산정"), "석면분담금": (294, "산정"),
         "임금채권부담금": (4423, "산정"), "퇴직공제부금비": (95070, "산정"),
         "산업안전보건관리비": (109089, "산정"),
         "경비 계": (2482120, "산정"), "순공사원가": (7575187, "산정"),
         "일반관리비": (606014, "산정"), "이윤": (1200426, "산정"),
         "총원가": (9381627, "산정"), "부가가치세": (938162, "산정"),
         "도급액": (10319789, "산정")},
        {"materials": 178360, "labor": 4914707, "expenses": 2482120,
         "net_cost": 7575187, "management": 606014, "profit": 1200426,
         "total_cost": 9381627, "vat": 938162, "contract_amount": 10319789},
    ),
    "C4": (
        {"duration": "1개월 미만"},
        {"건강보험료": (0, "제외"), "노인장기요양보험료": (0, "제외"),
         "연금보험료": (0, "제외"), "경비 계": (1899060, "산정"),
         "순공사원가": (7000394, "산정"), "일반관리비": (560031, "산정"),
         "이윤": (1107309, "산정"), "총원가": (8667734, "산정"),
         "부가가치세": (866773, "산정"), "도급액": (9534507, "산정")},
        {"materials": 178360, "labor": 4922974, "expenses": 1899060,
         "net_cost": 7000394, "management": 560031, "profit": 1107309,
         "total_cost": 8667734, "vat": 866773, "contract_amount": 9534507},
    ),
}


def check_case(name: str, changes: dict, changed_lines: dict, totals: dict) -> list[str]:
    statement = calculate_cost_statement(PRICED, {**BASE_INPUTS, **changes}, "2026-10-01")
    failures = []
    actual_lines = {line["name"]: line for line in statement["lines"]}
    expected_lines = {**BASE_LINES, **changed_lines}
    if len(actual_lines) != len(statement["lines"]) or set(actual_lines) != set(expected_lines):
        failures.append(f"{name}: 줄 이름 누락·중복·추가: {set(actual_lines) ^ set(expected_lines)}")
    for line_name, expected in expected_lines.items():
        row = actual_lines.get(line_name)
        if row is None or (row["amount"], row["status"]) != expected:
            failures.append(f"{name} {line_name}: 기대 {expected}, 실제 {row}")
        elif row["status"] != "산정" and not row["reason"]:
            failures.append(f"{name} {line_name}: 제외·미산정 사유 없음")
    if statement["totals"] != totals:
        failures.append(f"{name} 합계: 기대 {totals}, 실제 {statement['totals']}")
    if statement["status"] != "PARTIAL":
        failures.append(f"{name}: 연료비 미산정 시 PARTIAL이어야 함")
    if name == "C2" and actual_lines["하도급대금 지급보증 수수료"]["reason"] != "적용제외: 전문공사":
        failures.append("C2: 전문공사 제외 사유 불일치")
    if name == "C3" and actual_lines["산업안전보건관리비"]["note"] != "기초액은 전체 공사에 1회 계상 — 부분 견적에서 제외(간이)":
        failures.append("C3: 안전관리비 기초액 주석 불일치")
    if name == "C4":
        reason = "공사기간 1개월 미만 — 원문: 공사기간 1개월(30일) 이상 모든 건설공사"
        for item in ("건강보험료", "노인장기요양보험료", "연금보험료"):
            if actual_lines[item]["reason"] != reason:
                failures.append(f"C4 {item}: 기간 제외 사유 불일치")
    return failures


def main() -> int:
    checks = []
    for name, (changes, lines, totals) in CASES.items():
        failures = check_case(name, changes, lines, totals)
        checks.append((name, failures))

    for day, version, rate in (("2026-04-13", "260413", "19.1"),
                               ("2026-04-12", "260101", "16.5")):
        statement = calculate_cost_statement(PRICED, BASE_INPUTS, day)
        indirect = next(line for line in statement["lines"] if line["name"] == "간접노무비")
        failures = [] if (statement["overhead_version"]["id"] == version and indirect["rate"] == rate) else [
            f"{day}: 기대 판 {version}, 간접노무비 {rate}%; 실제 {statement['overhead_version']}, {indirect['rate']}%"]
        checks.append((day, failures))
    old = calculate_cost_statement(PRICED, BASE_INPUTS, "2025-12-31")
    checks.append(("2025-12-31", [] if old["status"] == "UNCALCULATED" and not old["lines"] else
                   [f"2025-12-31: 기대 UNCALCULATED, 실제 {old['status']} / {old['lines']}"]))

    sagup_priced = {
        **PRICED,
        "reference_amounts": {
            "subtotals": {"재료비": 23812360, "노무비": 4133480, "경비": 1339000},
            "total": 29284840,
            "volume": 260,
        },
    }
    sagup = calculate_cost_statement(sagup_priced, BASE_INPUTS, "2026-10-01")
    sagup_lines = {line["name"]: line for line in sagup["lines"]}
    sagup_expected = {
        "재료비": (23812360, "산정"), "간접노무비": (789494, "산정"),
        "노무비 계": (4922974, "산정"), "산재보험료": (175257, "산정"),
        "고용보험료": (49722, "산정"), "건강보험료": (148598, "산정"),
        "노인장기요양보험료": (19525, "산정"), "연금보험료": (196340, "산정"),
        "산업안전보건관리비": (880293, "산정"), "환경보전비": (234278, "산정"),
        "기타경비": (1580443, "산정"), "하도급대금 지급보증 수수료": (23720, "산정"),
        "석면분담금": (295, "산정"), "임금채권부담금": (4430, "산정"),
        "퇴직공제부금비": (0, "제외"), "경비 계": (4651901, "산정"),
        "순공사원가": (33387235, "산정"), "일반관리비": (2670978, "산정"),
        "이윤": (1836877, "산정"), "총원가": (37895090, "산정"),
        "부가가치세": (3789509, "산정"), "도급액": (41684599, "산정"),
    }
    sagup_totals = {
        "materials": 23812360, "labor": 4922974, "expenses": 4651901,
        "net_cost": 33387235, "management": 2670978, "profit": 1836877,
        "total_cost": 37895090, "vat": 3789509, "contract_amount": 41684599,
    }
    osafety = sagup_lines.get("산업안전보건관리비", {})
    sagup_ok = (all((sagup_lines.get(name) or {}).get("amount") == amount
                    and (sagup_lines.get(name) or {}).get("status") == status
                    for name, (amount, status) in sagup_expected.items())
                and sagup["totals"] == sagup_totals
                and osafety.get("base_amount") == 27945840
                and osafety.get("rate") == "3.15"
                and osafety.get("reason") is None)
    sagup_mismatches = {name: ((sagup_lines.get(name) or {}).get("amount"),
                               (sagup_lines.get(name) or {}).get("status"), amount, status)
                        for name, (amount, status) in sagup_expected.items()
                        if (sagup_lines.get(name) or {}).get("amount") != amount
                        or (sagup_lines.get(name) or {}).get("status") != status}
    checks.append(("사급 레미콘 입력 단가 원가계산서 정답", [] if sagup_ok else
                   [f"불일치 {sagup_mismatches}; 기대 {sagup_totals}, 실제 {sagup.get('totals')}; OSH {osafety}"]))

    for name, failures in checks:
        print(f"{'PASS' if not failures else 'FAIL'} {name}")
        for failure in failures:
            print(f"  {failure}")
    passed = sum(not failures for _, failures in checks)
    print(f"통과 {passed} / 전체 {len(checks)}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
