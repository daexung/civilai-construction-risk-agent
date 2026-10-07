"""표에 직접 적힌 단위당 품을 추측 없이 읽어 계산한다."""

from __future__ import annotations

import re
import unicodedata
from fractions import Fraction

from backend.agent.rules.conditions import price_fields
from backend.agent.tools.calc.daily_crew import _exact_text, _validate, check_blocked
from backend.agent.tools.calc.adjustments import apply_adjustments
from backend.agent.tools.calc.numbers import parse_fraction, parse_table_number
from backend.agent.tools.calc.price import select_rate_version
from backend.agent.tools.source.citation import _chunks, cite_table


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


def parse_basis(unit: str | None) -> tuple[int, str] | None:
    """품의 분모만 읽는다. 분자의 인/시간 표기는 표의 직종 열에서 결정한다."""
    if unit is None:
        return None
    compact = unicodedata.normalize("NFKC", unit).replace(" ", "").replace(",", "")
    compact = compact.strip("()")
    compact = re.sub(r"^(?:인(?:,?hr)?|hr|대)/", "", compact)
    compact = compact.removesuffix("당")
    match = re.fullmatch(r"(\d+)?(㎡|m2|㎥|m3|m|km|kg|t|ton|개|개소|층)", compact, re.I)
    if not match:
        return None
    name = match.group(2).lower().replace("m2", "㎡").replace("m3", "㎥")
    return int(match.group(1) or 1), name


def conversion(input_unit: str, table_unit: str) -> Fraction | None:
    """입력 물량 하나가 표 기준 물량 몇 개인지 나타내는 정확한 비율."""
    units = {"m": ("length", 1), "km": ("length", 1000),
             "㎡": ("area", 1), "㎥": ("volume", 1),
             "kg": ("mass", 1), "t": ("mass", 1000), "ton": ("mass", 1000),
             "개": ("piece", 1), "개소": ("place", 1), "층": ("floor", 1)}
    parsed = parse_basis(input_unit)
    if parsed is None:
        return None
    count, name = parsed
    if name not in units or table_unit not in units:
        return None
    family, scale = units[name]
    target_family, target_scale = units[table_unit]
    return Fraction(count * scale, target_scale) if family == target_family else None


def _material_unit(table_id: str, row: str, name: str) -> str:
    chunk = next((item for item in _chunks() if item.get("chunk_id") == table_id), None)
    if chunk:
        for text in chunk["text"].splitlines():
            if _key(row) in _key(text) and _key(name) in _key(text):
                match = re.search(r"단위\s*([㎏kgℓL㎡㎥m³t개]+)", text)
                if match:
                    return match.group(1).replace("㎏", "kg")
    return "단위 미확인"


