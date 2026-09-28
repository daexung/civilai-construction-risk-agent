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

    def add(name: str, category: str, base_name: str, base: int, item: dict | None,
            *, divisor: int = 100, note: str | None = None, amount: int | None = None) -> int:
        calc_amount = _rate_amount(base, item["rate"], divisor) if amount is None and item else amount
        lines.append({"name": name, "category": category, "base": base_name, "base_amount": base,
                      "rate": item.get("rate") if item else None, "amount": calc_amount,
                      "source": {"file": rates["source_file"], "cell": item.get("cell") if item else None,
                                 "version": version_id, "effective_from": version["effective_from"]},
                      "note": note})
        return int(calc_amount or 0)

    lines.extend([
        {"name": "재료비", "category": "재료비", "base": "일위대가표 물량 기준 참고 금액",
         "base_amount": direct_materials, "rate": None, "amount": direct_materials,
         "source": {"file": "일위대가표", "version": priced.get("rate_version", {}).get("id")}, "note": None},
        {"name": "직접노무비", "category": "노무비", "base": "일위대가표 물량 기준 참고 금액",
         "base_amount": direct_labor, "rate": None, "amount": direct_labor,
         "source": {"file": "일위대가표", "version": priced.get("rate_version", {}).get("id")}, "note": None},
        {"name": "직접경비", "category": "경비", "base": "일위대가표 물량 기준 참고 금액",
         "base_amount": direct_expenses, "rate": None, "amount": direct_expenses,
         "source": {"file": "일위대가표", "version": priced.get("rate_version", {}).get("id")}, "note": None},
    ])

    indirect_item = _pick(rates["indirect_labor"], scale=indirect_scale, period=duration)
    indirect_labor = add("간접노무비", "노무비", "직접노무비", direct_labor, indirect_item)
    labor_total = direct_labor + indirect_labor
    labor_base = labor_total
    health_item = next(item for item in rates["formula_rates"] if item["name"] == "건강보험료 추가분")
    accident_item = next(item for item in rates["formula_rates"] if item["name"] == "간접노무비")
    pension_item = next(item for item in rates["formula_rates"] if item["name"] == "장기요양보험료")
    accident = add("산재보험료", "경비", "직접노무비 + 간접노무비", labor_base, accident_item)
    employment_item = next(item for item in rates["employment_insurance"] if item["minimum_won"] <= scale_basis)
    employment = add("고용보험료", "경비", "직접노무비 + 간접노무비", labor_base, employment_item)
    health_item = {**health_item, "rate": "3.595", "cell": next(
        item["cell"] for item in rates["formula_rates"] if item["name"] == "산재보험료")}
    health = add("건강보험료", "경비", "직접노무비", direct_labor, health_item)
    long_term_item = next(item for item in rates["formula_rates"] if item["name"] == "건강보험료 추가분")
    long_term = add("장기요양보험료", "경비", "건강보험료", health, long_term_item)
    pension = add("국민연금보험료", "경비", "직접노무비", direct_labor, pension_item)

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
    subcontract = add("하도급대금 지급보증 수수료", "경비", "직접공사비", direct_total,
                      subcontract_item)
    shared = _rates()["shared_law_rates"][work]
    asbestos = add("석면분담금", "경비", "노무비", labor_total, shared["asbestos"])
    wage_claim = add("임금채권부담금", "경비", "노무비", labor_total, shared["wage_claim"])

    management_item = _pick(rates["management"], contractor=contractor, scale=contractor_scale)
    expense_total = (direct_expenses + accident + employment + health + long_term + pension
                     + environment + other_expense + subcontract + asbestos + wage_claim)
    net_cost = direct_materials + labor_total + expense_total
    management = _rate_amount(net_cost, management_item["rate"])
    lines.append({"name": "일반관리비", "category": "일반관리비", "base": "순공사원가",
                  "base_amount": net_cost, "rate": management_item["rate"], "amount": management,
                  "source": {"file": rates["source_file"], "cell": management_item["cell"],
                             "version": version_id, "effective_from": version["effective_from"]},
                  "note": None})
    profit_scale = _threshold_scale(scale_basis,
        [5_000_000_000, 30_000_000_000, 100_000_000_000],
        ["50억 미만", "50억~300억 미만", "300억~1000억 미만", "1000억 이상"])
    profit_item = _pick(rates["profit"], scale=profit_scale)
    profit_base = labor_total + expense_total + management
    profit = add("이윤", "이윤", "노무비 + 경비 + 일반관리비", profit_base, profit_item)
    total_cost = net_cost + management + profit
    vat = _won(Decimal(total_cost) * Decimal("0.1"))

    exclusions = [
        {"name": "퇴직공제부금비", "reason": "공사 종류·규모별 요건 확인 전 제외"},
        {"name": "산업안전보건관리비", "reason": "부분 견적에 기본액을 배분하지 않음. 기본액은 전체 공사에 1회 계상"},
        {"name": "공사이행보증", "reason": _rates()["unpriced_rules"]["performance_bond"]},
    ]
    safety_scale = _threshold_scale(scale_basis, [500_000_000, 5_000_000_000],
                                    ["5억 미만", "5억~50억 미만", "50억 이상"])
    safety_kind = ({"플랜트": "특수건설공사", "지하철": "중건설공사", "철도": "중건설공사",
                    "댐": "중건설공사"}.get(inputs["work_category"], "토목공사")
                   if work == "civil" else "건축공사")
    safety_item = _pick(rates["industrial_safety"], scale=safety_scale, kind=safety_kind)
    exclusions[1]["rate"] = safety_item["rate"]
    exclusions[1]["source"] = {"file": rates["source_file"], "cell": safety_item["cell"],
                                 "version": version_id}
    unpriced = list(priced.get("unpriced", []))
    if not any(item.get("name") == "건설기계대여대금 지급보증 수수료" for item in unpriced):
        unpriced.append({"name": "건설기계대여대금 지급보증 수수료",
                         "reason": _rates()["unpriced_rules"]["equipment_rental_guarantee"]})
    partial = bool(unpriced or exclusions or priced.get("partial"))
    return {
        "status": "PARTIAL" if partial else "OK", "basis_date": str(basis_date),
        "overhead_version": {"id": version_id, "effective_from": version["effective_from"],
                              "source_files": [rates["source_file"]]},
        "conditions": conditions,
        "basis_notes": [scale_note,
                        "안전관리비는 요율만 참고했고 기본액은 부분 견적에서 제외했습니다. 전체 공사에 한 번 계상하는 금액입니다."],
        "lines": lines,
        "excluded": exclusions,
        "unpriced": unpriced,
        "totals": {"materials": direct_materials, "labor": labor_total, "expenses": expense_total,
                   "net_cost": net_cost, "management": management, "profit": profit,
                   "total_cost": total_cost, "vat": vat, "contract_amount": total_cost + vat},
        "volume": volume,
    }
