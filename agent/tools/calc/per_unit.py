"""표에 직접 적힌 단위당 품을 추측 없이 읽어 계산한다."""

from __future__ import annotations

import re
from fractions import Fraction

from agent.tools.calc.daily_crew import _exact_text, _validate, check_blocked
from agent.tools.calc.numbers import parse_fraction
from agent.tools.source.citation import cite_table


def clean_label(value: str) -> str:
    """공백과 표의 머리글 접두어만 제거한다. 구분자는 보기 이름에서 뺀다."""
    parts = []
    for part in value.split("|"):
        part = re.sub(r"\s+", "", part)
        # 머리글은 각 구분자 뒤에서도 반복될 수 있다. 실제 직종·조건 글자는 보존한다.
        part = re.sub(r"^(?:(?:수량|구분|작업조|단위))", "", part)
        if part:
            parts.append(part)
    return " ".join(parts)


def _key(value: str) -> str:
    return clean_label(value).replace(" ", "")


def _unresolvable(table: str, row: str, column: str, reason: str) -> dict:
    return {"status": "unresolvable", "reason": f"{table}: 행 '{row}', 열 '{column}' — {reason}"}


def per_unit(spec: dict, inputs: dict) -> dict:
    fields = {field["name"]: field for field in spec["inputs"]}
    validated = {}
    for name, value in inputs.items():
        if name not in fields:
            return {"status": "rejected", "reason": f"알 수 없는 입력: {name}"}
        if value is None:
            continue
        checked, error = _validate(fields[name], value)
        if error:
            return {"status": "rejected", "reason": error}
        validated[name] = checked
    missing = [name for name, field in fields.items() if field["required"] and name not in validated]
    if missing:
        return {"status": "ask", "missing": missing}
    blocked = check_blocked(spec, validated)
    if blocked:
        return {"status": "blocked", **blocked}

    params = spec["quantity_model"]["params"]
    rate = params["unit_rate_table"]
    table_id = rate["table"]
    if params.get("surcharges") or params.get("note_adjustments"):
        return _unresolvable(table_id, str(rate.get("row_input", "")),
                             str(rate.get("column_input", "")), "할증·보정 규칙 미지원")
    tables = {table["id"]: table for table in spec["tables"]}
    table = tables.get(table_id)
    if table is None:
        return _unresolvable(table_id, str(rate.get("row_input", "")),
                             str(rate.get("column_input", "")), "표 없음")
    unit_match = re.fullmatch(r"인/(\d+)?(.+)", re.sub(r"\s+", "", table.get("unit", "")))
    if unit_match is None:
        return _unresolvable(table_id, str(rate.get("row_input", "")),
                             str(rate.get("column_input", "")), "기준 단위 파싱 실패")
    base = int(unit_match.group(1) or "1")
    quantity_unit = unit_match.group(2)
    quantity_name = params["quantity_input"]
    if fields[quantity_name]["unit"] != quantity_unit:
        return _unresolvable(table_id, str(rate.get("row_input", "")),
                             str(rate.get("column_input", "")), "물량 단위 불일치")
    row_ref = rate.get("row_input")
    col_ref = rate.get("column_input")
    if row_ref is None and len(table["values"]) != 1:
        return _unresolvable(table_id, "", "", "행 지정 없음")
    row_word = str(validated.get(row_ref, row_ref)) if row_ref is not None else ""
    col_word = str(validated.get(col_ref, col_ref)) if col_ref is not None else ""
    lines = []
    sources = {}
    for trade in rate["trades"]:
        rows = ([next(iter(table["values"]))] if row_ref is None else
                [name for name in table["values"]
                 if _key(trade) in _key(name) and _key(row_word) in _key(name)])
        if len(rows) != 1:
            return _unresolvable(table_id, f"{row_word} + {trade}", col_word,
                                 f"행 후보 {len(rows)}개")
        row = rows[0]
        columns = list(table["values"][row])
        if col_ref is None:
            if len(columns) != 1:
                return _unresolvable(table_id, row_word, col_word, "열 지정 없음")
            matches = columns
        else:
            exact_columns = [name for name in columns if _key(name) == _key(col_word)]
            matches = exact_columns or [name for name in columns if _key(col_word) in _key(name)]
        if len(matches) != 1:
            return _unresolvable(table_id, row_word, col_word, f"열 후보 {len(matches)}개")
        column = matches[0]
        raw = table["values"][row][column]
        try:
            value = parse_fraction(raw) / base
        except (ValueError, ZeroDivisionError):
            return _unresolvable(table_id, row_word, col_word, "셀 값 파싱 실패")
        if value < 0:
            return _unresolvable(table_id, row_word, col_word, "음수 품")
        citation = cite_table(table_id, row, column, raw)
        line = {"kind": "labor", "name": trade, "unit": f"인/{quantity_unit}",
                "exact": str(value), "applied": _exact_text(value), "places": 0,
                "formula": f"{raw}인 ÷ {base}{quantity_unit}",
                "rule": "표 단위당 품 그대로 적용(반올림 없음)",
                "source": f"{table_id} {table['source']}", "citations": [citation]}
        lines.append(line)
        sources[trade] = {"table": table_id, "row": row, "column": column,
                          "value": raw, "citations": [citation]}
    return {"status": "computed", "unit_lines": lines,
            "unit_basis": {"per": f"1{quantity_unit}", "daily_output": "",
                           "places": 0, "adjustable_note": "표 단위당 품을 정확히 적용"},
            "provenance": {"unit_rates": sources, "quantity_input": quantity_name,
                           "quantity": _exact_text(validated[quantity_name])},
            "not_calculated": spec["not_calculated"]}