def per_unit(spec: dict, inputs: dict, *, labor_only: bool = False) -> dict:
    """labor_only=True(품 산출 모드)일 때만 가격 조건이 없어도 품을 계산한다."""
    fields = {field["name"]: field for field in spec["inputs"]}
    optional = price_fields(spec) if labor_only else frozenset()
    validated = {}
    for name, value in inputs.items():
        if re.fullmatch(r"apply_adj_\d+", name):
            if value not in ("예", "아니오"):
                return {"status": "rejected", "reason": f"{name}는 예 또는 아니오여야 함"}
            validated[name] = value
            continue
        if name not in fields:
            return {"status": "rejected", "reason": f"알 수 없는 입력: {name}"}
        if value is None:
            continue
        checked, error = _validate(fields[name], value)
        if error:
            return {"status": "rejected", "reason": error}
        validated[name] = checked
    missing = [name for name, field in fields.items()
               if field["required"] and name not in validated and name not in optional]
    if missing:
        return {"status": "ask", "missing": missing}
    blocked = check_blocked(spec, validated)
    if blocked:
        return {"status": "blocked", **blocked}

    params = spec["quantity_model"]["params"]
    rate = params["unit_rate_table"]
    table_id = rate["table"]
    tables = {table["id"]: table for table in spec["tables"]}
    table = tables.get(table_id)
    if table is None:
        return _unresolvable(table_id, str(rate.get("row_input", "")),
                             str(rate.get("column_input", "")), "표 없음")
    input_unit = fields[params["quantity_input"]]["unit"]
    raw_basis = table.get("unit")
    basis = parse_basis(raw_basis)
    unit_warning = None
    if basis is None and (raw_basis is None or raw_basis == "ℓ, 인"):
        basis = (1, input_unit or "단위")
        unit_warning = "단위 표기 없음: 표의 분모를 1단위로 적용"
    if basis is None:
        return _unresolvable(table_id, str(rate.get("row_input", "")),
                             str(rate.get("column_input", "")), "기준 단위 파싱 실패")
    base, quantity_unit = basis
    quantity_name = params["quantity_input"]
    factor = Fraction(1) if unit_warning else conversion(input_unit, quantity_unit)
    if factor is None:
        return _unresolvable(table_id, str(rate.get("row_input", "")),
                             str(rate.get("column_input", "")),
                             f"물량 단위 불일치: 입력 {input_unit}, 표 {table.get('unit', '')}")
    row_ref = rate.get("row_input")
    col_ref = rate.get("column_input")
    row_word = str(validated.get(row_ref, row_ref)) if row_ref is not None else ""
    col_word = str(validated.get(col_ref, col_ref)) if col_ref is not None else ""
    lines = []
    sources = {}
    material_columns = []
    for trade in rate["trades"]:
        if row_ref is None:
            rows = [name for name in table["values"] if _key(trade) in _key(name)]
            if not rows and len(table["values"]) == 1:
                rows = list(table["values"])
        else:
            rows = [name for name in table["values"]
                    if _key(trade) in _key(name) and _key(row_word) in _key(name)]
            if not rows:
                rows = [name for name in table["values"] if _key(row_word) == _key(name)]
            if not rows and row_ref not in validated:
                rows = [name for name in table["values"] if _key(trade) == _key(name)]
        if len(rows) != 1:
            return _unresolvable(table_id, f"{row_word} + {trade}", col_word,
                                 f"행 후보 {len(rows)}개")
        row = rows[0]
        columns = list(table["values"][row])
        if col_ref is None:
            trade_columns = [name for name in columns if _key(trade) == _key(name)]
            if not trade_columns:
                trade_columns = [name for name in columns if _key(trade) in _key(name)]
            if trade_columns:
                matches = trade_columns
                material_columns = [name for name in columns if name not in trade_columns]
            elif len(columns) != 1:
                return _unresolvable(table_id, row_word, col_word, "열 지정 없음")
            else:
                matches = columns
        else:
            exact_columns = [name for name in columns if _key(name) == _key(col_word)]
            matches = exact_columns or [name for name in columns if _key(col_word) in _key(name)]
        if len(matches) != 1:
            return _unresolvable(table_id, row_word, col_word, f"열 후보 {len(matches)}개")
        column = matches[0]
        raw = table["values"][row][column]
        try:
            value = parse_table_number(raw) * factor / base
        except (ValueError, ZeroDivisionError):
            return _unresolvable(table_id, row_word, col_word, "셀 값 파싱 실패")
        if value < 0:
            return _unresolvable(table_id, row_word, col_word, "음수 품")
        citation = cite_table(table_id, row, column, raw)
        line = {"kind": "labor", "name": trade, "unit": f"인/{input_unit}",
                "exact": str(value), "applied": _exact_text(value), "places": 0,
                "formula": f"{raw}인 × {factor} ÷ {base}{quantity_unit}",
                "rule": "표 단위당 품 그대로 적용(반올림 없음)",
                "source": f"{table_id} {table['source']}", "citations": [citation]}
        lines.append(line)
        sources[trade] = {"table": table_id, "row": row, "column": column,
                          "value": raw, "citations": [citation]}
        for name in material_columns:
            if name in rate["trades"] or any(line["name"] == name for line in lines):
                continue
            material_raw = table["values"][row][name]
            try:
                material_value = parse_table_number(material_raw) * factor / base
            except (ValueError, ZeroDivisionError):
                continue
            if material_value < 0:
                return _unresolvable(table_id, row, name, "음수 재료량")
            material_unit = _material_unit(table_id, row, name)
            version = select_rate_version("2026-10-01")
            labor_names = {entry["name"] for entry in version["rates"].values()} if version else set()
            kind = ("labor" if name in labor_names else "equipment" if material_unit in ("hr", "대")
                    else "material")
            numerator_unit = "인" if kind == "labor" else material_unit
            material_citation = cite_table(table_id, row, name, material_raw)
            lines.append({"kind": kind, "name": name, "unit": f"{numerator_unit}/{input_unit}",
                          "exact": str(material_value), "applied": _exact_text(material_value), "places": 0,
                          "formula": f"{material_raw}{material_unit} × {factor} ÷ {base}{quantity_unit}",
                          "rule": ("재료 단가 자료 없음(사용자 입력 기능 예정)" if kind == "material"
                                   else "표 단위당 품 그대로 적용(반올림 없음)"),
                          "source": f"{table_id} {table['source']}", "citations": [material_citation]})
    if row_ref is None and col_ref is not None:
        version = select_rate_version("2026-10-01")
        labor_names = {entry["name"] for entry in version["rates"].values()} if version else set()
        for name, columns in table["values"].items():
            if name in rate["trades"] or any(line["name"] == name for line in lines):
                continue
            candidates = [column for column in columns if _key(column) == _key(col_word)]
            if len(candidates) != 1:
                continue
            column = candidates[0]
            raw = columns[column]
            try:
                value = parse_table_number(raw) * factor / base
            except (ValueError, ZeroDivisionError):
                continue
            if value < 0:
                return _unresolvable(table_id, name, column, "음수 품")
            kind = "labor" if name in labor_names else "material"
            material_unit = ("인" if kind == "labor" else "ℓ" if raw_basis == "ℓ, 인"
                             else _material_unit(table_id, name, name))
            citation = cite_table(table_id, name, column, raw)
            lines.append({"kind": kind, "name": name, "unit": f"{material_unit}/{input_unit}",
                          "exact": str(value), "applied": _exact_text(value), "places": 0,
                          "formula": f"{raw}{material_unit} × {factor} ÷ {base}{quantity_unit}",
                          "rule": ("재료 단가 자료 없음(사용자 입력 기능 예정)" if kind == "material"
                                   else "표 단위당 품 그대로 적용(반올림 없음)"),
                          "source": f"{table_id} {table['source']}", "citations": [citation]})
    adjusted = apply_adjustments(spec, validated, lines)
    if adjusted["status"] != "computed":
        return adjusted
    return {"status": "computed", "unit_lines": lines, "adjustment_memos": adjusted["memos"],
            "warnings": [unit_warning] if unit_warning else [],
            "unit_basis": {"per": f"1{quantity_unit}", "daily_output": "",
                           "places": 0, "adjustable_note": "표 단위당 품을 정확히 적용"},
            "provenance": {"unit_rates": sources, "quantity_input": quantity_name,
                           "quantity": _exact_text(validated[quantity_name])},
            "not_calculated": spec["not_calculated"]}
