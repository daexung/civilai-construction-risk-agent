"""명세의 표와 조건만으로 일당 작업조형 기본 품량을 계산한다."""

from __future__ import annotations

import operator
import re
from fractions import Fraction
from typing import Any

from backend.agent.rules.conditions import price_fields
from backend.agent.tools.calc.unit_rounding import round_quantity, unit_places
from backend.agent.rules.quantity_units import quantity_unit as quantity_unit_of
from backend.agent.tools.calc.numbers import parse_fraction, parse_table_number
from backend.agent.tools.source.citation import cite_table, resolve_cites


_COMPARISONS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
    "in": lambda value, choices: value in choices,
    "not_in": lambda value, choices: value not in choices,
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
        if number < field.get("minimum", 0):
            return None, f"{name}는 {field.get('minimum', 0)} 이상의 정수여야 함"
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
    if kind == "percentage":
        try:
            number = parse_fraction(value)
        except (ValueError, ZeroDivisionError):
            return None, f"{name}는 0 이상 100 미만의 정확한 백분율이어야 함"
        minimum = parse_fraction(field.get("minimum", 0))
        maximum = parse_fraction(field.get("maximum", 100))
        if number < minimum or number > maximum:
            return None, f"{name}는 {minimum} 이상 {maximum} 이하이어야 함"
        return number, None
    if kind == "source_reference":
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 300:
            return None, f"{name}은 1~300자의 출처여야 함"
        return value.strip(), None
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


def _cell(tables: dict, table_id: str, row: str, column: str) -> tuple[Fraction | None, dict]:
    table = tables[table_id]
    values = table["values"]
    row_key = str(row).lower() if isinstance(row, bool) and str(row).lower() in values else row
    row_values = values[row_key]
    column_key = (str(column).lower() if isinstance(column, bool)
                  and str(column).lower() in row_values else column)
    raw = row_values[column_key]
    try:
        value = parse_table_number(raw)
        parse_error = None
    except (ValueError, ZeroDivisionError):
        # A dash or other nonnumeric source cell is not zero and must not escape
        # as an uncontextualized execution exception. Keep the exact cell and
        # citation so the caller can fail closed with a source-backed reason.
        value = None
        parse_error = "표 셀에 계산 가능한 수치가 없음"
    return value, {"table": table_id, "row": row_key, "column": column_key, "value": raw,
                   "source": table["source"], "parse_error": parse_error,
                   "citations": [cite_table(table_id, row, column, raw)]}


def _unavailable_cell(source: dict) -> dict:
    return {"status": "unresolvable",
            "reason": (f"{source['table']} 표 셀 ({source['row']}, {source['column']}) "
                       f"원문 값 {source['value']!r}: {source['parse_error']}"),
            "citations": source["citations"]}


