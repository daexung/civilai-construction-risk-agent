"""일위대가표의 노무비와 명세에 적힌 노무비 요율 비용을 계산한다."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal, ROUND_DOWN
from functools import lru_cache
from pathlib import Path

from agent.tools.source.citation import resolve_cites


ROOT = Path(__file__).resolve().parents[3]
RATES = ROOT / "data/rates/labor_rates.json"
AMOUNTS = ROOT / "agent/rules/common/1-2-2_amount_units.json"
EQUIPMENT_RATES = ROOT / "data/rates/equipment_rates.json"


@lru_cache(maxsize=1)
def _versions() -> list[dict]:
    return json.loads(RATES.read_text(encoding="utf-8"))["versions"]


@lru_cache(maxsize=1)
def _amount_rules() -> dict:
    return json.loads(AMOUNTS.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _equipment_rates() -> dict:
    return json.loads(EQUIPMENT_RATES.read_text(encoding="utf-8"))


def select_rate_version(basis_date: str | date | None = None) -> dict | None:
    """기준일을 포함하는 공표 적용 기간을 선택한다. 없는 기간은 보간하지 않는다."""
    day = date.today() if basis_date is None else date.fromisoformat(basis_date) if isinstance(basis_date, str) else basis_date
    return next((version for version in _versions()
                 if date.fromisoformat(version["effective_from"]) <= day
                 and (version["effective_to"] is None or day <= date.fromisoformat(version["effective_to"]))), None)


def select_equipment_version(basis_date: str | date | None = None) -> dict | None:
    """연도별 경비산출표의 적용 기간을 확인한다. 다른 연도로 보간하지 않는다."""
    day = date.today() if basis_date is None else date.fromisoformat(basis_date) if isinstance(basis_date, str) else basis_date
    version = _equipment_rates()
    return (version if date.fromisoformat(version["effective_from"]) <= day
            <= date.fromisoformat(version["effective_to"]) else None)


def _truncate(value: Decimal, quantum: str) -> Decimal:
    unit = Decimal(quantum)
    return (value / unit).to_integral_value(rounding=ROUND_DOWN) * unit


def _money(value: Decimal | None, places: int) -> str | None:
    return format(value, f".{places}f") if value is not None else None


def _exact(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _rule_citation(item: str, value: str) -> dict:
    rule = _amount_rules()
    return {
        "code": "2026 건설공사 표준품셈", "division": "공통부문",
        "section_no": "1-2-2", "section_title": "수량의 단위표준", "section": "1-2-2 수량의 단위표준",
        "subsection": "2. 금액의 단위표준", "item": item, "row": item,
        "column": None, "value": value, "pdf_page": 62, "printed_page": 6,
        "quote": None, "internal_id": "PDF62-1-2-2",
        "label": f"{rule['source']}\n{item}: {value}원 미만버림",
    }


def _wage_citation(version: dict, code: str, entry: dict) -> dict:
    page = entry.get("pdf_page")
    label = (f"{version['publisher']} 「{version['title']}」(시중노임단가), "
             f"{version['effective_from']} 적용\n{code} {entry['name']}: {int(entry['daily']):,}원/일")
    if page:
        label += f" (PDF {page}쪽)"
    else:
        label += f" ({version['source_tag']} 보존 CSV)"
    return {"code": version["title"], "division": None, "section_no": code,
            "section_title": entry["name"], "section": entry["name"], "subsection": None,
            "item": "노임단가", "row": entry["name"], "column": code,
            "value": entry["daily"], "pdf_page": page, "printed_page": None,
            "quote": None, "internal_id": f"{version['id']}:{code}", "label": label}


def _version_info(version: dict | None) -> dict | None:
    if version is None:
        return None
    return {key: version[key] for key in ("id", "title", "publisher", "effective_from", "effective_to",
                                          "source_file", "unit")}


def _equipment_version_info(version: dict | None) -> dict | None:
    if version is None:
        return None
    return {"version": version["version"], "title": f"{version['version']}년도 건설기계 경비산출표",
            **{key: version[key] for key in ("publisher", "published", "effective_from",
                                               "effective_to", "source_file", "effective_period_basis")}}


def _machine_citation(code: str, entry: dict, item: str, value: str) -> dict:
    return {"code": "2026년도 건설기계 경비산출표", "division": "건설기계",
            "section_no": "4504", "section_title": "콘크리트 펌프차", "section": "4504 콘크리트 펌프차",
            "subsection": entry["spec"], "item": item, "row": code, "column": item,
            "value": value, "pdf_page": entry["pdf_page"], "printed_page": entry["pdf_page"],
            "quote": None, "internal_id": code,
            "label": f"대한건설협회 「2026년도 건설기계 경비산출표」 {code} {entry['spec']} (PDF {entry['pdf_page']}쪽)\n{item}: {value}"}


def _standard_citation(section_no: str, title: str, page: int, quote: str) -> dict:
    return {"code": "2026 건설공사 표준품셈", "division": "공통부문",
            "section_no": section_no, "section_title": title, "section": f"{section_no} {title}",
            "subsection": None, "item": "본문", "row": None, "column": None,
            "value": None, "pdf_page": page, "printed_page": page - 56,
            "quote": quote, "internal_id": f"PDF{page}-{section_no}",
            "label": f"2026 건설공사 표준품셈 공통부문 {section_no} {title} (인쇄 {page - 56}쪽)"}


def _operator_hours_citation() -> dict:
    return {"code": "2026년 하반기 적용 건설업 임금실태조사", "division": None,
            "section_no": None, "section_title": "이용상의 주의사항", "section": "이용상의 주의사항",
            "subsection": "7. 이용상의 주의사항", "item": "1일 8시간 기준",
            "row": None, "column": None, "value": "8시간", "pdf_page": 4,
            "printed_page": 3, "quote": "다. 본조사임금은1일8시간기준(단, 잠수부는6시간기준)금액임.",
            "internal_id": "2026H2:PDF4:8시간",
            "label": "대한건설협회 「2026년 하반기 적용 건설업 임금실태조사」 7. 이용상의 주의사항 (PDF 4쪽)\n건설기계운전사 일당의 시간당 환산: 1일 8시간"}


def _machine_rows(spec: dict, line: dict, version: dict | None,
                  equipment_version: dict | None, inputs: dict) -> list[dict]:
    setting = spec["quantity_model"]["params"]["equipment"]
    field = next(field for field in spec["inputs"] if field["name"] == setting["machine_code_input"])
    size = inputs.get(setting["machine_code_input"])
    code = field["machine_codes"].get(size)
    if not code:
        return []
    base = {"kind": "equipment_component", "machine_code": code,
            "machine_spec": size, "unit": line["unit"],
            "quantity": line["applied"], "rate_code": None,
            "amount_exact": None, "amount": None, "reason": None}
    if equipment_version is None:
        reason = "기준일에 적용 가능한 건설기계 경비산출표 없음"
        return [{**base, "category": category, "name": name, "unit_price": None,
                 "reason": reason, "citations": list(line.get("citations", []))}
                for category, name in (("경비", "펌프차 기계손료"),
                                       ("노무비", "펌프차 운전원"),
                                       ("재료비", "펌프차 연료·잡재료비"))]
    machine = equipment_version["machines"][code]
    base["machine_spec"] = machine["spec"]
    quantity = Decimal(line["applied"])
    amount_rule = _rule_citation("일위대가표의 금액란", "0.1")
    standard = _standard_citation("8-1-6", "기계경비 적산요령", 223,
        "3. 운전경비 : 기계를 사용하는데 필요한 다음 각호 경비의 합계액으로 한다.")
    hourly = Decimal(machine["hourly_depreciation"])
    exact = quantity * hourly
    depreciation = {**base, "category": "경비", "name": "펌프차 기계손료",
                    "unit_price": _exact(hourly), "amount_exact": _exact(exact),
                    "amount": _money(_truncate(exact, "0.1"), 1),
                    "citations": list(line.get("citations", [])) + [
                        _machine_citation(code, machine, "시간당 손료", str(machine["hourly_depreciation"])),
                        _standard_citation("8-1-5", "기계경비 용어와 정의", 223,
                            "손료계수의 합계를 곱한 값을 말한다. (원미만의 값은 절사한다.)"),
                        amount_rule]}
    wage = version["rates"].get(setting["operator_rate_code"]) if version else None
    operator = {**base, "category": "노무비", "name": "펌프차 운전원",
                "rate_code": setting["operator_rate_code"], "unit_price": None,
                "reason": None, "citations": list(line.get("citations", [])) + [
                    _machine_citation(code, machine, "조종원", str(machine["operator_per_day"])),
                    standard,
                    _operator_hours_citation()]}
    if wage and wage["daily"] is not None and wage["name"] == "건설기계운전사":
        hourly_wage = Decimal(machine["operator_per_day"]) * Decimal(wage["daily"]) / Decimal(8)
        exact = quantity * hourly_wage
        operator.update(unit_price=_exact(hourly_wage), amount_exact=_exact(exact),
                        amount=_money(_truncate(exact, "0.1"), 1),
                        citations=operator["citations"] + [
                            _wage_citation(version, setting["operator_rate_code"], wage), amount_rule])
    else:
        operator["reason"] = "적용 가능한 건설기계운전사 공표 노임단가 없음"
    fuel_amount = quantity * Decimal(machine["fuel_l_per_hr"])
    fuel = {**base, "category": "재료비", "name": "펌프차 연료·잡재료비",
            "unit_price": None, "fuel_l_per_hr": machine["fuel_l_per_hr"],
            "fuel_l_per_unit": _exact(fuel_amount),
            "misc_pct_of_fuel": machine["misc_pct_of_fuel"],
            "reason": "유류 가격 미입력 — 품셈 8-1-7: 해당 지역 가격",
            "citations": list(line.get("citations", [])) + [
                _machine_citation(code, machine, "주연료", machine["fuel_l_per_hr"] + "ℓ/hr"),
                _standard_citation("8-1-7", "손료보정 등", 224,
                    "5. 유류가격은 해당지역의 가격으로 한다.")]}
    return [depreciation, operator, fuel]


def price_unit(spec: dict, unit_lines: list[dict], rate_version: dict | None,
               inputs: dict | None = None, basis_date: str | date | None = None) -> dict:
    """applied 품량으로만 금액을 산출하며, 없는 단가/기계경비는 null로 남긴다."""
    amount_rule = _rule_citation("일위대가표의 금액란", "0.1")
    total_rule = _rule_citation("일위대가표의 계금", "1")
    codes = spec["quantity_model"]["params"]["crew"]["rate_codes"]
    rows = []
    unpriced = []
    priced_labor = []
    equipment_lines = []
    equipment_version = select_equipment_version(basis_date)
    labor_missing = False
    for line in unit_lines:
        row = {"kind": line["kind"], "category": "노무비" if line["kind"] == "labor" else "경비",
               "name": line["name"], "unit": line["unit"], "quantity": line["applied"],
               "rate_code": codes.get(line["name"]) if line["kind"] == "labor" else None,
               "unit_price": None, "amount_exact": None, "amount": None,
               "citations": list(line.get("citations", [])), "reason": None}
        if line["kind"] == "equipment":
            equipment_lines.extend(_machine_rows(spec, line, rate_version, equipment_version, inputs or {}))
            if not equipment_lines:
                row["reason"] = "장비 규격 미입력으로 기계경비 미산정"
        elif rate_version is None:
            row["reason"] = "적용 가능한 노임단가 없음"
            labor_missing = True
        else:
            code = row["rate_code"]
            wage = rate_version["rates"].get(code) if code else None
            if not wage or wage["daily"] is None or wage["name"] != line["name"]:
                row["reason"] = "해당 직종의 공표 노임단가 없음"
                labor_missing = True
            else:
                exact = Decimal(line["applied"]) * Decimal(wage["daily"])
                applied = _truncate(exact, "0.1")
                row.update(unit_price=wage["daily"], amount_exact=_exact(exact),
                           amount=_money(applied, 1),
                           citations=row["citations"] + [_wage_citation(rate_version, code, wage), amount_rule])
                priced_labor.append(applied)
        rows.append(row)
        if row["reason"]:
            unpriced.append({"name": row["name"], "reason": row["reason"],
                             "category": row["category"], "citations": row["citations"]})

    labor_subtotal = sum(priced_labor, Decimal("0")) if priced_labor else None
    costs = []
    category_values = {"재료비": [], "노무비": priced_labor, "경비": []}
    for component in equipment_lines:
        if component["amount"] is None:
            unpriced.append({"name": component["name"], "reason": component["reason"],
                             "category": component["category"], "citations": component["citations"]})
        else:
            category_values[component["category"]].append(Decimal(component["amount"]))
    for rule in spec.get("cost_rules", []):
        if rule["base"] != "labor_subtotal":
            raise ValueError(f"지원하지 않는 요율 기준: {rule['base']}")
        citations = resolve_cites(rule["cite"])
        cost = {"kind": "rate_cost", "category": rule["category"], "name": rule["name"],
                "base": rule["base"], "rate": rule["rate"], "amount_exact": None,
                "amount": None, "reason": None, "citations": citations}
        if labor_missing or labor_subtotal is None:
            cost["reason"] = "노무비 소계 미완성으로 요율 비용 미산정"
            unpriced.append({"name": cost["name"], "reason": cost["reason"],
                             "category": cost["category"], "citations": citations})
        else:
            exact = labor_subtotal * Decimal(rule["rate"])
            applied = _truncate(exact, "0.1")
            cost.update(amount_exact=_exact(exact), amount=_money(applied, 1),
                        citations=citations + [amount_rule])
            category_values[rule["category"]].append(applied)
        costs.append(cost)

    for item in spec["not_calculated"]:
        unpriced.append({"name": item["item"], "reason": "이번 계산 범위에서 미산정",
                         "category": None, "citations": resolve_cites(item.get("cite"))})

    subtotals = {category: _money(sum(values, Decimal("0")) if values else None, 1)
                 for category, values in category_values.items()}
    total_exact = sum((value for values in category_values.values() for value in values), Decimal("0"))
    has_amount = any(category_values.values())
    partial = bool(unpriced)
    return {"status": "PARTIAL" if partial else "OK", "partial": partial,
            "rate_version": _version_info(rate_version),
            "equipment_rate_version": _equipment_version_info(equipment_version),
            "lines": rows, "equipment_lines": equipment_lines,
            "cost_lines": costs,
            "labor_subtotal": _money(labor_subtotal, 1), "subtotals": subtotals,
            "total_exact": _money(total_exact, 1) if has_amount else None,
            "total": _money(_truncate(total_exact, "1"), 0) if has_amount else None,
            "total_citations": [total_rule] if has_amount else [],
            "unpriced": unpriced,
            "rounding_policy": {"source": _amount_rules()["source"],
                                "line": "0.1원 미만버림", "total": "1원 미만버림",
                                "small_amount_exception": _amount_rules()["small_amount_exception"]}}
