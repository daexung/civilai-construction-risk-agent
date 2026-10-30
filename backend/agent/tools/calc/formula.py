"""Bounded declarative quantity formulas with source-table rate support."""
from __future__ import annotations

from fractions import Fraction
from typing import Any

from backend.agent.tools.calc.daily_crew import _exact_text, _validate, check_blocked
from backend.agent.tools.calc.generated import _evaluate_expr, _rule_matches
from backend.agent.tools.calc.numbers import parse_fraction, parse_table_number
from backend.agent.tools.calc.per_unit import conversion, parse_basis
from backend.agent.tools.source.citation import cite_table, resolve_cites


def _formula_field_applies(field: dict, inputs: dict) -> bool:
    condition = field.get("required_when") or field.get("when")
    if not isinstance(condition, dict):
        return True
    actual = inputs.get(condition.get("input"))
    if "equals" in condition:
        return actual == condition["equals"]
    if isinstance(condition.get("in"), list):
        return actual in condition["in"]
    return False


def formula_quantity(spec: dict, inputs: dict) -> dict:
    fields = {field["name"]: field for field in spec.get("inputs", [])}
    validated: dict[str, Any] = {}
    for name, value in inputs.items():
        if name not in fields:
            return {"status": "rejected", "reason": f"알 수 없는 입력: {name}"}
        if value is None:
            continue
        checked, error = _validate(fields[name], value)
        if error:
            return {"status": "rejected", "reason": error, "input": name}
        validated[name] = checked
    for name in validated:
        if not _formula_field_applies(fields[name], validated):
            return {"status": "rejected", "reason": f"{name}는 선택한 분류에 적용되지 않습니다",
                    "input": name}
    dependency_sources = {}
    for dependency in spec.get("quantity_model", {}).get("params", {}).get("references", []):
        output_input = dependency.get("output_input")
        try:
            from backend.agent.rules.specs import load_specs
            referenced = load_specs().get(dependency["section_id"])
        except Exception:
            referenced = None
        if not referenced or not isinstance(output_input, str):
            return {"status": "unresolvable", "reason":
                    f"참조 명세를 하나로 확인할 수 없음: {dependency.get('section_id')}"}
        reference_inputs = {}
        for target_name, binding in dependency.get("inputs", {}).items():
            if "input" in binding:
                source_name = binding["input"]
                if source_name not in validated:
                    return {"status": "ask", "missing": [source_name],
                            "questions": [{"name": source_name, "ask": fields[source_name]["ask"],
                                          "allowed_values": fields[source_name].get("allowed_values")} ]}
                reference_inputs[target_name] = validated[source_name]
            elif "value" in binding:
                reference_inputs[target_name] = binding["value"]
            else:
                return {"status": "unresolvable", "reason": f"참조 입력 연결 형식 오류: {target_name}"}
        from backend.agent.tools.calc.per_unit import per_unit
        referenced_result = per_unit(referenced, reference_inputs, labor_only=True)
        if referenced_result.get("status") != "computed":
            return {"status": referenced_result.get("status", "unresolvable"),
                    "reason": f"참조 절 {dependency['section_id']} 계산 실패: {referenced_result.get('reason', '')}",
                    "reference": referenced_result, "input": output_input}
        resource_name = dependency.get("resource_name")
        lines = [line for line in referenced_result.get("unit_lines", [])
                 if line.get("name") == resource_name and line.get("kind") == "labor"]
        if len(lines) != 1:
            return {"status": "unresolvable", "reason":
                    f"참조 절 {dependency['section_id']}에서 직종 '{resource_name}' 단위율이 유일하지 않음"}
        line = lines[0]
        if line.get("unit") != dependency.get("expected_unit"):
            return {"status": "unresolvable", "reason":
                    f"참조 절 단위 불일치: {line.get('unit')} ≠ {dependency.get('expected_unit')}"}
        if output_input in validated:
            return {"status": "rejected", "reason": f"참조 결과 입력은 직접 덮어쓸 수 없음: {output_input}"}
        validated[output_input] = parse_fraction(line["exact"])
        dependency_sources[output_input] = {"section_id": dependency["section_id"],
                                            "unit": line["unit"], "value": line["exact"],
                                            "source": line["source"], "citations": line["citations"],
                                            "inputs": reference_inputs}
    missing = [name for name, field in fields.items()
               if (field.get("required") or isinstance(field.get("required_when"), dict)
                   or isinstance(field.get("when"), dict))
               and _formula_field_applies(field, validated) and name not in validated]
    if missing:
        return {"status": "ask", "missing": missing,
                "questions": [{"name": name, "ask": fields[name]["ask"],
                              "allowed_values": fields[name].get("allowed_values")} for name in missing]}

    params = spec.get("quantity_model", {}).get("params", {})
    for rule in params.get("conditional_ranges", []):
        if not all(validated.get(name) == expected for name, expected in rule.get("when", {}).items()):
            continue
        name = rule["input"]
        value = validated[name]
        minimum, maximum = parse_fraction(rule["minimum"]), parse_fraction(rule["maximum"])
        if value < minimum or value > maximum:
            return {"status": "rejected", "reason":
                    f"{name}는 원문 허용 범위 {_exact_text(minimum)}~{_exact_text(maximum)}를 벗어남",
                    "input": name, "source": rule.get("source"),
                    "citations": resolve_cites(rule.get("cite"))}

    blocked = check_blocked(spec, validated)
    if blocked:
        return {"status": "blocked", **blocked}
    for condition in params.get("blocked_conditions", []):
        try:
            matches = _rule_matches({"when_expr": condition["when_expr"]}, validated)
        except (KeyError, ValueError, ZeroDivisionError, TypeError) as exc:
            return {"status": "unresolvable", "reason":
                    f"공식 계산 보류 조건 해석 실패: {exc}"}
        if matches:
            return {"status": "blocked", "reason": condition["reason"],
                    "source": condition.get("source"),
                    "citations": resolve_cites(condition.get("cite"))}

    tables = {table["id"]: table for table in spec.get("tables", [])}
    derived_error = _apply_derived(params.get("derived", []), tables, validated, dependency_sources)
    if derived_error:
        return derived_error
    lines = []
    provenance = {}
    excluded_source_cells = []
    for output in params.get("outputs", []):
        when = output.get("when", {})
        if when and not all(validated.get(key) == value for key, value in when.items()):
            continue
        name = output.get("name", output.get("table", "table_rates"))
        if output.get("kind") == "formula":
            try:
                value = _evaluate_expr(output["expression"], validated)
            except (ValueError, ZeroDivisionError, TypeError) as exc:
                return {"status": "unresolvable", "reason": f"공식 해석 실패 ({name}): {exc}"}
            if value < 0:
                return {"status": "rejected", "reason": f"명세 오류: {name} 결과가 음수임", "input": "spec"}
            source = output.get("source") or spec["quantity_model"].get("source")
            citations = resolve_cites(output.get("cite"))
            for input_name in _input_refs(output["expression"]):
                if input_name in dependency_sources:
                    citations.extend(dependency_sources[input_name].get("citations", []))
            lines.append({"kind": output.get("resource_kind", "labor"), "name": name,
                          "exact": _exact_text(value), "applied": _exact_text(value),
                          "unit": output["unit"], "formula": output.get("formula", "declarative formula"),
                          "source": source, "citations": citations})
            provenance[name] = {"expression": output["expression"], "value": _exact_text(value),
                                "inputs": {key: _exact_text(validated[key]) if isinstance(validated[key], Fraction)
                                           else validated[key] for key in _input_refs(output["expression"])},
                                "input_sources": {key: (dependency_sources[key] if key in dependency_sources else
                                    {"source": fields[key].get("source"), "unit": fields[key].get("unit")})
                                                  for key in _input_refs(output["expression"])},
                                "references": {key: dependency_sources[key]
                                               for key in _input_refs(output["expression"])
                                               if key in dependency_sources},
                                "citations": citations}
            continue

        # Source-cell rate products support cases where a quantity is priced
        # from one exact table intersection and a second cited table supplies
        # an optional percentage on that rate (for example support labor as a
        # share of inspection labor). Keep both source cells in provenance.
        if output.get("kind") == "table_rate_product":
            source_table = tables.get(output.get("table"))
            quantity_name = output.get("quantity_input")
            row_name = output.get("row")
            column_name = output.get("column")
            if (source_table is None or quantity_name not in validated
                    or row_name not in (source_table or {}).get("values", {})
                    or column_name not in (source_table or {}).get("values", {}).get(row_name, {})):
                return {"status": "unresolvable", "reason":
                        f"{output.get('table')}: source rate cell or quantity input missing"}
            basis = parse_basis(source_table.get("unit", ""))
            quantity_unit = fields[quantity_name].get("unit")
            if basis is None:
                return {"status": "unresolvable", "reason":
                        f"{source_table['id']}: source rate unit is not a declared rate"}
            base_quantity, denominator_unit = basis
            quantity_factor = conversion(quantity_unit, denominator_unit)
            if quantity_factor is None:
                return {"status": "unresolvable", "reason":
                        f"{source_table['id']}: input unit {quantity_unit!r} does not match {denominator_unit!r}"}
            source_raw = source_table["values"][row_name][column_name]
            try:
                value = (validated[quantity_name] * quantity_factor / base_quantity
                         * parse_table_number(source_raw))
            except (ValueError, TypeError, ZeroDivisionError):
                return {"status": "unresolvable", "reason":
                        f"{source_table['id']}: invalid source rate at {row_name}/{column_name}"}
            citations = [cite_table(source_table["id"], row_name, column_name, source_raw)]
            multiplier = output.get("multiplier")
            multiplier_value = Fraction(1)
            multiplier_raw = None
            multiplier_cell = None
            if multiplier:
                multiplier_table = tables.get(multiplier.get("table"))
                selector_input = multiplier.get("column_input")
                multiplier_row = multiplier.get("row")
                if (multiplier_table is None or selector_input not in validated
                        or multiplier_row not in (multiplier_table or {}).get("values", {})):
                    return {"status": "unresolvable", "reason":
                            f"{multiplier.get('table')}: source multiplier table/input missing"}
                multiplier_cell = multiplier.get("column_value_map", {}).get(
                    str(validated[selector_input]), str(validated[selector_input]))
                multiplier_values = multiplier_table["values"][multiplier_row]
                if multiplier_cell not in multiplier_values:
                    return {"status": "unresolvable", "reason":
                            f"{multiplier_table['id']}: source multiplier cell {multiplier_cell!r} missing"}
                multiplier_raw = multiplier_values[multiplier_cell]
                try:
                    multiplier_value = parse_table_number(multiplier_raw)
                except (ValueError, TypeError, ZeroDivisionError):
                    return {"status": "unresolvable", "reason":
                            f"{multiplier_table['id']}: invalid source multiplier"}
                if multiplier_value < 0:
                    return {"status": "rejected", "reason":
                            f"{multiplier_table['id']}: negative source multiplier"}
                value *= multiplier_value
                citations.append(cite_table(multiplier_table["id"], multiplier_row,
                                            multiplier_cell, multiplier_raw))
            citations.extend(resolve_cites(output.get("cite")))
            name = output.get("name", row_name)
            if value < 0:
                return {"status": "rejected", "reason": f"명세 오류: {name} 결과가 음수임", "input": "spec"}
            formula_text = f"{validated[quantity_name]} × {source_raw}"
            if multiplier:
                formula_text += f" × {multiplier_raw}"
            lines.append({"kind": output.get("resource_kind", "labor"), "name": name,
                          "exact": _exact_text(value), "applied": _exact_text(value),
                          "unit": output.get("unit", source_table.get("unit", "")),
                          "formula": formula_text,
                          "source": output.get("source") or source_table.get("source"),
                          "citations": citations})
            provenance[name] = {"table": source_table["id"], "row": row_name,
                                "column": column_name, "source_rate": source_raw,
                                "quantity_input": quantity_name,
                                "quantity": _exact_text(validated[quantity_name]),
                                "multiplier": (None if not multiplier else {
                                    "table": multiplier_table["id"], "row": multiplier_row,
                                    "column": multiplier_cell, "source_rate": multiplier_raw,
                                    "exact": _exact_text(multiplier_value)}),
                                "result": _exact_text(value), "citations": citations}
            continue

        if output.get("kind") == "table_divisor":
            table = tables.get(output.get("table"))
            value_name = output.get("value_input")
            row_input = output.get("row_input")
            row_name = validated.get(row_input) if row_input else output.get("row")
            column_input = output.get("column_input")
            column_name = (validated.get(column_input) if column_input
                           else output.get("column"))
            if (table is None or value_name not in validated or value_name not in fields
                    or (row_input and row_input not in validated)
                    or row_name not in (table or {}).get("values", {})
                    or column_name not in (table or {}).get("values", {}).get(row_name, {})):
                return {"status": "unresolvable", "reason":
                        f"{output.get('table')}: table divisor declaration/input missing"}
            raw = table["values"][row_name][column_name]
            rate_unit = table.get("unit", "")
            if "/" not in rate_unit:
                return {"status": "unresolvable", "reason":
                        f"{table['id']}: source productivity unit must be a rate"}
            numerator_unit, denominator_unit = rate_unit.rsplit("/", 1)
            input_unit = fields[value_name].get("unit")
            unit_factor = conversion(input_unit, numerator_unit)
            if unit_factor is None:
                return {"status": "unresolvable", "reason":
                        f"{table['id']}: quantity unit {input_unit!r} does not match source-rate numerator {numerator_unit!r}"}
            try:
                rate_value = parse_table_number(raw)
                rate_multiplier = parse_fraction(output.get("rate_multiplier", "1"))
                if rate_multiplier <= 0:
                    return {"status": "rejected", "reason":
                            f"{table['id']}: source productivity multiplier must be positive"}
                rate_value *= rate_multiplier
                if rate_value <= 0:
                    return {"status": "rejected", "reason":
                            f"{table['id']}: source productivity must be positive"}
                result_value = validated[value_name] * unit_factor / rate_value
            except (ValueError, TypeError, ZeroDivisionError):
                return {"status": "unresolvable", "reason":
                        f"{table['id']}: source productivity cell is not numeric"}
            citation = cite_table(table["id"], row_name, column_name, raw)
            citations = [citation] if isinstance(citation, dict) else citation
            citations.extend(resolve_cites(output.get("cite")))
            name = output.get("name", table.get("role", table["id"]))
            unit = output.get("unit", denominator_unit)
            lines.append({"kind": output.get("resource_kind", "equipment"),
                          "name": name, "exact": _exact_text(result_value),
                          "applied": _exact_text(result_value), "unit": unit,
                          "formula": output.get("formula", f"{value_name} ÷ source productivity × { _exact_text(Fraction(1, 1) / rate_multiplier) if rate_multiplier != 1 else '1' }"),
                          "source": table.get("source", spec["quantity_model"].get("source")),
                          "citations": citations})
            provenance[name] = {"table": table["id"], "row": row_name,
                                "column": column_name, "source_rate": raw,
                                "source_unit": rate_unit,
                                "rate_multiplier": _exact_text(rate_multiplier),
                                "input": _exact_text(validated[value_name]),
                                "input_unit": input_unit,
                                "value": _exact_text(result_value),
                                "citations": citations}
            continue

        if output.get("kind") == "table_multiplier":
            table = tables.get(output.get("table"))
            input_name = output.get("selector_input")
            value_name = output.get("value_input")
            row_input = output.get("row_input")
            row_name = validated.get(row_input) if row_input else output.get("row")
            if (table is None or input_name not in validated or value_name not in validated
                    or (row_input and row_input not in validated)):
                return {"status": "unresolvable", "reason":
                        f"{output.get('table')}: table multiplier declaration/input missing"}
            row = table.get("values", {}).get(row_name)
            if not isinstance(row, dict):
                return {"status": "unresolvable", "reason": f"{table['id']}: row {row_name!r} missing"}
            selected = str(validated[input_name])
            try:
                if output.get("selector_mode") == "threshold":
                    selected_number = parse_fraction(selected)
                    bands = []
                    for label, raw in row.items():
                        match = __import__("re").search(r"([\d,]+(?:\.\d+)?)\s*(이상|미만)", label)
                        if match:
                            threshold = parse_fraction(match.group(1).replace(",", ""))
                            bands.append((threshold, match.group(2), label, raw))
                    lower = [band for band in bands if band[1] == "이상" and band[0] <= selected_number]
                    if lower:
                        _, _, column, raw = max(lower, key=lambda band: band[0])
                    else:
                        upper = [band for band in bands if band[1] == "미만"]
                        if not upper:
                            return {"status": "rejected", "reason":
                                    f"{table['id']}: selector {selected} is below the source table range"}
                        _, _, column, raw = min(upper, key=lambda band: band[0])
                else:
                    row_name = output.get("row_value_map", {}).get(str(row_name), row_name)
                    column = output.get("column_value_map", {}).get(selected, selected)
                    if column not in row:
                        return {"status": "unresolvable", "reason":
                                f"{table['id']}: source column {column!r} missing"}
                    raw = row[column]
                rate_value = parse_table_number(raw)
                if table.get("unit") == "%":
                    rate_value /= 100
                result_value = validated[value_name] * rate_value
                add_for = output.get("add_value_when_values")
                if (output.get("add_value_input")
                        and (add_for is None or selected in add_for)):
                    result_value += validated[output["add_value_input"]]
            except (ValueError, TypeError, ZeroDivisionError):
                return {"status": "unresolvable", "reason":
                        f"{table['id']}: no unique numeric source band for {selected}"}
            citation = cite_table(table["id"], row_name, column, raw)
            citations = [citation]
            citations.extend(resolve_cites(output.get("cite")))
            lines.append({"kind": output.get("resource_kind", "labor"), "name": name,
                          "exact": _exact_text(result_value), "applied": _exact_text(result_value),
                          "unit": output["unit"],
                          "formula": f"{_exact_text(validated[value_name])} × {raw}",
                          "source": output.get("source") or table.get("source"),
                          "citations": citations})
            provenance[name] = {"table": table["id"], "row": row_name,
                                "column": column, "rate": raw,
                                "value_input": value_name, "selector_input": input_name,
                                "result": _exact_text(result_value), "citations": citations}
            continue

        if output.get("kind") == "table_row_rates":
            table = tables.get(output.get("table"))
            quantity_name = output.get("quantity_input")
            selector = output.get("row_selector", {})
            if table is None or quantity_name not in validated:
                return {"status": "unresolvable", "reason":
                        f"{output.get('table')}: table row-rate declaration/input missing"}
            selector_inputs = selector.get("inputs", [])
            if not selector_inputs or any(key not in validated for key in selector_inputs):
                return {"status": "unresolvable", "reason": "table row selector inputs missing"}
            matches = [item for item in selector.get("value_map", [])
                       if all(validated.get(key) == value for key, value in item.get("when", {}).items())]
            if len(matches) != 1:
                return {"status": "rejected", "reason":
                        f"{table['id']}: input combination maps to {len(matches)} source rows"}
            row_name = matches[0].get("row")
            row_values = table.get("values", {}).get(row_name)
            if not isinstance(row_values, dict):
                return {"status": "unresolvable", "reason": f"{table['id']}: source row {row_name!r} missing"}
            basis = parse_basis(table.get("unit"))
            input_unit = fields[quantity_name].get("unit")
            factor = conversion(input_unit, basis[1]) if basis and input_unit else None
            if basis is None or factor is None:
                return {"status": "unresolvable", "reason":
                        f"{table['id']}: source basis/input unit mismatch"}
            quantity = validated[quantity_name] * factor / basis[0]
            for column in output.get("columns", list(row_values)):
                if column not in row_values:
                    return {"status": "unresolvable", "reason": f"{table['id']}: source column {column!r} missing"}
                raw = row_values[column]
                if raw == "-" and output.get("source_dash_means_excluded") is True:
                    excluded_source_cells.append({"table": table["id"], "row": row_name,
                                                  "column": column, "source_value": raw,
                                                  "source": table.get("source"),
                                                  "citations": [cite_table(table["id"], row_name, column, raw)]})
                    continue
                try:
                    amount = parse_table_number(raw) * quantity
                except (ValueError, ZeroDivisionError):
                    return {"status": "unresolvable", "reason":
                            f"{table['id']}: nonnumeric source cell {row_name!r}/{column!r}={raw!r}",
                            "citations": [cite_table(table["id"], row_name, column, raw)]}
                citation = cite_table(table["id"], row_name, column, raw)
                line_name = output.get("names", {}).get(column, column)
                unit = output.get("unit", basis[0] and basis[1])
                lines.append({"kind": output.get("resource_kind", "material"), "name": line_name,
                              "exact": _exact_text(amount), "applied": _exact_text(amount), "unit": unit,
                              "formula": f"{_exact_text(validated[quantity_name])} × {raw}/{basis[0]}{basis[1]}",
                              "source": table.get("source"), "citations": [citation]})
                provenance[line_name] = {"table": table["id"], "row": row_name, "column": column,
                                         "rate": raw, "quantity": _exact_text(validated[quantity_name]),
                                         "citations": [citation]}
            continue

        if output.get("kind") != "table_rates":
            return {"status": "unresolvable", "reason": f"지원하지 않는 공식 출력 형식: {output.get('kind')}"}
        table = tables.get(output.get("table"))
        if table is None:
            return {"status": "unresolvable", "reason": f"공식 출력 표 없음: {output.get('table')}"}
        input_name, quantity_name = output.get("column_input"), output.get("quantity_input")
        if input_name not in validated or quantity_name not in validated:
            return {"status": "unresolvable", "reason": f"{table['id']}: 선택/물량 입력 연결 누락"}
        basis = parse_basis(table.get("unit"))
        factor = conversion(fields[quantity_name].get("unit"), basis[1]) if basis else None
        if basis is None or factor is None:
            return {"status": "unresolvable", "reason": f"{table['id']}: 원문 분모 또는 입력 단위 해석 불가"}
        quantity = validated[quantity_name] * factor / basis[0]
        for row in output.get("rows", []):
            row_values = table["values"].get(row)
            if not isinstance(row_values, dict):
                return {"status": "unresolvable", "reason": f"{table['id']}: 행 '{row}' 없음"}
            column = output.get("column")
            if column is None:
                column = validated[input_name]
            if column not in row_values:
                return {"status": "unresolvable", "reason": f"{table['id']}: 열 '{column}' 없음"}
            raw = row_values[column]
            if raw == "-" and output.get("source_dash_means_excluded") is True:
                excluded_source_cells.append({"table": table["id"], "row": row,
                                              "column": column, "source_value": raw,
                                              "source": table.get("source"),
                                              "citations": [cite_table(table["id"], row, column, raw)]})
                continue
            try:
                value = parse_table_number(raw) * quantity
            except (ValueError, ZeroDivisionError):
                return {"status": "unresolvable", "reason":
                        f"{table['id']} 표 셀 ({row}, {column}) 원문 값 {raw!r}: 수치 해석 불가",
                        "citations": [cite_table(table["id"], row, column, raw)]}
            citation = cite_table(table["id"], row, column, raw)
            line_name = output.get("names", {}).get(row, row)
            unit = (row_values.get(output["unit_column"]) if output.get("unit_column")
                    else output.get("units", {}).get(row, table.get("unit")))
            if not isinstance(unit, str) or not unit.strip():
                return {"status": "unresolvable", "reason":
                        f"{table['id']}: 행 '{row}'의 단위 열 '{output.get('unit_column')}' 없음"}
            lines.append({"kind": output.get("resource_kind", "material"), "name": line_name,
                          "exact": _exact_text(value), "applied": _exact_text(value), "unit": unit,
                          "formula": f"{_exact_text(validated[quantity_name])} × {raw}/{_exact_text(basis[0])}{basis[1]}",
                          "source": table.get("source"), "citations": [citation]})
            provenance[line_name] = {"table": table["id"], "row": row, "column": column,
                                     "rate": raw, "quantity": _exact_text(validated[quantity_name]),
                                     "formula": "quantity ÷ source basis × table rate",
                                     "citations": [citation]}
    if not lines:
        return {"status": "unresolvable", "reason": "공식 출력 명세가 비어 있음"}
    return {"status": "computed", "unit_lines": lines, "provenance": provenance,
            "excluded_source_cells": excluded_source_cells,
            "not_calculated": spec.get("not_calculated", []),
            "scope_notes": {"blocked": spec.get("blocked", []),
                            "open_questions": spec.get("open_questions", [])},
            "rounding": spec["quantity_model"].get("rounding")}


