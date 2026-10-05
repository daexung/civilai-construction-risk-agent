"""Deterministic construction cost statement from priced unit work and public rates."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, ROUND_DOWN
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RATES = ROOT / "data/rates/overhead_rates.json"


@lru_cache(maxsize=1)
def _rates() -> dict:
    return json.loads(RATES.read_text(encoding="utf-8"))


def _won(value: Decimal | int) -> int:
    return int(Decimal(value).to_integral_value(rounding=ROUND_DOWN))


def _rate_amount(base: int, rate: str, divisor: int = 100) -> int:
    return _won(Decimal(base) * Decimal(rate) / Decimal(divisor))


def _version_for(basis_date: str | date) -> tuple[str | None, dict | None]:
    day = date.fromisoformat(basis_date) if isinstance(basis_date, str) else basis_date
    entries = _rates()["versions"]
    eligible = [(key, value) for key, value in entries.items()
                if date.fromisoformat(value["effective_from"]) <= day]
    return max(eligible, key=lambda pair: pair[1]["effective_from"]) if eligible else (None, None)


def _threshold_scale(value: int, upper_bounds: list[int], labels: list[str]) -> str:
    for upper, label in zip(upper_bounds, labels):
        if value < upper:
            return label
    return labels[-1]


def _pick(items: list[dict], **criteria) -> dict:
    return next(item for item in items if all(item.get(key) == value for key, value in criteria.items()))


def calculate_cost_statement(priced: dict, inputs: dict, basis_date: str | date) -> dict:
    version_id, version = _version_for(basis_date)
    conditions = {key: inputs.get(key) for key in
                  ("work_category", "duration", "contractor_type", "project_scale")}
    if version is None:
        return {"status": "UNCALCULATED", "reason": "해당 기준일의 제비율 없음",
                "basis_date": str(basis_date), "overhead_version": None,
                "conditions": conditions, "lines": [], "excluded": [], "unpriced": [],
                "basis_notes": ["해당 기준일의 제비율 없음"], "totals": {}}

    work = "civil" if inputs.get("work_category") not in ("재개발·재건축", "주택 신축", "주택 외 건축") else "architecture"
    rates = version[work]
    direct = priced.get("reference_amounts") or {}
    direct_parts = direct.get("subtotals") or {}
    if not direct_parts:
        direct_parts = priced.get("unit_prices") or {}
    volume = direct.get("volume")
    direct_materials = int(direct_parts.get("재료비") or 0)
    direct_labor = int(direct_parts.get("노무비") or 0)
    direct_expenses = int(direct_parts.get("경비") or 0)
    direct_total = int(direct.get("total") or (direct_materials + direct_labor + direct_expenses))
    scale_basis = direct_total if inputs.get("project_scale", "이 견적만") == "이 견적만" else int(inputs["project_scale"])
    scale_note = (f"전체 공사 규모: 이 견적만 기준({direct_total:,}원)으로 제비율 구간을 선택했습니다."
                  if inputs.get("project_scale", "이 견적만") == "이 견적만"
                  else f"전체 공사 규모 {scale_basis:,}원을 기준으로 제비율 구간을 선택했습니다.")
    duration = "6개월 이하" if inputs.get("duration") == "1개월 미만" else inputs.get("duration")
    duration = {"1~6개월": "6개월 이하"}.get(duration, duration)
    indirect_scale = _threshold_scale(scale_basis,
        [1_000_000_000, 5_000_000_000, 30_000_000_000, 100_000_000_000],
        ["10억 미만", "10억~50억 미만", "50억~300억 미만", "300억~1000억 미만", "1000억 이상"])
    management_scale = _threshold_scale(scale_basis,
        [5_000_000_000, 30_000_000_000, 100_000_000_000],
        ["50억 미만", "50억~300억 미만", "300억~1000억 미만", "1000억 이상"])
    contractor = inputs.get("contractor_type")
    contractor_scale = management_scale
    if contractor == "전문건설업":
        contractor_scale = _threshold_scale(scale_basis, [500_000_000, 3_000_000_000, 10_000_000_000],
            ["5억 미만", "5억~30억 미만", "30억~100억 미만", "100억 이상"])

    lines: list[dict] = []
    exclusions: list[dict] = []

    def add(name: str, category: str, base_name: str, base: int, item: dict | None,
            *, status: str = "산정", reason: str | None = None, note: str | None = None,
            amount: int | None = None, condition_cell: str | None = None) -> int:
        if status == "산정":
            calc_amount = _rate_amount(base, item["rate"]) if amount is None and item else amount
        else:
            calc_amount = 0 if status == "제외" else None
        lines.append({"name": name, "category": category, "base": base_name, "base_amount": base,
                      "rate": item.get("rate") if item else None, "amount": calc_amount,
                      "source": {"file": rates["source_file"], "cell": item.get("cell") if item else None,
                                 "version": version_id, "effective_from": version["effective_from"]},
                      "condition_source": {"file": rates["source_file"], "cell": condition_cell}
                                          if condition_cell else None,
                      "status": status, "reason": reason, "note": note})
        if status == "제외":
            exclusions.append({"name": name, "reason": reason})
        return int(calc_amount or 0)

    def add_total(name: str, category: str, amount: int, base_name: str) -> None:
        lines.append({"name": name, "category": category, "base": base_name,
                      "base_amount": amount, "rate": None, "amount": amount,
                      "source": {"file": "원가계산서 합산", "version": version_id},
                      "condition_source": None, "status": "산정", "reason": None, "note": None})

    lines.extend([
        {"name": "재료비", "category": "재료비", "base": "일위대가표 물량 기준 참고 금액",
         "base_amount": direct_materials, "rate": None, "amount": direct_materials,
         "source": {"file": "일위대가표", "version": priced.get("rate_version", {}).get("id")},
         "condition_source": None, "status": "산정", "reason": None, "note": None},
        {"name": "직접노무비", "category": "노무비", "base": "일위대가표 물량 기준 참고 금액",
         "base_amount": direct_labor, "rate": None, "amount": direct_labor,
         "source": {"file": "일위대가표", "version": priced.get("rate_version", {}).get("id")},
         "condition_source": None, "status": "산정", "reason": None, "note": None},
        {"name": "직접경비", "category": "경비", "base": "일위대가표 물량 기준 참고 금액",
         "base_amount": direct_expenses, "rate": None, "amount": direct_expenses,
         "source": {"file": "일위대가표", "version": priced.get("rate_version", {}).get("id")},
         "condition_source": None, "status": "산정", "reason": None, "note": None},
    ])

    indirect_item = _pick(rates["indirect_labor"], scale=indirect_scale, period=duration)
    indirect_labor = add("간접노무비", "노무비", "직접노무비", direct_labor, indirect_item)
    labor_total = direct_labor + indirect_labor
    add_total("노무비 계", "노무비", labor_total, "직접노무비 + 간접노무비")
    formulas = {item["name"]: item for item in rates["formula_rates"]}
    accident = add("산재보험료", "경비", "노무비 계", labor_total, formulas["산재보험료"])
    employment_item = next(item for item in rates["employment_insurance"] if item["minimum_won"] <= scale_basis)
    employment = add("고용보험료", "경비", "노무비 계", labor_total, employment_item)
    short_duration = inputs.get("duration") == "1개월 미만"
    insurance_reason = "공사기간 1개월 미만 — 원문: 공사기간 1개월(30일) 이상 모든 건설공사"
    insurance_cell = "AU53" if version_id == "260413" else "AU65"
    health = add("건강보험료", "경비", "직접노무비", direct_labor, formulas["건강보험료"],
                 status="제외" if short_duration else "산정",
                 reason=insurance_reason if short_duration else None,
                 condition_cell=insurance_cell if short_duration else None)
    long_term = add("노인장기요양보험료", "경비", "건강보험료", health,
                    formulas["노인장기요양보험료"],
                    status="제외" if short_duration else "산정",
                    reason=insurance_reason if short_duration else None,
                    condition_cell=insurance_cell if short_duration else None)
    pension = add("연금보험료", "경비", "직접노무비", direct_labor, formulas["연금보험료"],
                  status="제외" if short_duration else "산정",
                  reason=insurance_reason if short_duration else None,
                  condition_cell=insurance_cell if short_duration else None)

    env_kind = {
        "도로": "road", "플랜트": "plant", "지하철": "subway", "철도": "rail",
        "상하수도": "water", "항만(오탁방지막 미설치)": "port",
        "항만(오탁방지막 설치)": "silt_screen", "댐": "dam", "택지개발": "land",
        "기타 토목공사": "other_civil", "재개발·재건축": "redevelopment",
        "주택 신축": "new_housing", "주택 외 건축": "other_building",
    }[inputs["work_category"]]
    env_item = _pick(rates["environment"], kind=env_kind)
    environment = add("환경보전비", "경비", "직접공사비", direct_total, env_item,
                      note=f"공사 종류: {inputs['work_category']}")
    other_item = _pick(rates["other_expense"], scale=indirect_scale, period=duration)
    other_expense = add("기타경비", "경비", "재료비 + 노무비", direct_materials + labor_total, other_item)
    subcontract_item = next(item for item in rates["subcontract"] if item["minimum_won"] <= scale_basis)
    professional = contractor == "전문건설업"
    subcontract_cell = ("BZ" if work == "civil" else "BY") + ("86" if version_id == "260413" else "98")
    subcontract = add("하도급대금 지급보증 수수료", "경비", "직접공사비", direct_total,
                      subcontract_item, status="제외" if professional else "산정",
                      reason="적용제외: 전문공사" if professional else None,
                      condition_cell=subcontract_cell if professional else None)
    shared = _rates()["shared_law_rates"][work]
    asbestos = add("석면분담금", "경비", "노무비", labor_total, shared["asbestos"])
    wage_claim = add("임금채권부담금", "경비", "노무비", labor_total, shared["wage_claim"])

    retirement_eligible = scale_basis >= 100_000_000
    retirement_cell = ("AU113" if version_id == "260413" else
                       ("BZ112" if work == "civil" else "BY112"))
    retirement = add("퇴직공제부금비", "경비", "직접노무비", direct_labor,
                     formulas["퇴직공제부금비"],
                     status="산정" if retirement_eligible else "제외",
                     reason=None if retirement_eligible else "추정금액 1억 미만",
                     condition_cell=None if retirement_eligible else retirement_cell)
    safety_scale = _threshold_scale(scale_basis, [500_000_000, 5_000_000_000],
                                    ["5억 미만", "5억~50억 미만", "50억 이상"])
    safety_kind = ({"플랜트": "특수건설공사", "지하철": "중건설공사", "철도": "중건설공사",
                    "댐": "중건설공사"}.get(inputs["work_category"], "토목공사")
                   if work == "civil" else "건축공사")
    safety_item = _pick(rates["industrial_safety"], scale=safety_scale, kind=safety_kind)
    safety_eligible = scale_basis >= 20_000_000
    safety = add("산업안전보건관리비", "경비", "재료비 + 직접노무비",
                 direct_materials + direct_labor, safety_item,
                 status="산정" if safety_eligible else "제외",
                 reason=None if safety_eligible else "총 공사금액 2천만원 미만",
                 note="기초액은 전체 공사에 1회 계상 — 부분 견적에서 제외(간이)" if safety_eligible else None,
                 condition_cell=None if safety_eligible else ("DK51" if work == "civil" else "DJ51"))

    management_item = _pick(rates["management"], contractor=contractor, scale=contractor_scale)
    expense_total = (direct_expenses + accident + employment + health + long_term + pension
                     + environment + other_expense + subcontract + asbestos + wage_claim
                     + retirement + safety)
    add_total("경비 계", "경비", expense_total, "직접경비 + 간접경비")
    net_cost = direct_materials + labor_total + expense_total
    add_total("순공사원가", "합계", net_cost, "재료비 + 노무비 계 + 경비 계")
    management = add("일반관리비", "일반관리비", "순공사원가", net_cost, management_item)
    profit_scale = _threshold_scale(scale_basis,
        [5_000_000_000, 30_000_000_000, 100_000_000_000],
        ["50억 미만", "50억~300억 미만", "300억~1000억 미만", "1000억 이상"])
    profit_item = _pick(rates["profit"], scale=profit_scale)
    profit_base = labor_total + expense_total + management
    profit = add("이윤", "이윤", "노무비 + 경비 + 일반관리비", profit_base, profit_item)
    total_cost = net_cost + management + profit
    vat = _won(Decimal(total_cost) * Decimal("0.1"))
    add_total("총원가", "합계", total_cost, "순공사원가 + 일반관리비 + 이윤")
    add("부가가치세", "부가가치세", "총원가", total_cost, None, amount=vat)
    add_total("도급액", "합계", total_cost + vat, "총원가 + 부가가치세")
    add("공사이행보증", "경비", "", 0, None, status="제외",
        reason=_rates()["unpriced_rules"]["performance_bond"])
    for item in priced.get("excluded", []):
        if not any(line["name"] == item.get("name") for line in lines):
            add(item["name"], item.get("category", "경비"), "", 0, None,
                status="제외", reason=item.get("reason"))
    unpriced = list(priced.get("unpriced", []))
    if not any(item.get("name") == "건설기계대여대금 지급보증 수수료" for item in unpriced):
        unpriced.append({"name": "건설기계대여대금 지급보증 수수료",
                         "reason": _rates()["unpriced_rules"]["equipment_rental_guarantee"]})
    for item in unpriced:
        if not any(line["name"] == item.get("name") for line in lines):
            add(item["name"], item.get("category", "경비"), "", 0, None,
                status="미산정", reason=item.get("reason"))
    partial = bool(unpriced)
    return {
        "status": "PARTIAL" if partial else "OK", "basis_date": str(basis_date),
        "overhead_version": {"id": version_id, "effective_from": version["effective_from"],
                              "source_files": [rates["source_file"]]},
        "conditions": conditions,
        "basis_notes": [scale_note,
                        "산업안전보건관리비 기초액은 전체 공사에 1회 계상 — 부분 견적에서 제외(간이)."],
        "lines": lines,
        "excluded": exclusions,
        "unpriced": unpriced,
        "totals": {"materials": direct_materials, "labor": labor_total, "expenses": expense_total,
                   "net_cost": net_cost, "management": management, "profit": profit,
                   "total_cost": total_cost, "vat": vat, "contract_amount": total_cost + vat},
        "volume": volume,
    }
