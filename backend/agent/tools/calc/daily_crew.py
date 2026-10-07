"""명세의 표와 조건만으로 일당 작업조형 기본 품량을 계산한다."""

from __future__ import annotations

import operator
import re
from fractions import Fraction
from typing import Any

from backend.agent.rules.conditions import price_fields
from backend.agent.tools.calc.unit_rounding import round_quantity, unit_places
from backend.agent.tools.calc.numbers import parse_fraction, parse_table_number
from backend.agent.tools.source.citation import cite_table, resolve_cites


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
            number = parse_fraction(value)
        except (ValueError, ZeroDivisionError):
            return None, f"{name}는 정확한 양수여야 함"
        if number <= 0:
            return None, f"{name}은 0보다 커야 함"
        return number, None
    if kind == "positive_currency":
        if value == "모름":
            return value, None
        if type(value) not in (str, int, Fraction):
            return None, f"{name}는 정확한 양수여야 함"
        try:
            number = parse_fraction(value)
        except (ValueError, ZeroDivisionError):
            return None, f"{name}는 정확한 양수여야 함"
        if number <= 0:
            return None, f"{name}은 0보다 커야 함"
        return str(number.numerator) if number.denominator == 1 else str(number), None
    return None, f"{name}의 지원하지 않는 입력 타입: {kind}"


def _cell(tables: dict, table_id: str, row: str, column: str) -> tuple[Fraction, dict]:
    table = tables[table_id]
    raw = table["values"][row][column]
    value = parse_table_number(raw)
    return value, {"table": table_id, "row": row, "column": column, "value": raw,
                   "source": table["source"], "citations": [cite_table(table_id, row, column, raw)]}


def _axis_key(values: dict, reference: str | None, inputs: dict,
              axis: str, table_id: str) -> tuple[str | None, str | None]:
    """축 지정이 없을 때는 유일한 키만 채택한다. 복수 후보를 임의로 고르지 않는다."""
    if reference is None:
        if len(values) == 1:
            return next(iter(values)), None
        return None, f"{table_id}: {axis} 지정 없음 (후보 {len(values)}개)"
    key = inputs.get(reference, reference)
    if key not in values:
        return None, f"{table_id}: {axis} '{key}' 없음"
    return key, None


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
        if not condition or condition["input"] not in validated:
            continue
        field = by_name[condition["input"]]
        expected = condition["value"]
        if field["type"] in ("positive_rational", "positive_currency", "nonnegative_integer"):
            try:
                expected = parse_fraction(expected)
            except ValueError:
                return {"status": "unresolvable", "reason":
                        f"숫자 보류 조건 해석 불가: {condition['input']} {condition['op']} {condition['value']}",
                        "input": condition["input"]}
        try:
            matches = _COMPARISONS[condition["op"]](validated[condition["input"]], expected)
        except (TypeError, KeyError):
            return {"status": "unresolvable", "reason":
                    f"보류 조건 비교 불가: {condition['input']} {condition['op']} {condition['value']}",
                    "input": condition["input"]}
        if matches:
            return {"reason": item["reason"], "source": item["source"], "input": condition["input"],
                    "citations": resolve_cites(item.get("cite"))}
    return None


