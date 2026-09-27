"""명세의 표와 조건만으로 일당 작업조형 기본 품량을 계산한다."""

from __future__ import annotations

import operator
import re
from fractions import Fraction
from typing import Any


_COMPARISONS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def _exact_text(value: Fraction) -> str:
    """유한소수는 소수로, 순환소수는 기약분수로 적는다."""
    if value.denominator == 1:
        return str(value.numerator)
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        twos += 1
        denominator //= 2
    while denominator % 5 == 0:
        fives += 1
        denominator //= 5
    if denominator != 1:
        return f"{value.numerator}/{value.denominator}"
    places = max(twos, fives)
    scaled = value.numerator * (10**places // value.denominator)
    sign = "-" if scaled < 0 else ""
    digits = str(abs(scaled)).zfill(places + 1)
    return f"{sign}{digits[:-places]}.{digits[-places:]}".rstrip("0").rstrip(".")


def _validate(field: dict, value: Any) -> tuple[Any, str | None]:
    name = field["name"]
    kind = field["type"]
    if kind == "enum":
        allowed = field["allowed_values"]
        if value not in allowed or type(value) is not type(allowed[0]):
            return None, f"{name}는 허용값 {allowed} 중 하나여야 함"
        return value, None
    if kind == "boolean":
        if type(value) is not bool or value not in field["allowed_values"]:
            return None, f"{name}는 true 또는 false여야 함"
        return value, None
    if kind == "nonnegative_integer":
        if type(value) is int:
            number = value
        elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value):
            number = int(value)
        else:
            return None, f"{name}는 0 이상의 정수여야 함"
        if number < 0:
            return None, f"{name}는 0 이상의 정수여야 함"
        return number, None
    if kind == "positive_rational":
        if type(value) not in (str, int, Fraction):
            return None, f"{name}는 정확한 양수여야 함"
        try:
            number = Fraction(value)
        except (ValueError, ZeroDivisionError):
            return None, f"{name}는 정확한 양수여야 함"
        if number <= 0:
            return None, f"{name}은 0보다 커야 함"
        return number, None
    return None, f"{name}의 지원하지 않는 입력 타입: {kind}"


def _cell(tables: dict, table_id: str, row: str, column: str) -> tuple[Fraction, dict]:
    table = tables[table_id]
    raw = table["values"][row][column]
    value = Fraction(raw)
    return value, {"table": table_id, "row": row, "column": column, "value": raw, "source": table["source"]}


def check_blocked(spec: dict, inputs: dict) -> dict | None:
    """명세의 blocked 조건에 걸리면 사유·출처를 돌려주고, 아니면 None. gate와 compute가 함께 쓴다."""
    by_name = {field["name"]: field for field in spec["inputs"]}
    validated: dict[str, Any] = {}
    for name, value in inputs.items():
        field = by_name.get(name)
        if field is None or value is None:
            continue
        checked, error = _validate(field, value)
        if error is None:
            validated[name] = checked
    for item in spec["blocked"]:
        condition = item.get("blocked_if")
        if (condition and condition["input"] in validated
                and _COMPARISONS[condition["op"]](validated[condition["input"]], condition["value"])):
            return {"reason": item["reason"], "source": item["source"], "input": condition["input"]}
    return None


def adjusted_daily_crew(spec: dict, inputs: dict) -> dict:
    """검사 → 누락 질문 → 보류 판정 → 정확한 기본 품량 순으로 처리한다."""
    fields = spec["inputs"]
    by_name = {field["name"]: field for field in fields}
    tables = {table["id"]: table for table in spec["tables"]}
    validated: dict[str, Any] = {}

    for name, value in inputs.items():
        if name not in by_name:
            return {"status": "rejected", "reason": f"알 수 없는 입력: {name}", "input": name}
        if value is None:
            continue
        checked, error = _validate(by_name[name], value)
        if error:
            return {"status": "rejected", "reason": error, "input": name}
        validated[name] = checked

    missing = [field["name"] for field in fields if field["required"] and field["name"] not in validated]
    if missing:
        questions = []
        for name in missing:
            field = by_name[name]
            question = {"name": name, "ask": field["ask"], "allowed_values": field["allowed_values"]}
            if "decision_table" in field:
                table_id = field["decision_table"]
                table = tables[table_id]
                question["decision_table"] = {"id": table_id, "values": table["values"], "source": table["source"]}
            questions.append(question)
        return {"status": "ask", "missing": missing, "questions": questions}

    blocked = check_blocked(spec, validated)
    if blocked:
        return {"status": "blocked", **blocked}

    params = spec["quantity_model"]["params"]
    base = params["base_output"]
    base_value, base_source = _cell(
        tables, base["table"], validated[base["row_input"]], validated[base["column_input"]]
    )
    daily_volume = base_value
    coefficient_sources = []
    for coefficient in params["coefficients"]:
        value, source = _cell(tables, coefficient["table"], coefficient["row"], validated[coefficient["input"]])
        daily_volume *= value
        coefficient_sources.append(source)
    if daily_volume <= 0:
        return {"status": "rejected", "reason": "명세의 일당시공량이 0 이하임", "input": "spec"}

    quantity_name = params["quantity_input"]
    quantity = validated[quantity_name]
    work_days = quantity / daily_volume
    crew = params["crew"]
    column = validated[crew["column_input"]]
    person_days = {}
    person_sources = {}
    for trade in crew["trades"]:
        count, crew_source = _cell(tables, crew["table"], trade, column)
        applied_rules = []
        for rule in spec["crew_rules"]:
            if all(validated.get(name) == expected for name, expected in rule["when"].items()):
                if trade in rule["change"]:
                    change = rule["change"][trade]
                    count += Fraction(change)
                    applied_rules.append({"when": rule["when"], "change": change, "source": rule["source"]})
        if count < 0:
            return {"status": "rejected", "reason": f"명세 오류: {trade} 조정 후 인원이 음수임", "input": "spec"}
        person_days[trade] = _exact_text(work_days * count)
        person_sources[trade] = {
            "crew": crew_source,
            "rules": applied_rules,
            "adjusted_crew": _exact_text(count),
            "work_days": "work_days",
            "formula": "work_days × adjusted_crew",
        }

    equipment = params["equipment"]
    equipment_count, equipment_source = _cell(tables, equipment["table"], equipment["name"], column)
    if equipment_count < 0:
        return {"status": "rejected", "reason": "명세 오류: 장비 대수가 음수임", "input": "spec"}
    equipment_days = _exact_text(work_days * equipment_count)

    return {
        "status": "computed",
        "daily_volume_m3": _exact_text(daily_volume),
        "work_days": _exact_text(work_days),
        "person_days": person_days,
        "equipment_days": {equipment["name"]: equipment_days},
        "equipment_units": {equipment["name"]: equipment["unit"]},
        "provenance": {
            "daily_volume_m3": {
                "base_output": base_source,
                "coefficients": coefficient_sources,
                "formula_source": spec["quantity_model"]["source"],
            },
            "work_days": {
                "quantity_input": quantity_name,
                "quantity": _exact_text(quantity),
                "quantity_source": by_name[quantity_name]["source"],
                "daily_volume_m3": "daily_volume_m3",
                "formula": "quantity ÷ daily_volume_m3",
            },
            "person_days": person_sources,
            "equipment_days": {
                equipment["name"]: {
                    "equipment": equipment_source,
                    "work_days": "work_days",
                    "formula": "work_days × equipment_count",
                }
            },
        },
        "not_calculated": spec["not_calculated"],
    }