def _apply_derived(derived: list, tables: dict, validated: dict, sources: dict) -> dict | None:
    """표 조회·조건부 가감으로 공식 입력을 파생한다(사이값 보간 없음, 원문 '-'는 막는다).

    table_cell: cases 중 when이 맞는 것이 정확히 하나여야 한다. Literal cases may declare value+citation;
    table cases use row/row_input, column/column_input/
    column_join(입력값을 sep으로 이은 문자열), exact_bands는 '10이하' 같은 라벨을 숫자 입력으로 고르는 규칙.
    sum_terms: when이 맞는 항의 value를 더한다(없으면 0). expression: 앞서 파생·입력된 값으로 식을 계산한다.
    """
    for item in derived:
        name = item["name"]
        if item["kind"] == "sum_terms":
            total = Fraction(0)
            for term in item.get("terms", []):
                if all(validated.get(k) == v for k, v in term.get("when", {}).items()):
                    total += parse_fraction(term["value"])
            validated[name] = total
            sources[name] = {"source": item.get("source"), "unit": item.get("unit"), "value": _exact_text(total),
                             "citations": resolve_cites(item.get("cite"))}
            continue
        if item["kind"] == "minimum":
            names = item.get("inputs", [])
            if len(names) < 2 or any(key not in validated for key in names):
                return {"status": "unresolvable", "reason":
                        f"{name}: minimum requires at least two resolved source values"}
            minimum = min(parse_fraction(validated[key]) for key in names)
            validated[name] = minimum
            citations = []
            for key in names:
                citations.extend(sources.get(key, {}).get("citations", []))
            sources[name] = {"source": item.get("source"), "unit": item.get("unit"),
                             "value": _exact_text(minimum), "operation": "minimum",
                             "inputs": {key: _exact_text(validated[key]) for key in names},
                             "citations": citations}
            continue
        if item["kind"] == "expression":
            try:
                value = _evaluate_expr(item["expression"], validated)
            except (ValueError, ZeroDivisionError, TypeError) as exc:
                return {"status": "unresolvable", "reason": f"파생 식 해석 실패 ({name}): {exc}"}
            if value <= 0:
                return {"status": "rejected", "reason": f"{name}: 계산 결과가 0 이하입니다({_exact_text(value)})"}
            validated[name] = value
            sources[name] = {"source": item.get("source"), "unit": item.get("unit"), "value": _exact_text(value),
                             "expression": item["expression"], "citations": resolve_cites(item.get("cite"))}
            continue
        if item["kind"] != "table_cell":
            return {"status": "unresolvable", "reason": f"지원하지 않는 파생 입력 형식: {item['kind']}"}
        cases = [case for case in item.get("cases", [{}])
                 if all(validated.get(k) == v for k, v in case.get("when", {}).items())]
        if len(cases) != 1:
            return {"status": "rejected", "reason": f"{name}: 입력 조합이 원문 표 {len(cases)}곳에 대응함(하나여야 함)"}
        case = cases[0]
        if "input_value" in case:  # 선택한 조건의 입력값을 그대로 쓴다(예: 토량변화율 L)
            source_name = case["input_value"]
            if source_name not in validated:
                return {"status": "unresolvable", "reason": f"{name}: 입력 누락 {source_name}"}
            validated[name] = parse_fraction(validated[source_name])
            sources[name] = {"source": case.get("source"), "unit": item.get("unit"),
                             "value": _exact_text(validated[name]), "input": source_name,
                             "citations": resolve_cites(case.get("cite"))}
            continue
        if "value" in case:
            try:
                value = parse_table_number(str(case["value"]))
            except (ValueError, ZeroDivisionError):
                return {"status": "unresolvable", "reason": f"{name}: literal source value is not numeric"}
            validated[name] = value
            citations = resolve_cites(case.get("cite"))
            sources[name] = {"source": case.get("source"), "unit": item.get("unit"),
                             "source_value": str(case["value"]), "value": _exact_text(value),
                             "citations": citations}
            continue
        table = tables.get(case["table"])
        if table is None:
            return {"status": "unresolvable", "reason": f"{name}: 표 없음 {case['table']}"}
        try:
            row = validated[case["row_input"]] if "row_input" in case else case["row"]
            if "column_join" in case:
                column = case.get("sep", " ").join(str(validated[key]) for key in case["column_join"])
            elif "column_input" in case:
                column = validated[case["column_input"]]
            else:
                column = case.get("column")
            if "bands" in item:  # 숫자 입력을 원문 구간 라벨로: 한계 이하 라벨 또는 정확히 같은 값만
                number = validated[item["band_input"]]
                label = next((b["label"] for b in item["bands"]
                              if (b.get("at_most") is not None and number <= parse_fraction(b["at_most"]))
                              or (b.get("equals") is not None and number == parse_fraction(b["equals"]))), None)
                if label is None:
                    return {"status": "rejected", "input": item["band_input"], "reason":
                            f"{item['band_input']}={_exact_text(number)}: 원문 표에 없는 값입니다(사이값은 정하지 않음)"}
                column = label
        except KeyError as exc:
            return {"status": "unresolvable", "reason": f"{name}: 입력 누락 {exc}"}
        cell = table.get("values", {}).get(str(row), {}).get(str(column))
        if cell is None:
            return {"status": "rejected", "reason": f"{name}: 원문 표 {table['id']}에 ({row}, {column}) 칸이 없습니다"}
        if cell.strip() in ("-", ""):
            return {"status": "rejected", "reason": f"{name}: 원문 표 {table['id']}의 ({row}, {column}) 칸은 '-'(해당 없음)입니다",
                    "citations": [cite_table(table["id"], str(row), str(column), cell)]}
        try:
            value = parse_table_number(cell)
        except (ValueError, ZeroDivisionError):
            return {"status": "unresolvable", "reason": f"{name}: 표 칸 {cell!r} 수치 해석 불가"}
        validated[name] = value
        citation = cite_table(table["id"], str(row), str(column), cell)
        sources[name] = {"table": table["id"], "row": str(row), "column": str(column), "source_value": cell,
                         "value": _exact_text(value), "unit": table.get("unit"), "source": table.get("source"),
                         "citations": [citation] if isinstance(citation, dict) else citation}
    return None


def _input_refs(expression: object) -> set[str]:
    if isinstance(expression, dict):
        result = set()
        if set(expression) == {"input"} and isinstance(expression["input"], str):
            result.add(expression["input"])
        else:
            for value in expression.values():
                result.update(_input_refs(value))
        return result
    if isinstance(expression, list):
        return set().union(*(_input_refs(item) for item in expression)) if expression else set()
    return set()