def _axis_key(values: dict, reference: str | dict | None, inputs: dict,
              axis: str, table_id: str, *, context: dict | None = None) -> tuple[str | None, str | None]:
    """Select one declared axis key; compound selectors must have one unique match."""
    if isinstance(reference, list):
        # Alternative inputs that each apply under a different `when` (e.g. diameter per method).
        present = [name for name in reference if name in inputs]
        if len(present) != 1:
            return None, f"{table_id}: {axis} 선택 입력 {len(present)}개 (후보 {reference})"
        reference = present[0]
    if reference is None:
        if len(values) == 1:
            return next(iter(values)), None
        return None, f"{table_id}: {axis} 지정 없음 (후보 {len(values)}개)"
    if isinstance(reference, dict):
        input_name = reference.get("input")
        if input_name not in inputs:
            return None, f"{table_id}: {axis} 선택 입력 없음 '{input_name}'"
        range_tokens = []
        if reference.get("ranges"):
            try:
                actual = parse_fraction(inputs[input_name])
                ranges = []
                for item in reference["ranges"]:
                    lower = parse_fraction(item["min"]) if "min" in item else None
                    upper = parse_fraction(item["max"]) if "max" in item else None
                    lower_ok = (True if lower is None else
                                actual >= lower if item.get("min_inclusive", True) else actual > lower)
                    upper_ok = (True if upper is None else
                                actual <= upper if item.get("max_inclusive", True) else actual < upper)
                    if lower_ok and upper_ok:
                        ranges.append(item)
            except (ValueError, TypeError, KeyError):
                return None, f"{table_id}: {axis} 범위 입력 해석 불가 '{input_name}'"
            if len(ranges) != 1:
                return None, f"{table_id}: {axis} 범위 구간 후보 {len(ranges)}개"
            range_tokens = [str(ranges[0]["contains"])]
        selected_value = reference.get("value_map", {}).get(
            str(inputs[input_name]), inputs[input_name])
        tokens = [str(token).replace("{value}", str(selected_value))
                  .replace("{trade}", str((context or {}).get("trade", "")))
                  for token in reference.get("contains", [])]
        exact_tokens = []
        for selector_input in reference.get("exact_input_contains", []):
            if selector_input not in inputs:
                return None, f"{table_id}: {axis} 선택 입력 없음 '{selector_input}'"
            exact_tokens.append(str(inputs[selector_input]))
        exact_components = []
        for selector_input in reference.get("exact_component_inputs", []):
            if selector_input not in inputs:
                return None, f"{table_id}: {axis} 선택 입력 없음 '{selector_input}'"
            exact_components.append(str(inputs[selector_input]))
        for selector_input in reference.get("input_contains", []):
            if selector_input == "{trade}":
                tokens.append(str((context or {}).get("trade", "")))
                continue
            if selector_input not in inputs:
                return None, f"{table_id}: {axis} 선택 입력 없음 '{selector_input}'"
            tokens.append(str(inputs[selector_input]))
        # A token that only applies when its (conditionally asked) input was supplied, e.g. plate type.
        for selector_input in reference.get("optional_input_contains", []):
            if selector_input in inputs:
                tokens.append(str(inputs[selector_input]))
        tokens.extend(str(token).replace("{trade}", str((context or {}).get("trade", "")))
                      for token in range_tokens)
        if not tokens:
            return None, f"{table_id}: {axis} 복합 선택 조건 없음"
        def compact(value: object) -> str:
            return re.sub(r"[\s()（）]", "", str(value)).replace("×", "x").casefold()
        matches = [key for key in values
                   if all(compact(token) in compact(key) for token in tokens)
                   and all(compact(token) in [compact(part) for part in re.split(r"[\s|/×]+", str(key))]
                           for token in exact_components)
                   and all(re.search(rf"(?<!\d){re.escape(compact(token))}(?!\d)", compact(key))
                           for token in exact_tokens)]
        if len(matches) == 1:
            return matches[0], None
        return None, f"{table_id}: {axis} 복합 조건 후보 {len(matches)}개"
    key = inputs.get(reference, reference)
    if isinstance(reference, str) and "{trade}" in reference:
        key = reference.replace("{trade}", str((context or {}).get("trade", "")))
    if key not in values:
        normalized = re.sub(r"[\s()（）]", "", str(key)).replace("×", "x").casefold()
        matches = [candidate for candidate in values
                   if normalized and normalized in re.sub(r"[\s()（）]", "", str(candidate)).replace("×", "x").casefold()]
        if len(matches) == 1:
            return matches[0], None
        return None, f"{table_id}: {axis} '{key}' 없음 (정규화 후보 {len(matches)}개)"
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
        conditions = item.get("blocked_if_all") or ([item["blocked_if"]] if item.get("blocked_if") else [])
        if not conditions or any(condition.get("input") not in validated for condition in conditions):
            continue
        matches = []
        for condition in conditions:
            field = by_name.get(condition["input"])
            if field is None:
                return {"status": "unresolvable", "reason": f"보류 조건 입력 명세 없음: {condition['input']}"}
            expected = condition["value"]
            if field["type"] in ("positive_rational", "positive_currency", "nonnegative_integer"):
                try:
                    expected = parse_fraction(expected)
                except ValueError:
                    return {"status": "unresolvable", "reason":
                            f"숫자 보류 조건 해석 불가: {condition['input']} {condition['op']} {condition['value']}",
                            "input": condition["input"]}
            try:
                matches.append(_COMPARISONS[condition["op"]](validated[condition["input"]], expected))
            except (TypeError, KeyError):
                return {"status": "unresolvable", "reason":
                        f"보류 조건 비교 불가: {condition['input']} {condition['op']} {condition['value']}",
                        "input": condition["input"]}
        if all(matches):
            return {"reason": item["reason"], "source": item["source"],
                    "input": [condition["input"] for condition in conditions],
                    "citations": resolve_cites(item.get("cite"))}
    return None