def adjusted_daily_crew(spec: dict, inputs: dict, *, labor_only: bool = False) -> dict:
    """검사 → 누락 질문 → 보류 판정 → 정확한 기본 품량 순으로 처리한다.

    labor_only=True(품 산출 모드)일 때만 가격 조건(관급/사급·자재 단가)이 없어도 품을 계산한다.
    """
    fields = spec["inputs"]
    optional = price_fields(spec) if labor_only else frozenset()
    by_name = {field["name"]: field for field in fields}
    tables = {table["id"]: table for table in spec["tables"]}
    validated: dict[str, Any] = {}

    for name, value in inputs.items():
        if re.fullmatch(r"apply_adj_\d+", name):
            if value not in ("예", "아니오"):
                return {"status": "rejected", "reason": f"{name}는 예 또는 아니오여야 함", "input": name}
            validated[name] = value
            continue
        if name not in by_name:
            return {"status": "rejected", "reason": f"알 수 없는 입력: {name}", "input": name}
        if value is None:
            continue
        checked, error = _validate(by_name[name], value)
        if error:
            return {"status": "rejected", "reason": error, "input": name}
        validated[name] = checked

    missing = [field["name"] for field in fields
               if field["required"] and field["name"] not in validated and field["name"] not in optional
               and (not field.get("when")
                    or validated.get(field["when"]["input"]) == field["when"]["equals"])]
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
    base_table = tables[base["table"]]["values"]
    base_row, error = _axis_key(base_table, base.get("row_input", base.get("row")), validated, "행", base["table"])
    if error:
        return {"status": "unresolvable", "reason": error}
    base_column, error = _axis_key(base_table[base_row], base.get("column_input", base.get("column")),
                                   validated, "열", base["table"])
    if error:
        return {"status": "unresolvable", "reason": error}
    base_value, base_source = _cell(tables, base["table"], base_row, base_column)
    daily_volume = base_value
    coefficient_sources = []
    for coefficient in params.get("coefficients", []):
        value, source = _cell(tables, coefficient["table"], coefficient["row"], validated[coefficient["input"]])
        daily_volume *= value
        coefficient_sources.append(source)
    if daily_volume <= 0:
        return {"status": "rejected", "reason": "명세의 일당시공량이 0 이하임", "input": "spec"}

    places = unit_places(daily_volume)
    quantity_name = params["quantity_input"]
    quantity_unit = by_name[quantity_name]["unit"]
    daily_text = _exact_text(daily_volume)
    magnitude = "1단위이하" if daily_volume < 10 else f"{10 ** (places - 2):,}단위"
    rule_label = f"1-2-8 {magnitude}→소수 {places}자리, 1-2-1 반올림"
    unit_lines = []
    quantity = validated[quantity_name]
    work_days = quantity / daily_volume
    crew = params["crew"]
    crew_table = tables[crew["table"]]["values"]
    person_days = {}
    person_sources = {}
    for trade in crew["trades"]:
        if trade not in crew_table:
            return {"status": "unresolvable", "reason": f"{crew['table']}: 행 '{trade}' 없음"}
        column, error = _axis_key(crew_table[trade], crew.get("column_input", crew.get("column")),
                                  validated, "열", crew["table"])
        if error:
            return {"status": "unresolvable", "reason": error}
        count, crew_source = _cell(tables, crew["table"], trade, column)
        applied_rules = []
        for rule in spec["crew_rules"]:
            if all(validated.get(name) == expected for name, expected in rule["when"].items()):
                if trade in rule["change"]:
                    change = rule["change"][trade]
                    count += parse_fraction(change)
                    applied_rules.append({"when": rule["when"], "change": change, "source": rule["source"],
                                          "citations": resolve_cites(rule.get("cite"))})
        if count < 0:
            return {"status": "rejected", "reason": f"명세 오류: {trade} 조정 후 인원이 음수임", "input": "spec"}
        person_days[trade] = _exact_text(work_days * count)
        unit_value = count / daily_volume
        unit_lines.append({
            "kind": "labor", "name": trade, "unit": f"인/{quantity_unit}",
            "exact": str(unit_value), "applied": round_quantity(unit_value, places),
            "places": places, "formula": f"{_exact_text(count)}인 ÷ {daily_text}{quantity_unit}",
            "rule": rule_label, "source": f"{crew_source['table']} {crew_source['source']}",
            "citations": crew_source["citations"] + [citation for rule in applied_rules
                                                        for citation in rule["citations"]],
        })
        person_sources[trade] = {
            "crew": crew_source,
            "rules": applied_rules,
            "adjusted_crew": _exact_text(count),
            "work_days": "work_days",
            "formula": "work_days × adjusted_crew",
            "citations": crew_source["citations"] + [citation for rule in applied_rules
                                                   for citation in rule["citations"]],
        }

    equipment_spec = params.get("equipment") or []
    equipment_items = equipment_spec if isinstance(equipment_spec, list) else [equipment_spec]
    equipment_days = {}
    equipment_units = {}
    equipment_sources = {}
    for equipment in equipment_items:
        if not equipment.get("table"):
            continue
        equipment_table = tables[equipment["table"]]["values"]
        if equipment["name"] not in equipment_table:
            return {"status": "unresolvable", "reason": f"{equipment['table']}: 행 '{equipment['name']}' 없음"}
        equipment_column, error = _axis_key(equipment_table[equipment["name"]],
                                            equipment.get("column_input", equipment.get("column",
                                                          crew.get("column_input", crew.get("column")))),
                                            validated, "열", equipment["table"])
        if error:
            return {"status": "unresolvable", "reason": error}
        equipment_count, equipment_source = _cell(tables, equipment["table"], equipment["name"], equipment_column)
        if equipment_count < 0:
            return {"status": "rejected", "reason": "명세 오류: 장비 대수가 음수임", "input": "spec"}
        equipment_days[equipment["name"]] = _exact_text(work_days * equipment_count)
        equipment_units[equipment["name"]] = equipment["unit"]
        equipment_sources[equipment["name"]] = {
            "equipment": equipment_source, "work_days": "work_days",
            "formula": "work_days × equipment_count", "citations": equipment_source["citations"]}
        equipment_value = equipment_count * 8 / daily_volume
        if equipment_count:
            unit_lines.append({
                "kind": "equipment", "name": equipment["name"], "unit": f"hr/{quantity_unit}",
                "exact": str(equipment_value), "applied": round_quantity(equipment_value, places),
                "places": places,
                "formula": f"{_exact_text(equipment_count)}대 × 8hr ÷ {daily_text}{quantity_unit}",
                "rule": rule_label, "source": f"{equipment_source['table']} {equipment_source['source']}",
                "citations": equipment_source["citations"],
            })

    from backend.agent.tools.calc.adjustments import apply_adjustments
    adjusted = apply_adjustments(spec, validated, unit_lines)
    if adjusted["status"] != "computed":
        return adjusted
    for line in unit_lines:
        if line.get("adjustments") and line["kind"] == "labor":
            person_days[line["name"]] = _exact_text(Fraction(line["exact"]) * quantity)

    return {
        "status": "computed",
        "daily_volume_m3": _exact_text(daily_volume),
        "work_days": _exact_text(work_days),
        "person_days": person_days,
        "equipment_days": equipment_days,
        "equipment_units": equipment_units,
        "unit_lines": unit_lines,
        "adjustment_memos": adjusted["memos"],
        "unit_basis": {
            "per": f"1{quantity_unit}", "daily_output": daily_text, "places": places,
            "adjustable_note": "1-2-8은 조정 가능 조항. 기본 자릿수 적용",
        },
        "provenance": {
            "daily_volume_m3": {
                "base_output": base_source,
                "coefficients": coefficient_sources,
                "formula_source": spec["quantity_model"]["source"],
                "citations": base_source["citations"] + [citation for source in coefficient_sources
                                                        for citation in source["citations"]],
            },
            "work_days": {
                "quantity_input": quantity_name,
                "quantity": _exact_text(quantity),
                "quantity_source": by_name[quantity_name]["source"],
                "daily_volume_m3": "daily_volume_m3",
                "formula": "quantity ÷ daily_volume_m3",
                "citations": base_source["citations"] + [citation for source in coefficient_sources
                                                        for citation in source["citations"]],
            },
            "person_days": person_sources,
            "equipment_days": equipment_sources,
        },
        "not_calculated": spec["not_calculated"],
    }