def adjusted_daily_crew(spec: dict, inputs: dict, *, labor_only: bool = False,
                        daily_output_adjustments: list[dict] | None = None) -> dict:
    """검사 → 누락 질문 → 보류 판정 → 정확한 기본 품량 순으로 처리한다.

    labor_only=True(품 산출 모드)일 때만 가격 조건(관급/사급·자재 단가)이 없어도 품을 계산한다.
    """
    fields = spec["inputs"]
    optional = price_fields(spec) if labor_only else frozenset()
    by_name = {field["name"]: field for field in fields}
    tables = {table["id"]: table for table in spec["tables"]}

    def selected_table_id(config: dict) -> str:
        selector = config.get("table_selector") or {}
        if not selector:
            return config["table"]
        input_name = selector["input"]
        choices = selector["values"]
        selected = choices.get(str(inputs.get(input_name)))
        if selected not in tables:
            raise KeyError(f"No source table route for {input_name}={inputs.get(input_name)!r}")
        return selected

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

    # An input whose own `when` condition is not met is not part of this case (e.g. plate type
    # for a post-installation item); drop it so selectors and rules never read a stale value.
    pruning = True
    while pruning:
        pruning = False
        for field in fields:
            when = field.get("when")
            if when and field["name"] in validated and validated.get(when["input"]) != when["equals"]:
                del validated[field["name"]]
                pruning = True
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
    base_table_id = selected_table_id(base)
    base_table = tables[base_table_id]["values"]
    base_row, error = _axis_key(base_table, base.get("row_selector", base.get("row_input", base.get("row"))),
                                validated, "행", base_table_id,
                                context={"trade": base.get("trade", "")})
    if error:
        return {"status": "unresolvable", "reason": error}
    base_column, error = _axis_key(base_table[base_row], base.get("column_selector", base.get("column_input", base.get("column"))),
                                   validated, "열", base_table_id)
    if error:
        return {"status": "unresolvable", "reason": error}
    base_value, base_source = _cell(tables, base_table_id, base_row, base_column)
    if base_value is None:
        return _unavailable_cell(base_source)
    source_cell_override = (base.get("citation_overrides", {}).get(base_row, {})
                            .get(base_column))
    if source_cell_override:
        source_citations = [cite_table(base_table_id, source_cell_override["row"],
                                       source_cell_override["column"], base_source["value"])]
        for related in source_cell_override.get("related_citations", []):
            source_citations.append(cite_table(base_table_id, related["row"],
                                                related["column"], related.get("value")))
        base_source["citations"] = source_citations
        base_source["source_cell"] = {key: source_cell_override[key]
                                       for key in ("row", "column")}
    daily_volume = base_value
    coefficient_sources = []
    for coefficient in params.get("coefficients", []):
        input_value = validated[coefficient["input"]]
        if input_value in coefficient.get("skip_values", []):
            continue
        if input_value in coefficient.get("unsupported_values", []):
            return {"status": "unresolvable", "reason":
                    f"{coefficient['table']} {coefficient['row']}: 복수 조건의 결합 방식이 원문에 명시되지 않음",
                    "input": coefficient["input"]}
        coefficient_table_id = coefficient["table"]
        selector = coefficient.get("table_selector") or {}
        if selector:
            selector_input = selector.get("input")
            selected = selector.get("values", {}).get(str(validated.get(selector_input)))
            if selector_input not in validated or selected not in tables:
                return {"status": "unresolvable", "reason":
                        f"{coefficient_table_id}: 계수표 경로 선택 불가 ({selector_input})"}
            coefficient_table_id = selected
        coefficient_column = input_value
        if coefficient.get("selector_mode") == "threshold":
            # Source headers define ordered upper bounds and, optionally, a final
            # open-ended "초과" band. Select from the source labels themselves.
            try:
                actual = parse_fraction(input_value)
                row = tables[coefficient_table_id]["values"][coefficient["row"]]
                bounded, open_ended = [], []
                for label in row:
                    match = re.search(
                        r"([\d,]+(?:\.\d+)?)\s*(?:㎡|㎥|m²|m³)?\s*(이하|초과)", str(label))
                    if not match:
                        raise ValueError("unrecognized source band")
                    bound = parse_fraction(match.group(1).replace(",", ""))
                    (bounded if match.group(2) == "이하" else open_ended).append((bound, label))
                bounded.sort(key=lambda item: item[0])
                if (not bounded or len(open_ended) != 1
                        or any(bounded[i][0] >= bounded[i + 1][0]
                               for i in range(len(bounded) - 1))
                        or open_ended[0][0] != bounded[-1][0]):
                    raise ValueError("source bands are not a unique ordered partition")
                coefficient_column = next(
                    (label for bound, label in bounded if actual <= bound), open_ended[0][1])
            except (ValueError, KeyError, TypeError, ZeroDivisionError):
                return {"status": "unresolvable", "reason":
                        f"{coefficient_table_id} {coefficient['row']}: 원문 구간 선택이 유일하지 않음"}
        value, source = _cell(tables, coefficient_table_id, coefficient["row"], coefficient_column)
        if value is None:
            return _unavailable_cell(source)
        if coefficient.get("interpretation") == "signed_percentage_change":
            if not str(source["value"]).strip().endswith("%"):
                return {"status": "unresolvable", "reason":
                        f"{source['table']} {source['row']} {source['column']}: 퍼센트 조정값이 아님",
                        "citations": source["citations"]}
            value += 1
        daily_volume *= value
        coefficient_sources.append(source)
    unmodified_output = daily_volume
    # Module modifiers apply to the computed output, never to the source table.
    # This keeps the cited table cell faithful to the published base value.
    output_adjustment_trace = []
    declared_output_adjustments = list(daily_output_adjustments or [])
    for rule in params.get("output_adjustments", []):
        when = rule.get("when", {})
        if when and all(validated.get(name) == expected for name, expected in when.items()):
            adjustment = {**rule, "citations": resolve_cites(rule.get("cite"))}
            if rule.get("value_input"):
                input_name = rule["value_input"]
                if input_name not in validated:
                    return {"status": "unresolvable", "reason":
                            f"output adjustment input missing: {input_name}"}
                adjustment["value"] = _exact_text(validated[input_name])
            declared_output_adjustments.append(adjustment)
    for adjustment in declared_output_adjustments:
        operation = adjustment.get("operation")
        operand = parse_fraction(adjustment.get("value"))
        before = daily_volume
        if operation == "multiply_output":
            daily_volume *= operand
        elif operation == "add_output":
            daily_volume += operand
        elif operation == "set_output_percent":
            daily_volume = unmodified_output * (1 - operand / 100)
        elif operation == "subtract_percent_per_count":
            count_name = adjustment.get("count_input")
            if count_name not in validated:
                return {"status": "unresolvable", "reason":
                        f"output adjustment count input missing: {count_name}"}
            count = validated[count_name]
            if count < 0:
                return {"status": "rejected", "reason": "명세 오류: 반복 감산 횟수가 음수임", "input": "spec"}
            daily_volume *= 1 - operand * count / 100
        else:
            return {"status": "rejected", "reason": f"지원하지 않는 일당시공량 보정: {operation}"}
        if daily_volume <= 0:
            return {"status": "rejected", "reason": "보정 후 일당시공량은 0보다 커야 합니다"}
        output_adjustment_trace.append({**adjustment, "before": _exact_text(before),
                                        "after": _exact_text(daily_volume)})
    if daily_volume <= 0:
        return {"status": "rejected", "reason": "명세의 일당시공량이 0 이하임", "input": "spec"}

    places = unit_places(daily_volume)
    quantity_name = params["quantity_input"]
    quantity_unit = quantity_unit_of(by_name[quantity_name], validated)
    daily_text = _exact_text(daily_volume)
    magnitude = "1단위이하" if daily_volume < 10 else f"{10 ** (places - 2):,}단위"
    rule_label = f"1-2-8 {magnitude}→소수 {places}자리, 1-2-1 반올림"
    unit_lines = []
    quantity = validated[quantity_name]
    work_days = quantity / daily_volume
    # Some source tables define equipment output without a labor crew.
    # Preserve that source structure and calculate only the declared equipment.
    crew = params.get("crew") or {}
    crew_table_id = selected_table_id(crew) if crew else None
    crew_table = tables[crew_table_id]["values"] if crew else {}
    person_days = {}
    person_sources = {}
    trade_input = crew.get("trade_selector_input")
    trades = (crew.get("trades_by_input", {}).get(str(validated.get(trade_input)), [])
              if trade_input else crew.get("trades", []))
    for trade in trades:
        if crew.get("row_input"):
            crew_row, error = _axis_key(crew_table, crew["row_input"], validated,
                                        "행", crew_table_id, context={"trade": trade})
        else:
            crew_row, error = _axis_key(crew_table, crew.get("row_selector", trade), validated,
                                        "행", crew_table_id, context={"trade": trade})
        if error:
            return {"status": "unresolvable", "reason": error}
        column_ref = crew.get("column_selector_by_trade", {}).get(
            trade, crew.get("column_selector", crew.get("column_input",
                  crew.get("column_template", crew.get("column")))))
        column, error = _axis_key(crew_table[crew_row], column_ref, validated, "열", crew_table_id,
                                  context={"trade": trade})
        if error:
            return {"status": "unresolvable", "reason": error}
        count, crew_source = _cell(tables, crew_table_id, crew_row, column)
        if count is None:
            return _unavailable_cell(crew_source)
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

    additional_labor = []
    for rule in params.get("additional_unit_labor", []):
        when = rule.get("when", {})
        if when and not all(validated.get(name) == expected for name, expected in when.items()):
            continue
        trade = rule.get("trade")
        quantity_input = rule.get("quantity_input", quantity_name)
        rate_unit = rule.get("unit")
        if not isinstance(trade, str) or not trade:
            return {"status": "unresolvable", "reason":
                    f"additional labor trade is not declared by the source crew: {trade}"}
        if quantity_input not in validated or not rate_unit:
            return {"status": "unresolvable", "reason":
                    f"additional labor quantity or rate unit is missing: {trade}"}
        try:
            rate = parse_fraction(rule["rate"])
            # Reuse the same dimension-checked unit conversion as per-unit rates.
            from backend.agent.tools.calc.per_unit import conversion, parse_basis
            basis = parse_basis(rule.get("basis") or rate_unit)
            unit_factor = conversion(by_name[quantity_input].get("unit"), basis[1]) if basis else None
            if basis is None or unit_factor is None or rate < 0:
                return {"status": "unresolvable", "reason":
                        f"additional labor source basis does not match {quantity_input}: {trade}"}
            unit_rate = rate * unit_factor / basis[0]
            total = unit_rate * validated[quantity_input]
        except (KeyError, ValueError, ZeroDivisionError, TypeError):
            return {"status": "unresolvable", "reason":
                    f"additional labor source rate is invalid: {trade}"}
        person_days[trade] = _exact_text(parse_fraction(person_days.get(trade, "0")) + total)
        citations = resolve_cites(rule.get("cite"))
        additional_labor.append({"trade": trade, "quantity_input": quantity_input,
                                 "unit_rate": _exact_text(unit_rate), "total": _exact_text(total),
                                 "unit": rate_unit, "source": rule.get("source"),
                                 "citations": citations})
        unit_lines.append({"kind": "labor", "name": trade, "unit": rate_unit,
                           "exact": _exact_text(unit_rate), "applied": _exact_text(unit_rate),
                           "places": None,
                           "formula": rule.get("formula", f"{rule['rate']} × {quantity_input}"),
                           "rule": "source additional unit labor rate",
                           "source": rule.get("source", spec["quantity_model"].get("source")),
                           "citations": citations})
    for entry in additional_labor:
        person_sources.setdefault(entry["trade"], {})["additional_unit_labor"] = entry

    equipment_spec = params.get("equipment") or []
    equipment_items = equipment_spec if isinstance(equipment_spec, list) else [equipment_spec]
    equipment_days = {}
    equipment_units = {}
    equipment_sources = {}
    for equipment in equipment_items:
        when = equipment.get("when", {})
        if when and not all(validated.get(name) == expected for name, expected in when.items()):
            continue
        literal_count = equipment.get("count")
        if not equipment.get("table") and literal_count is None:
            continue
        equipment_table_id = selected_table_id(equipment) if equipment.get("table") else None
        equipment_table = tables[equipment_table_id]["values"] if equipment_table_id else {}
        if literal_count is not None and not equipment.get("table"):
            # A count stated in a note rather than a table cell (e.g. "add one more roller").
            equipment_name = equipment["name"]
            equipment_count = parse_fraction(literal_count)
            equipment_source = {"table": "원문 비고", "row": None, "column": None, "value": str(literal_count),
                                "source": equipment.get("source", ""),
                                "citations": resolve_cites(equipment.get("cite"))}
        elif equipment.get("row_from") == "base_output":
            equipment_row = base_row
            row_values = equipment_table.get(equipment_row, {})
            name_column = equipment.get("name_column")
            quantity_column = equipment.get("quantity_column", equipment.get("column"))
            if name_column not in row_values or quantity_column not in row_values:
                return {"status": "unresolvable", "reason":
                        f"{equipment_table_id}: selected row lacks equipment columns"}
            equipment_name = str(row_values[name_column]).strip()
            equipment_column = quantity_column
            equipment_count, equipment_source = _cell(
                tables, equipment_table_id, equipment_row, equipment_column)
            if equipment_count is None:
                return _unavailable_cell(equipment_source)
            equipment_source["citations"].append(
                cite_table(equipment_table_id, equipment_row, name_column, row_values[name_column]))
            equipment_source["row"] = equipment_row
        else:
            equipment_name = equipment.get("name")
            if equipment.get("row_selector") is not None:
                equipment_row, error = _axis_key(
                    equipment_table, equipment["row_selector"], validated,
                    "row", equipment_table_id,
                    context={"trade": equipment.get("trade", equipment_name)})
                if error:
                    return {"status": "unresolvable", "reason": error}
            else:
                equipment_row = equipment.get("row", equipment_name)
            if equipment_row not in equipment_table:
                return {"status": "unresolvable", "reason":
                        f"{equipment_table_id}: row '{equipment_row}' not found"}
            equipment_column, error = _axis_key(equipment_table[equipment_row],
                                                equipment.get("column_input", equipment.get("column",
                                                              crew.get("column_input", crew.get("column")))),
                                                validated, "column", equipment_table_id)
            if error:
                return {"status": "unresolvable", "reason": error}
            equipment_count, equipment_source = _cell(
                tables, equipment_table_id, equipment_row, equipment_column)
            if equipment_count is None:
                return _unavailable_cell(equipment_source)
        if equipment_count < 0:
            return {"status": "rejected", "reason": "명세 오류: 장비 대수가 음수임", "input": "spec"}
        if equipment_count == 0 and equipment.get("omit_if_zero"):
            # The selected crew group lists no such equipment (a grouped table row), so it is not used here.
            continue
        equipment_days[equipment_name] = _exact_text(
            Fraction(equipment_days.get(equipment_name, "0")) + work_days * equipment_count)
        equipment_units[equipment_name] = equipment.get("unit", "대")
        equipment_sources[equipment_name] = {
            "equipment": equipment_source, "work_days": "work_days",
            "formula": "work_days × equipment_count", "citations": equipment_source["citations"]}
        equipment_value = equipment_count * 8 / daily_volume
        if equipment_count:
            unit_lines.append({
                "kind": "equipment", "name": equipment_name, "unit": f"hr/{quantity_unit}",
                "exact": str(equipment_value), "applied": round_quantity(equipment_value, places),
                "places": places,
                "formula": f"{_exact_text(equipment_count)}대 × 8hr ÷ {daily_text}{quantity_unit}",
                "rule": rule_label, "source": f"{equipment_source['table']} {equipment_source['source']}",
                "citations": equipment_source["citations"],
            })
        continue

    for allowance in params.get("daily_equipment_allowances", []):
        when = allowance.get("when", {})
        if not when or not all(validated.get(name) == expected for name, expected in when.items()):
            continue
        hours = parse_fraction(allowance["hours_per_day"])
        if hours < 0:
            return {"status": "rejected", "reason": "명세 오류: 일일 장비시간이 음수임", "input": "spec"}
        name = allowance["name"]
        equipment_days[name] = _exact_text(work_days)
        equipment_units[name] = "hr/day"
        source = {"table": allowance.get("table"), "row": allowance.get("row"),
                  "column": allowance.get("column"), "value": allowance["hours_per_day"],
                  "source": allowance["source"], "citations": resolve_cites(allowance.get("cite"))}
        equipment_sources[name] = {"equipment": source, "work_days": "work_days",
                                   "formula": "work_days × source hours_per_day",
                                   "citations": source["citations"]}
        unit_value = hours / daily_volume
        unit_lines.append({"kind": "equipment", "name": name, "unit": f"hr/{quantity_unit}",
                           "exact": _exact_text(unit_value), "applied": round_quantity(unit_value, places),
                           "places": places, "formula": f"{_exact_text(hours)}hr ÷ {daily_text}{quantity_unit}",
                           "rule": rule_label, "source": source["source"],
                           "citations": source["citations"]})

    material_sources = {}
    for material in params.get("materials", []):
        when = material.get("when", {})
        if when and not all(validated.get(name) == expected for name, expected in when.items()):
            continue
        material_table_id = material["table"]
        material_table = tables[material_table_id]["values"]
        if material.get("row_selector") is not None:
            row, error = _axis_key(material_table, material["row_selector"], validated,
                                   "행", material_table_id)
            if error:
                return {"status": "unresolvable", "reason": error}
        elif material.get("row_input") is not None:
            row, error = _axis_key(material_table, material["row_input"], validated,
                                   "행", material_table_id)
            if error:
                return {"status": "unresolvable", "reason": error}
        else:
            row = material.get("row")
        if row not in material_table:
            return {"status": "unresolvable", "reason": f"{material_table_id}: 행 '{row}' 없음"}
        column, error = _axis_key(material_table[row], material.get("column_selector"),
                                  validated, "열", material_table_id)
        if error:
            return {"status": "unresolvable", "reason": error}
        rate, source = _cell(tables, material_table_id, row, column)
        name = material["name"]
        if rate is None and material.get("range_policy") == "preserve":
            parts = re.findall(r"\d+(?:\.\d+)?", str(source["value"]))
            if len(parts) == 2:
                lower, upper = (parse_fraction(part) * quantity for part in parts)
                material_sources[name] = {"rate": source, "quantity_input": quantity_name,
                                          "quantity": _exact_text(quantity),
                                          "formula": "quantity ? source rate interval",
                                          "range": [_exact_text(lower), _exact_text(upper)]}
                unit_lines.append({"kind": "material_range", "name": name, "unit": material["unit"],
                                   "minimum": _exact_text(lower), "maximum": _exact_text(upper),
                                   "exact": f"{_exact_text(lower)}~{_exact_text(upper)}",
                                   "applied": f"{_exact_text(lower)}~{_exact_text(upper)}",
                                   "places": None,
                                   "formula": f"{_exact_text(quantity)} ? source rate {source['value']}",
                                   "source": source["source"], "citations": source["citations"]})
                continue
        if rate is None:
            return _unavailable_cell(source)
        total = quantity * rate
        material_sources[name] = {"rate": source, "quantity_input": quantity_name,
                                  "quantity": _exact_text(quantity), "formula": "quantity ? source rate"}
        unit_lines.append({"kind": "material", "name": name, "unit": material["unit"],
                           "exact": _exact_text(total), "applied": _exact_text(total),
                           "places": None, "formula": f"{_exact_text(quantity)} ? {_exact_text(rate)}",
                           "source": source["source"], "citations": source["citations"]})

    # Additional source-defined activities can use a different quantity
    # basis/output cell (e.g. area installation plus joint length). Keep these
    # rows declarative and combine only their computed labor quantities.
    for task in params.get("additional_work", []):
        when = task.get("when", {})
        if when and not all(validated.get(name) == expected for name, expected in when.items()):
            continue
        task_quantity_name = task["quantity_input"]
        task_quantity = validated.get(task_quantity_name)
        if task_quantity is None:
            return {"status": "unresolvable", "reason":
                    f"additional work quantity input missing: {task_quantity_name}"}
        task_base = task["base_output"]
        # Task output cells may depend on declared inputs (e.g. panel size), like the main output.
        task_values = tables[task_base["table"]]["values"]
        task_row, error = _axis_key(task_values, task_base.get("row_input", task_base.get("row")),
                                    validated, "행", task_base["table"])
        if error:
            return {"status": "unresolvable", "reason": error}
        task_column, error = _axis_key(task_values[task_row],
                                       task_base.get("column_input", task_base.get("column")),
                                       validated, "열", task_base["table"])
        if error:
            return {"status": "unresolvable", "reason": error}
        task_output, output_source = _cell(tables, task_base["table"], task_row, task_column)
        if task_output is None:
            return _unavailable_cell(output_source)
        if task_output <= 0:
            return {"status": "unresolvable", "reason":
                    f"{task_base['table']}: additional-work output must be positive",
                    "citations": output_source["citations"]}
        task_days = task_quantity / task_output
        for task_trade in task.get("crew", []):
            display_trade = task.get("add_to_trade", task_trade)
            task_crew, crew_source = _cell(
                tables, task["crew_table"], task_trade, task["crew_column"])
            if task_crew is None:
                return _unavailable_cell(crew_source)
            added_days = task_days * task_crew
            previous = Fraction(next((line["exact"] for line in unit_lines
                                      if line.get("kind") == "labor"
                                      and line.get("name") == display_trade), "0"))
            unit_value = previous + added_days / quantity
            person_days[display_trade] = _exact_text(
                Fraction(person_days.get(display_trade, "0")) + added_days)
            unit_lines.append({
                "kind": "labor", "name": display_trade, "unit": f"인/{quantity_unit}",
                "exact": _exact_text(unit_value), "applied": round_quantity(unit_value, places),
                "places": places,
                "formula": (f"{_exact_text(task_quantity)} ÷ {_exact_text(task_output)} × "
                            f"{_exact_text(task_crew)} ÷ {_exact_text(quantity)}"),
                "source": f"{crew_source['table']} {crew_source['source']}",
                "citations": output_source["citations"] + crew_source["citations"],
                "task_source": task.get("source"),
            })
            # API/export code reads provenance for every trade in person_days; a trade that only
            # exists in this task needs its own entry (an existing main-crew entry is kept).
            person_sources.setdefault(display_trade, {
                "crew": crew_source, "rules": [], "adjusted_crew": _exact_text(task_crew),
                "work_days": "task_work_days", "formula": "task_work_days × crew",
                "citations": output_source["citations"] + crew_source["citations"],
                "task_source": task.get("source")})
        for task_equipment in task.get("equipment", []):
            count, count_source = _cell(tables, task_equipment["table"], task_equipment["row"],
                                        task_equipment["column"])
            if count is None:
                return _unavailable_cell(count_source)
            equipment_name = task_equipment["name"]
            equipment_days[equipment_name] = _exact_text(
                Fraction(equipment_days.get(equipment_name, "0")) + task_days * count)
            equipment_units[equipment_name] = task_equipment.get("unit", "대")
            unit_lines.append({
                "kind": "equipment", "name": equipment_name, "unit": f"hr/{by_name[task_quantity_name]['unit']}",
                "exact": _exact_text(count * 8 / task_output),
                "applied": round_quantity(count * 8 / task_output, places), "places": places,
                "formula": f"{_exact_text(count)}대 × 8hr ÷ {_exact_text(task_output)}",
                "source": f"{count_source['table']} {count_source['source']}",
                "citations": output_source["citations"] + count_source["citations"],
                "task_source": task.get("source"),
            })
            equipment_sources.setdefault(equipment_name, {
                "equipment": count_source, "work_days": "task_work_days",
                "formula": "task_work_days × equipment_count",
                "citations": output_source["citations"] + count_source["citations"]})

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
                "output_adjustments": output_adjustment_trace,
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
            "materials": material_sources,
        },
        "not_calculated": spec["not_calculated"],
    }
