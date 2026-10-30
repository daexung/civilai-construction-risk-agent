"""표에 직접 적힌 단위당 품을 추측 없이 읽어 계산한다."""

from __future__ import annotations

import re
import unicodedata
from math import ceil
from fractions import Fraction

from backend.agent.rules.conditions import price_fields, field_active
from backend.agent.tools.calc.daily_crew import _axis_key, _exact_text, _validate, check_blocked
from backend.agent.tools.calc.adjustments import apply_adjustments
from backend.agent.tools.calc.numbers import parse_fraction, parse_table_number
from backend.agent.tools.calc.price import select_rate_version
from backend.agent.tools.source.citation import _chunks, cite_table, resolve_cites


def clean_label(value: str) -> str:
    """공백과 표의 머리글 접두어만 제거한다. 구분자는 보기 이름에서 뺀다."""
    parts = []
    for part in value.split("|"):
        part = re.sub(r"\s+", "", part)
        # 머리글은 각 구분자 뒤에서도 반복될 수 있다. 실제 직종·조건 글자는 보존한다.
        # Bare axis labels are meaningful in small source tables (e.g. the
        # columns "단위" and "수량"). Strip them only when they prefix a more
        # specific label such as "수량(㎥)".
        if part not in ("수량", "구분", "작업조", "단위"):
            part = re.sub(r"^(?:(?:수량|구분|작업조|단위))", "", part)
        if part:
            parts.append(part)
    return " ".join(parts)


def _key(value: str) -> str:
    return (clean_label(value).replace(" ", "").replace("∼", "~")
            .replace("～", "~"))


def _select_parenthetical_source_value(raw: object, selector: dict | None,
                                       inputs: dict) -> tuple[str | None, str | None, str | None]:
    """Select a source's parenthetical alternative only under a declared input mapping."""
    text = str(raw).strip()
    if "(" not in text and ")" not in text:
        return text, None, None
    if selector and selector.get("mode") == "parenthetical_only":
        match = re.fullmatch(r"\(\s*([^()]+?)\s*\)", text)
        if match:
            return match.group(1).strip(), "parenthetical_only", None
        return None, None, "parenthetical-only selector requires one exact parenthesized source value"
    match = re.fullmatch(r"\s*([^()]+?)\s*\(\s*([^()]+?)\s*\)\s*", text)
    if not match or not selector:
        return None, None, "parenthetical source cell needs an explicit source-value selector"
    input_name = selector.get("input")
    if input_name not in inputs:
        return None, None, f"parenthetical source selector input missing: {input_name}"
    mode = selector.get("values", {}).get(str(inputs[input_name]))
    if mode == "primary":
        return match.group(1).strip(), mode, None
    if mode == "parenthetical":
        return match.group(2).strip(), mode, None
    return None, None, f"no exact parenthetical source-value route for {input_name}={inputs[input_name]!r}"


def _exact_axis_component(label: str, value: str) -> bool:
    """Match a source header component without matching a longer word around it."""
    label = unicodedata.normalize("NFKC", label).replace("∼", "~").replace("～", "~")
    value = unicodedata.normalize("NFKC", value).replace("∼", "~").replace("～", "~")
    if _key(label) == _key(value):
        return True
    # Korean/Latin letters and digits join header words; whitespace and
    # punctuation separate exact child-header components (e.g. 압력관 vs 비압력관).
    word = r"가-힣A-Za-z0-9"
    return re.search(rf"(?<![{word}]){re.escape(value)}(?![{word}])", label, re.I) is not None


def _unresolvable(table: str, row: str, column: str, reason: str) -> dict:
    return {"status": "unresolvable", "reason": f"{table}: 행 '{row}', 열 '{column}' — {reason}"}


_BASIS_UNITS = r"㎡|m2|㎥|m3|m|km|kg|t|ton|개|매|장|개소|층|l"


def _unit_key(value: str) -> str:
    compact = unicodedata.normalize("NFKC", value).strip().replace(" ", "")
    aliases = {"m2": "㎡", "m3": "㎥", "ton": "t", "톤": "t"}
    return aliases.get(compact.casefold(), compact.casefold())


def _parse_opaque_unit(value: str) -> tuple[int, str] | None:
    """Parse a quantity-unit token without asserting its physical dimension.

    Opaque units are usable only for exact unit identity in ``conversion``.
    This covers source denominators such as 대, 조, 필지, 매 and Joint without
    pretending that distinct domain units are interchangeable.
    """
    match = re.fullmatch(r"(?:(\d{1,3}(?:,\d{3})+|\d+))?([^\W\d_][\w·.-]*)", value, re.UNICODE)
    if not match:
        return None
    return int((match.group(1) or "1").replace(",", "")), match.group(2)


def parse_basis(unit: str | None) -> tuple[int, str] | None:
    """품의 분모만 읽는다. 분자의 인/시간 표기는 표의 직종 열에서 결정한다."""
    if unit is None:
        return None
    compact = unicodedata.normalize("NFKC", unit).replace(" ", "")
    compact = compact.strip("()")
    # Many standard-estimate tables express resource numerator over a quantity
    # denominator (for example 인·일/t or hr/㎥). Only the denominator controls
    # conversion of the supplied work quantity; keep the numerator opaque.
    if "/" in compact:
        numerator, denominator = compact.rsplit("/", 1)
        if numerator and denominator:
            compact = denominator
    compact = re.sub(r"^(?:인(?:,?hr)?|hr|대)/", "", compact)
    compact = compact.removesuffix("당")
    match = re.fullmatch(rf"(\d{{1,3}}(?:,\d{{3}})+|\d+)?({_BASIS_UNITS})", compact, re.I)
    if not match:
        # A slash explicitly identifies the quantity denominator. Preserve an
        # unfamiliar source unit as opaque; conversion will permit identity
        # only and will reject any unlike unit.
        if "/" not in unicodedata.normalize("NFKC", unit):
            return None
        return _parse_opaque_unit(compact)
    name = match.group(2).lower().replace("m2", "㎡").replace("m3", "㎥")
    return int((match.group(1) or "1").replace(",", "")), name


def conversion(input_unit: str, table_unit: str) -> Fraction | None:
    """입력 물량 하나가 표 기준 물량 몇 개인지 나타내는 정확한 비율."""
    if not isinstance(input_unit, str) or not isinstance(table_unit, str):
        return None
    units = {"m": ("length", 1), "km": ("length", 1000),
             "㎡": ("area", 1), "㎥": ("volume", 1),
             "kg": ("mass", 1), "t": ("mass", 1000),
             "개": ("piece", 1), "개소": ("place", 1), "층": ("floor", 1), "l": ("liquid", 1)}
    parsed = parse_basis(input_unit) or _parse_opaque_unit(
        unicodedata.normalize("NFKC", input_unit).replace(" ", ""))
    if parsed is None:
        return None
    count, name = parsed
    name_key, target_key = _unit_key(name), _unit_key(table_unit)
    if name_key not in units or target_key not in units:
        return Fraction(count) if name_key == target_key else None
    family, scale = units[name_key]
    target_family, target_scale = units[target_key]
    return Fraction(count * scale, target_scale) if family == target_family else None


def _material_unit(table_id: str, row: str, name: str) -> str:
    chunk = next((item for item in _chunks() if item.get("chunk_id") == table_id), None)
    if chunk:
        for text in chunk["text"].splitlines():
            if _key(row) in _key(text) and _key(name) in _key(text):
                match = re.search(r"단위\s*([A-Za-z]+|[㎏kgℓL㎡㎥m³t개]+)", text)
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
        if not field_active(fields[name], inputs, fields):
            continue
        if value is None:
            continue
        checked, error = _validate(fields[name], value)
        if error:
            return {"status": "rejected", "reason": error}
        validated[name] = checked
    missing = [name for name, field in fields.items()
               if field["required"] and name not in validated and name not in optional
               and field_active(field, validated, fields)]
    if missing:
        return {"status": "ask", "missing": missing}
    blocked = check_blocked(spec, validated)
    if blocked:
        return {"status": "blocked", **blocked}

    params = spec["quantity_model"]["params"]
    rate = params.get("unit_rate_table")
    if not isinstance(rate, dict) or "table" not in rate or "trades" not in rate:
        return _unresolvable("quantity_model", "", "",
                             "per_unit requires a declared unit_rate_table with table and trades")
    table_id = rate["table"]
    table_selector = rate.get("table_selector")
    if table_selector:
        if table_selector.get("routes") is not None:
            routes = table_selector.get("routes", [])
            invalid = [name for route in routes for name in route.get("when", {})
                       if name not in fields]
            if invalid:
                return _unresolvable(table_id, str(rate.get("row_input", "")),
                                     str(rate.get("column_input", "")),
                                     f"table selector must reference declared inputs: {sorted(set(invalid))}")
            matched_routes = [route for route in routes
                              if all(validated.get(name) == value
                                     for name, value in route.get("when", {}).items())]
            if len(matched_routes) != 1:
                return _unresolvable(table_id, str(rate.get("row_input", "")),
                                     str(rate.get("column_input", "")),
                                     f"no unique exact source table route (candidates {len(matched_routes)})")
            selected_table = matched_routes[0].get("table")
        else:
            selector_input = table_selector.get("input")
            selector_value = validated.get(selector_input)
            selected_table = table_selector.get("values", {}).get(str(selector_value))
            if not isinstance(selector_input, str) or selector_input not in fields:
                return _unresolvable(table_id, str(rate.get("row_input", "")),
                                     str(rate.get("column_input", "")),
                                     "table selector must reference a declared input")
        if not isinstance(selected_table, str):
            return _unresolvable(table_id, str(rate.get("row_input", "")),
                                 str(rate.get("column_input", "")),
                                 f"no exact source table route for {selector_input}={selector_value!r}")
        table_id = selected_table
    tables = {table["id"]: table for table in spec["tables"]}
    table = tables.get(table_id)
    if table is None:
        return _unresolvable(table_id, str(rate.get("row_input", "")),
                             str(rate.get("column_input", "")), "표 없음")
    row_input_by_table = rate.get("row_input_by_table", {})
    row_ref = row_input_by_table.get(table_id, rate.get("row_input"))
    if (table_id in row_input_by_table and row_ref is not None
            and (not isinstance(row_ref, str) or row_ref not in fields)):
        return _unresolvable(table_id, str(row_ref), str(rate.get("column_input", "")),
                             "selected row axis is not a declared input")
    row_value_map = rate.get("row_value_map_by_table", {}).get(
        table_id, rate.get("row_value_map", {}))
    trades_by_row = rate.get("trades_by_row", {})
    row_key_for_trades = None
    if row_ref is not None:
        row_key_for_trades = str(validated.get(row_ref, row_ref))
        row_key_for_trades = str(row_value_map.get(
            row_key_for_trades, row_key_for_trades))
    trades = trades_by_row.get(
        row_key_for_trades,
        rate.get("trades_by_table", {}).get(table_id, rate["trades"]))
    trade_routes = rate.get("trades_by_conditions", [])
    if trade_routes:
        matched_routes = [route for route in trade_routes
                          if route.get("when") and all(
                              validated.get(name) == expected
                              for name, expected in route["when"].items())]
        if len(matched_routes) != 1 or not isinstance(matched_routes[0].get("trades"), list):
            return _unresolvable(table_id, str(rate.get("row_input", "")),
                                 str(rate.get("column_input", "")),
                                 f"no unique exact resource route (candidates {len(matched_routes)})")
        trades = matched_routes[0]["trades"]
    ignored_columns = set(rate.get("ignored_columns_by_table", {}).get(table_id, ()))
    quantity_name = params.get("quantity_input")
    if isinstance(quantity_name, str) and "," in quantity_name:
        quantity_names = [name.strip() for name in quantity_name.split(",")]
    elif isinstance(quantity_name, list):
        quantity_names = quantity_name
    else:
        quantity_names = [quantity_name]
    if (not quantity_names or any(not isinstance(name, str) or name not in fields
                                  for name in quantity_names)):
        return _unresolvable(table_id, str(rate.get("row_input", "")),
                             str(rate.get("column_input", "")),
                             f"quantity_input must reference declared inputs: {quantity_name!r}")
    primary_name = quantity_names[0]
    raw_basis = table.get("unit")
    input_unit = fields[primary_name].get("unit")
    # Some source sections present parallel tables with different quantity
    # denominators (e.g. ea, ㎡ and m). Let the spec declare the exact unit for
    # each selected source table when the question's quantity unit is implicit
    # in the selected work type. Never infer a conversion between dimensions.
    quantity_unit_by_table = rate.get("quantity_unit_by_table", {})
    configured_quantity_unit = table_id in quantity_unit_by_table
    selected_quantity_unit = False
    if configured_quantity_unit:
        declared_input_unit = quantity_unit_by_table[table_id]
        if not isinstance(declared_input_unit, str) or not declared_input_unit:
            return _unresolvable(table_id, str(rate.get("row_input", "")),
                                 str(rate.get("column_input", "")),
                                 "selected table quantity unit must be a non-empty string")
        if input_unit is not None and _unit_key(input_unit) != _unit_key(declared_input_unit):
            return _unresolvable(table_id, str(rate.get("row_input", "")),
                                 str(rate.get("column_input", "")),
                                 "selected table quantity unit conflicts with input unit")
        input_unit = declared_input_unit
    unit_selector = rate.get("quantity_unit_selector")
    unit_selector_citations = []
    if unit_selector:
        unit_input = unit_selector.get("input")
        if unit_input not in validated:
            return _unresolvable(table_id, str(rate.get("row_input", "")),
                                 str(rate.get("column_input", "")),
                                 f"quantity unit selector input missing: {unit_input}")
        selected_unit = unit_selector.get("values", {}).get(str(validated[unit_input]))
        if not isinstance(selected_unit, str) or not selected_unit:
            return _unresolvable(table_id, str(validated.get(unit_input, "")), "",
                                 "no exact source quantity-unit route")
        input_unit = selected_unit
        configured_quantity_unit = True
        selected_quantity_unit = True
        unit_selector_citations = resolve_cites(
            unit_selector.get("cite_by_value", {}).get(str(validated[unit_input])))
    declared_basis = None
    basis_by_row = rate.get("basis_by_row", {})
    if basis_by_row:
        row_ref_for_basis = row_ref
        row_key_for_basis = str(validated.get(row_ref_for_basis, row_ref_for_basis))
        row_key_for_basis = str(row_value_map.get(row_key_for_basis, row_key_for_basis))
        declared_basis = basis_by_row.get(row_key_for_basis)
        if declared_basis is None:
            return _unresolvable(table_id, row_key_for_basis, "", "source row basis declaration missing")
    basis = parse_basis(declared_basis or raw_basis)
    unit_warning = None
    if (selected_quantity_unit and unit_selector.get("basis_by_selected_unit")):
        # A mixed-denominator source table can explicitly route one denominator
        # per selected row. In that opt-in mode, use that exact source-mapped
        # denominator rather than parsing the table-wide list as one unit.
        basis = (1, input_unit)
    elif basis is None and selected_quantity_unit:
        # Some source rows change between area and volume denominators. The
        # caller's exact work-type route declares the unit for this row.
        basis = (1, input_unit)
    elif basis is None and (raw_basis is None or raw_basis == "ℓ, 인"):
        basis = (1, input_unit or "단위")
        unit_warning = "단위 표기 없음: 표의 분모를 1단위로 적용"
    if basis is None:
        return _unresolvable(table_id, str(rate.get("row_input", "")),
                             str(rate.get("column_input", "")), "기준 단위 파싱 실패")
    base, quantity_unit = basis
    factor = (Fraction(1) if declared_basis and input_unit is None else
              Fraction(1) if unit_warning else conversion(input_unit, quantity_unit))
    if len(quantity_names) > 1 and not unit_warning:
        # A source denominator can be a product of independent quantities.
        # Require an explicit one-to-one match to every denominator component.
        normalized_basis = unicodedata.normalize("NFKC", str(raw_basis or ""))
        denominator = normalized_basis.rsplit("/", 1)[-1].strip(" ()")
        components = re.split(r"[·*×]", denominator)
        component_factors = []
        if len(components) == len(quantity_names):
            for name, component in zip(quantity_names, components):
                match = re.fullmatch(r"(?:(\d{1,3}(?:,\d{3})+|\d+))?(.+)", component)
                if not match:
                    component_factors = []
                    break
                count = int((match.group(1) or "1").replace(",", ""))
                component_factor = conversion(fields[name].get("unit"), match.group(2))
                if component_factor is None:
                    component_factors = []
                    break
                component_factors.append(component_factor / count)
        if len(component_factors) == len(quantity_names):
            factor = Fraction(1)
            for component_factor in component_factors:
                factor *= component_factor
        else:
            # Preserve explicit numerator-multiplier units such as mm/100㎡.
            normalized_basis = normalized_basis.removesuffix("당")
            numerator = normalized_basis.split("/", 1)[0] if "/" in normalized_basis else ""
            if (len(quantity_names) != 2
                    or _unit_key(fields[quantity_names[1]].get("unit") or "") != _unit_key(numerator)):
                return _unresolvable(table_id, str(rate.get("row_input", "")),
                                     str(rate.get("column_input", "")),
                                     f"compound quantity has no matching table numerator or denominator: {quantity_names!r}")
    if factor is None:
        return _unresolvable(table_id, str(rate.get("row_input", "")),
                             str(rate.get("column_input", "")),
                             f"물량 단위 불일치: 입력 {input_unit}, 표 {table.get('unit', '')}")
    coefficient_factor = Fraction(1)
    coefficient_combination = params.get("coefficient_combination", "additive_deltas")
    if coefficient_combination not in ("additive_deltas", "multiply"):
        return _unresolvable("coefficient_rules", "", "", "unsupported coefficient combination")
    coefficient_sources = []
    coefficient_citations = []
    for rule in params.get("coefficient_rules", []):
        source_table_id = rule["table"]
        source_table = tables.get(source_table_id)
        if source_table is None:
            return _unresolvable(source_table_id, "", "", "coefficient table missing")
        source_row_name = rule.get("row", "계수")
        if rule.get("kind") == "area_increment":
            area = Fraction(str(validated[rule["area_input"]]))
            if rule.get("land_input"):
                land = validated[rule["land_input"]]
                base_area = Fraction(str(rule["base_area_by_value"][land]))
            else:
                base_area = Fraction(str(rule["base_area"]))
            if area <= base_area:
                coefficient, cell = Fraction(1), "0회"
            else:
                # The source worked example gives n=4 for 7,000 / 1,500 m².
                n = ceil((area - base_area) / base_area)
                area_row = source_table.get("values", {}).get(rule.get("row", "계수"), {})
                one_increment_cells = [label for label in area_row
                                       if re.match(r"^1회(?:$|\d)",
                                                   re.sub(r"\s+", "", str(label)))]
                if n == 1 and len(one_increment_cells) == 1:
                    cell = one_increment_cells[0]
                    try:
                        coefficient = parse_table_number(area_row[cell])
                    except ValueError:
                        return _unresolvable(source_table_id, rule.get("row", "계수"), cell,
                                             "one-increment area coefficient is not numeric")
                elif n == 1:
                    return _unresolvable(source_table_id, rule.get("row", "계수"), "1회",
                                         "one-increment area source cell is missing or ambiguous")
                else:
                    coefficient, cell = Fraction(12, 10) + Fraction(n, 10), "2회이상"
        elif rule.get("row_input") and rule.get("column_input"):
            # Some source factors are two-axis matrices (for example, rail
            # weight × turnout type). Resolve each declared input by exact
            # normalized equality; substring/fuzzy axis selection is unsafe.
            normalize_axis = lambda value: re.sub(r"\s+", "", _key(str(value)))
            requested_row = normalize_axis(validated[rule["row_input"]])
            row_matches = [key for key in source_table.get("values", {})
                           if normalize_axis(key) == requested_row]
            if len(row_matches) != 1:
                return _unresolvable(source_table_id, str(validated[rule["row_input"]]), "",
                                     f"coefficient exact row candidates {len(row_matches)}")
            source_row_name = row_matches[0]
            source_row = source_table["values"][source_row_name]
            requested_column = normalize_axis(validated[rule["column_input"]])
            column_matches = [key for key in source_row
                              if normalize_axis(key) == requested_column]
            if len(column_matches) != 1:
                return _unresolvable(source_table_id, source_row_name,
                                     str(validated[rule["column_input"]]),
                                     f"coefficient exact column candidates {len(column_matches)}")
            cell = column_matches[0]
            try:
                coefficient = parse_table_number(source_row[cell])
            except ValueError:
                return _unresolvable(source_table_id, source_row_name, cell,
                                     "coefficient value is not numeric")
        else:
            row_name = rule.get("row", "계수")
            input_value = validated[rule["input"]]
            row = source_table["values"].get(row_name)
            if row is None:
                return _unresolvable(source_table_id, row_name, str(input_value), "coefficient row missing")
            normalize_coefficient = lambda value: re.sub(r"[\s()（）]", "", _key(str(value)))
            matches = [key for key in row
                       if normalize_coefficient(input_value) in normalize_coefficient(key)]
            if len(matches) != 1:
                return _unresolvable(source_table_id, row_name, str(input_value),
                                     f"coefficient candidates {len(matches)}")
            cell = matches[0]
            try:
                coefficient = parse_table_number(row[cell])
            except ValueError:
                return _unresolvable(source_table_id, row_name, cell, "coefficient value is not numeric")
            source_row_name = row_name
        if coefficient_combination == "multiply":
            coefficient_factor *= coefficient
        else:
            coefficient_factor += coefficient - 1
        source_row = source_table["values"].get(source_row_name, {})
        source_raw = ("1.0" if cell == "0회" else
                      source_row.get(cell, str(coefficient)))
        coefficient_citations.append(cite_table(source_table_id, source_row_name,
                                                cell, source_raw))
        coefficient_citations.extend(resolve_cites(rule.get("cite")))
        coefficient_sources.append({"table": source_table_id, "cell": cell,
                                    "coefficient": str(coefficient),
                                    "source_value": source_raw,
                                    "source": source_table.get("source", "")})
    if params.get("coefficient_combination_cite"):
        combination_citations = resolve_cites(params["coefficient_combination_cite"])
        if not combination_citations:
            return {"status": "blocked", "reason":
                    "coefficient combination rule citation is unresolved"}
        coefficient_citations.extend(combination_citations)
    if coefficient_factor <= 0:
        return _unresolvable("coefficient_rules", "", "", "combined coefficient is not positive")
    factor *= coefficient_factor
    quantity_label = (quantity_unit if (declared_basis and input_unit is None)
                      or selected_quantity_unit
                      or (configured_quantity_unit and fields[primary_name].get("unit") is None) else
                      "·".join(str(fields[name].get("unit") or name) for name in quantity_names))
    column_input_by_table = rate.get("column_input_by_table", {})
    column_value_by_table = rate.get("column_value_by_table", {})
    col_ref = column_value_by_table.get(
        table_id, column_input_by_table.get(table_id, rate.get("column_input")))
    row_word = str(validated.get(row_ref, row_ref)) if row_ref is not None else ""
    if (table_id in column_input_by_table and col_ref is not None
            and (not isinstance(col_ref, str) or col_ref not in fields)):
        return _unresolvable(table_id, row_word, str(col_ref),
                             "selected column axis is not a declared input")
    if row_ref is not None:
        row_word = str(row_value_map.get(row_word, row_word))
    row_selector = rate.get("row_selector_by_table", {}).get(table_id)
    if row_selector:
        selector_inputs = row_selector.get("inputs", [])
        invalid = [name for name in selector_inputs if name not in fields]
        if invalid:
            return _unresolvable(table_id, str(row_ref or ""), str(col_ref or ""),
                                 f"row selector must reference declared inputs: {sorted(set(invalid))}")
        matched_routes = [route for route in row_selector.get("routes", [])
                          if route.get("when")
                          and all(validated.get(name) == expected
                                  for name, expected in route["when"].items())]
        if len(matched_routes) != 1:
            return _unresolvable(table_id, str(row_ref or ""), str(col_ref or ""),
                                 f"no unique exact source row route (candidates {len(matched_routes)})")
        selected_row = matched_routes[0].get("row")
        exact_rows = [name for name in table.get("values", {}) if name == selected_row]
        if len(exact_rows) != 1:
            return _unresolvable(table_id, str(selected_row or ""), str(col_ref or ""),
                                 f"selected exact source row candidates {len(exact_rows)}")
        row_word = exact_rows[0]
        trades = trades_by_row.get(row_word,
                                   rate.get("trades_by_table", {}).get(table_id, rate["trades"]))
    trade_in_columns = bool(rate.get("trade_in_columns_by_table", {}).get(
        table_id, rate.get("trade_in_columns")))
    if trade_in_columns:
        # Opt-in orientation for source matrices where the requested quantity
        # selects a row and named resources are subcolumns of the other axis.
        col_word = ""
    elif isinstance(col_ref, dict):
        column_axis = {column: {} for row_values in table["values"].values()
                       for column in row_values}
        selected_column, column_error = _axis_key(
            column_axis, col_ref, validated, "열", table_id)
        if column_error:
            return _unresolvable(table_id, row_word, "", column_error)
        col_word = selected_column
    else:
        col_word = str(validated.get(col_ref, col_ref)) if col_ref is not None else ""
    # Resolve a source-defined calculated selector (for example a measured
    # length multiplied by a tabulated conversion coefficient) across one or
    # more continuation tables.  The source tables remain the only rate source.
    selector = rate.get("calculated_column_selector")
    selector_citation = list(coefficient_citations) + unit_selector_citations
    if selector:
        factor_tables = selector.get("factor_tables_by_value", {}).get(
            str(validated.get(selector.get("factor_table_input"), "")), [])
        if not factor_tables:
            return _unresolvable(table_id, row_word, "", "calculated selector has no source factor table")
        thickness = str(validated.get(selector.get("factor_column_input"), ""))
        factor_matches = []
        for factor_table_id in factor_tables:
            ft = tables.get(factor_table_id, {})
            fr = ft.get("values", {}).get(selector.get("factor_row"), {})
            factor_matches.extend((factor_table_id, ft, key, raw) for key, raw in fr.items()
                                  if _key(key) == _key(thickness))
        if len(factor_matches) != 1:
            return {"status": "rejected", "reason":
                    f"{selector.get('factor_row')} 표에 입력값 {thickness}의 원문 계수가 없어 적용 범위 밖입니다."}
        factor_table_id, ft, factor_cell, factor_raw = factor_matches[0]
        try:
            factor_value = parse_table_number(factor_raw)
            selected_value = Fraction(str(validated[selector["value_input"]])) * factor_value
        except (ValueError, KeyError, ZeroDivisionError):
            return _unresolvable(factor_table_id, selector.get("factor_row", ""), factor_cell,
                                 "calculated selector input or factor is invalid")
        candidates = []
        for source_id in [table_id, *rate.get("continuation_tables", [])]:
            source_table = tables.get(source_id)
            if source_table is None:
                return _unresolvable(source_id, "", "", "continuation rate table missing")
            source_row = source_table.get("values", {}).get(rate.get("row_input"), {})
            for label, raw in source_row.items():
                match = re.search(r"(\d+(?:\.\d+)?)\s*(?:이상|미만)", label)
                if match:
                    candidates.append((Fraction(match.group(1)), label, source_id, source_table, raw))
        lower = [(threshold, label, sid, st, raw) for threshold, label, sid, st, raw in candidates
                 if "이상" in label and threshold <= selected_value]
        if lower:
            _, col_word, table_id, table, _ = max(lower, key=lambda item: item[0])
        else:
            upper = [(threshold, label, sid, st, raw) for threshold, label, sid, st, raw in candidates
                     if "미만" in label]
            if not upper:
                return _unresolvable(table_id, row_word, str(selected_value),
                                     "calculated selector is below source table range")
            _, col_word, table_id, table, _ = min(upper, key=lambda item: item[0])
        selector_citation = [cite_table(factor_table_id, selector.get("factor_row"), factor_cell, factor_raw)]
        for conditional in rate.get("conditional_rate_multipliers", []):
            if all(validated.get(name) == value for name, value in conditional.get("when", {}).items()):
                factor *= Fraction(str(conditional["factor"]))
                selector_citation.extend(resolve_cites(conditional.get("cite")))
    # A directly declared source rule can multiply an entire per-unit rate
    # without requiring a calculated column selector (for example, a source
    # instruction to account a work type as a stated share of the base rate).
    for conditional in rate.get("base_rate_multipliers", []):
        if all(validated.get(name) == value for name, value in conditional.get("when", {}).items()):
            multiplier = Fraction(str(conditional["factor"]))
            if multiplier <= 0:
                return _unresolvable(table_id, row_word, col_word,
                                     "source base-rate multiplier must be positive")
            factor *= multiplier
            selector_citation.extend(resolve_cites(conditional.get("cite")))
    if factor <= 0:
        return _unresolvable(table_id, row_word, col_word, "calculated rate multiplier is not positive")
    lines = []
    sources = {}
    excluded_resources = []
    material_columns = []
    for trade in trades:
        excluded_rule = next((item for item in params.get("excluded_resources", [])
                              if item.get("trade") == trade
                              and all(validated.get(name) == expected
                                      for name, expected in item.get("when", {}).items())), None)
        if excluded_rule:
            excluded_resources.append({"trade": trade, "when": excluded_rule.get("when", {}),
                                       "source": excluded_rule.get("source", ""),
                                       "citations": resolve_cites(excluded_rule.get("cite"))})
            continue
        exact_row_ref = rate.get("row_by_trade_by_table", {}).get(table_id, {}).get(
            trade, rate.get("row_by_trade", {}).get(trade))
        if trade_in_columns and row_ref is not None:
            rows = [name for name in table["values"] if _key(name) == _key(row_word)]
        elif exact_row_ref is not None:
            rows = [name for name in table["values"] if _key(name) == _key(exact_row_ref)]
        elif row_ref is None:
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
            if not rows and rate.get("missing_source_row_policy") == "block":
                return {"status": "blocked",
                        "reason": f"no source rate row for exact input {row_word!r} in {table_id}",
                        "citations": resolve_cites(
                            rate.get("missing_cell_cites_by_table", {}).get(table_id))}
            return _unresolvable(table_id, f"{row_word} + {trade}", col_word,
                                 f"행 후보 {len(rows)}개")
        row = rows[0]
        columns = rate.get("source_columns_by_table", {}).get(
            table_id, list(table["values"][row]))
        if trade_in_columns:
            selector_ref = rate.get("trade_column_selector", col_ref)
            if isinstance(selector_ref, dict):
                selector_ref = dict(selector_ref)
                selector_ref["input_contains"] = [*selector_ref.get("input_contains", []), "{trade}"]
                axis = {name: {} for name in columns}
                selected, error = _axis_key(axis, selector_ref, validated, "열", table_id,
                                            context={"trade": trade})
                matches = [] if error else [selected]
            elif selector_ref is None:
                # When the source has a single resource axis and no second
                # selector, the declared trade identifies an exact header component.
                matches = [name for name in columns if _exact_axis_component(name, trade)]
            else:
                axis_value = str(validated.get(selector_ref, selector_ref)) if selector_ref is not None else ""
                matches = [name for name in columns
                           if _exact_axis_component(name, axis_value)
                           and _exact_axis_component(name, trade)]
            col_word = matches[0] if len(matches) == 1 else col_word
        elif col_ref is None and not selector:
            trade_columns = [name for name in columns if _key(trade) == _key(name)]
            if not trade_columns:
                trade_columns = [name for name in columns if _key(trade) in _key(name)]
            if trade_columns:
                matches = trade_columns
                material_columns = [name for name in columns
                                    if name not in trade_columns and name not in ignored_columns]
            elif len(columns) != 1:
                return _unresolvable(table_id, row_word, col_word, "열 지정 없음")
            else:
                matches = columns
        else:
            exact_columns = [name for name in columns if _key(name) == _key(col_word)]
            if exact_columns:
                matches = exact_columns
            elif rate.get("column_match_mode") == "token":
                matches = [name for name in columns if _exact_axis_component(name, col_word)]
            else:
                matches = [name for name in columns if _key(col_word) in _key(name)]
            if len(matches) > 1:
                # Grouped headers can repeat the selected column label across
                # resource subcolumns. Resolve only when the declared trade
                # names identify exactly one member of that selected group.
                trade_columns = [name for name in matches if _key(trade) in _key(name)]
                if len(trade_columns) == 1:
                    matches = trade_columns
        if len(matches) != 1:
            if not matches and rate.get("missing_source_cell_policy") == "block":
                return {"status": "blocked",
                        "reason": f"no source column for exact resource intersection {table_id}/{col_word}/{trade}",
                        "citations": resolve_cites(
                            rate.get("missing_cell_cites_by_table", {}).get(table_id))}
            return _unresolvable(table_id, row_word, col_word, f"열 후보 {len(matches)}개")
        column = matches[0]
        if column not in table["values"][row]:
            if rate.get("missing_source_cell_policy") == "block":
                return {"status": "blocked",
                        "reason": f"no numeric source cell at exact intersection {table_id}/{row}/{column}",
                        "citations": resolve_cites(
                            rate.get("missing_cell_cites_by_table", {}).get(table_id))}
            return _unresolvable(table_id, row, column, "원문 교차 셀 없음")
        raw = table["values"][row][column]
        selected_raw, parenthetical_mode, parenthetical_error = _select_parenthetical_source_value(
            raw, rate.get("parenthetical_value_selector"), validated)
        if parenthetical_error:
            return _unresolvable(table_id, row, column, parenthetical_error)
        try:
            value = parse_table_number(selected_raw) * factor / base
        except (ValueError, ZeroDivisionError):
            return _unresolvable(table_id, row_word, col_word, "셀 값 파싱 실패")
        if value < 0:
            return _unresolvable(table_id, row_word, col_word, "음수 품")
        component_citations = []
        component_formula = ""
        component = rate.get("source_component_multipliers_by_trade", {}).get(trade)
        if component:
            input_name = component.get("input")
            column_by_value = component.get("column_by_value", {})
            if input_name not in fields or validated.get(input_name) not in column_by_value:
                return _unresolvable(table_id, row, column,
                                     "source component multiplier has no exact input-to-column route")
            component_column = column_by_value[validated[input_name]]
            if component_column not in table["values"][row]:
                return _unresolvable(table_id, row, component_column,
                                     "source component multiplier column missing")
            component_raw = table["values"][row][component_column]
            try:
                component_value = parse_table_number(component_raw)
            except (ValueError, ZeroDivisionError):
                return _unresolvable(table_id, row, component_column,
                                     "source component multiplier cell is not numeric")
            if component_value < 0:
                return _unresolvable(table_id, row, component_column,
                                     "negative source component multiplier")
            value *= component_value
            component_citations.append(cite_table(table_id, row, component_column, component_raw))
            component_formula = f" × {component_raw}일"
        citation_override = rate.get("citation_overrides", {}).get(trade, {})
        citation_row = citation_override.get("row_map_by_column", {}).get(
            row, {}).get(column, citation_override.get("row_map", {}).get(
                row, citation_override.get("row", row)))
        citation_column = citation_override.get("column_map", {}).get(column,
                                                                       citation_override.get("column", column))
        if citation_override.get("page_source"):
            citation = resolve_cites({"page_source": citation_override["page_source"]})
        else:
            citation = cite_table(table_id, citation_row, citation_column, raw)
            citation = [citation] if isinstance(citation, dict) else citation
        citation.extend(selector_citation)
        basis_cite = rate.get("basis_cites_by_row", {}).get(row)
        if basis_cite:
            citation.extend(resolve_cites(basis_cite))
        if parenthetical_mode:
            citation.extend(resolve_cites(rate.get("parenthetical_value_selector", {}).get("cite")))
        citation_extra = resolve_cites(citation_override.get("cite"))
        rate_citations = citation + citation_extra
        rate_citations.extend(component_citations)
        resource_unit = rate.get("resource_units_by_row", {}).get(row, {}).get(
            trade, rate.get("resource_units", {}).get(
                trade, _material_unit(table_id, row, trade)))
        kind = rate.get("resource_kinds", {}).get(
            trade, "equipment" if resource_unit in ("hr", "h", "대") else "labor")
        if kind not in ("labor", "equipment", "material"):
            return _unresolvable(table_id, row_word, col_word,
                                 f"unsupported source resource kind for {trade}: {kind}")
        numerator_unit = (resource_unit if kind != "labor"
                          or trade in rate.get("preserve_labor_source_unit", []) else "인")
        display_trade = rate.get("trade_name_by_trade", {}).get(
            trade, rate.get("trade_name", trade))
        line = {"kind": kind, "name": display_trade, "unit": f"{numerator_unit}/{quantity_label}",
                "exact": str(value), "applied": _exact_text(value), "places": 0,
                "formula": f"{selected_raw}{numerator_unit} × {factor} ÷ {base}{quantity_unit}{component_formula}",
                "rule": (f"표의 괄호 값 중 {parenthetical_mode} 수치를 선택하여 단위당 품 그대로 적용(반올림 없음)"
                         if parenthetical_mode else "표 단위당 품 그대로 적용(반올림 없음)"),
                "source": f"{table_id} {table['source']}", "citations": rate_citations}
        lines.append(line)
        sources[display_trade] = {"table": table_id, "row": row, "column": column,
                          "value": raw, "selected_source_value": selected_raw,
                          "selected_parenthetical_mode": parenthetical_mode,
                          "citations": rate_citations}
        for name in material_columns:
            if (name in trades
                    or any(_key(trade) in _key(name) for trade in trades)
                    or any(line["name"] == name for line in lines)):
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
            # The row's explicit source unit takes precedence over a matching
            # rate-catalog name (e.g. a crane-hour row whose name also exists as
            # an operator trade code).
            kind = ("equipment" if material_unit in ("hr", "h", "대")
                    else "labor" if name in labor_names else "material")
            numerator_unit = "인" if kind == "labor" else material_unit
            material_citation = cite_table(table_id, row, name, material_raw)
            lines.append({"kind": kind, "name": name, "unit": f"{numerator_unit}/{quantity_label}",
                          "exact": str(material_value), "applied": _exact_text(material_value), "places": 0,
                          "formula": f"{material_raw}{material_unit} × {factor} ÷ {base}{quantity_unit}",
                          "rule": ("재료 단가 자료 없음(사용자 입력 기능 예정)" if kind == "material"
                                   else "표 단위당 품 그대로 적용(반올림 없음)"),
                          "source": f"{table_id} {table['source']}", "citations": [material_citation]})
    if row_ref is None and col_ref is not None:
        version = select_rate_version("2026-10-01")
        labor_names = {entry["name"] for entry in version["rates"].values()} if version else set()
        for name, columns in table["values"].items():
            if name in trades or any(line["name"] == name for line in lines):
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
            lines.append({"kind": kind, "name": name, "unit": f"{material_unit}/{quantity_label}",
                          "exact": str(value), "applied": _exact_text(value), "places": 0,
                          "formula": f"{raw}{material_unit} × {factor} ÷ {base}{quantity_unit}",
                          "rule": ("재료 단가 자료 없음(사용자 입력 기능 예정)" if kind == "material"
                                   else "표 단위당 품 그대로 적용(반올림 없음)"),
                          "source": f"{table_id} {table['source']}", "citations": [citation]})
    # Additional source-defined labor can be conditional and live in a
    # separate source table (for example an optional reinforcement activity).
    for activity in params.get("additional_unit_rates", []):
        when = activity.get("when", {})
        if when and not all(validated.get(name) == expected for name, expected in when.items()):
            continue
        activity_table = tables.get(activity.get("table"))
        if activity_table is None:
            return _unresolvable(str(activity.get("table")), "", "", "additional labor table missing")
        activity_quantity_name = activity.get("quantity_input", primary_name)
        if activity_quantity_name not in validated:
            return _unresolvable(activity["table"], "", "", "additional labor basis or quantity input unavailable")
        for trade in activity.get("trades", []):
            declared_basis = activity.get("basis_by_trade", {}).get(
                trade, activity.get("basis", activity_table.get("unit")))
            activity_basis = parse_basis(declared_basis)
            if activity_basis is None:
                return _unresolvable(activity["table"], "", "",
                                     f"additional labor basis unavailable for {trade}")
            activity_base, activity_unit = activity_basis
            activity_quantity_unit = (activity.get("quantity_unit")
                                      or fields[activity_quantity_name].get("unit"))
            activity_factor = conversion(activity_quantity_unit, activity_unit)
            if activity_factor is None:
                return _unresolvable(activity["table"], "", "",
                                     f"additional labor quantity unit mismatch for {trade}")
            row_name = activity.get("row_by_trade", {}).get(
                trade, activity.get("row_template", "{trade}").replace("{trade}", trade))
            row_values = activity_table.get("values", {}).get(row_name)
            column_selector = activity.get("column_selector")
            if column_selector:
                activity_columns_axis = {column: {} for column in row_values or {}}
                column_name, selector_error = _axis_key(
                    activity_columns_axis, column_selector, validated,
                    "추가 인부 열", activity["table"])
                if selector_error:
                    return _unresolvable(activity["table"], row_name, "", selector_error)
            else:
                column_name = activity.get("column_by_trade", {}).get(
                    trade, activity.get("column", "수량"))
            if row_values is None or column_name not in row_values:
                return _unresolvable(activity["table"], row_name, column_name,
                                     "additional labor row or column missing")
            selected_rate, parenthetical_mode, parenthetical_error = _select_parenthetical_source_value(
                row_values[column_name], activity.get("parenthetical_value_selector"), validated)
            if parenthetical_error:
                return _unresolvable(activity["table"], row_name, column_name,
                                     parenthetical_error)
            try:
                source_rate = parse_table_number(selected_rate)
            except (ValueError, ZeroDivisionError):
                return _unresolvable(activity["table"], row_name, column_name,
                                     "additional labor cell is not numeric")
            quantity_multiplier = parse_fraction(activity.get("quantity_multiplier", "1"))
            rate_multiplier = Fraction(1)
            citations = [cite_table(activity["table"], row_name, column_name, row_values[column_name])]
            citations.extend(resolve_cites(activity.get("cite")))
            if parenthetical_mode:
                citations.extend(resolve_cites(activity.get("parenthetical_value_selector", {}).get("cite")))
            for multiplier in activity.get("multipliers", []):
                if all(validated.get(name) == expected
                       for name, expected in multiplier.get("when", {}).items()):
                    try:
                        rate_multiplier *= parse_table_number(multiplier["factor"])
                    except (ValueError, KeyError, ZeroDivisionError):
                        return _unresolvable(activity["table"], row_name, column_name,
                                             "additional labor source multiplier is invalid")
                    citations.extend(resolve_cites(multiplier.get("cite")))
            per_quantity = (source_rate * activity_factor / activity_base
                            * quantity_multiplier * rate_multiplier)
            resource_unit = activity.get("resource_units", {}).get(trade, "인")
            lines.append({"kind": "labor", "name": trade,
                          "unit": f"{resource_unit}/{activity_quantity_unit or activity_quantity_name}",
                          "exact": str(per_quantity), "applied": _exact_text(per_quantity), "places": 0,
                          "quantity_input": activity_quantity_name,
                          "formula": f"{selected_rate}{resource_unit} × {activity_factor} ÷ {activity_base}{activity_unit}",
                          "rule": (f"parenthetical-only source value ({parenthetical_mode}); scaled by its declared quantity input at pricing"
                                   if parenthetical_mode else "source conditional unit labor rate; scaled by its declared quantity input at pricing"),
                          "source": f"{activity['table']} {activity_table.get('source', '')}",
                          "citations": citations})
    # Some source sections keep labor and material coefficients in separate
    # tables. Resolve those source-backed material quantities declaratively
    # without forcing them into the labor-rate table or inventing a shared row.
    for material in params.get("additional_materials", []):
        when = material.get("when", {})
        if when and not all(validated.get(name) == expected for name, expected in when.items()):
            continue
        # Some quantity standards state a fixed material coefficient in a
        # cited note rather than a table cell. Keep it on the same per-unit
        # path, but require both an explicit source rate and text citation.
        if "source_rate" in material:
            material_quantity_input = material.get("quantity_input", primary_name)
            if material_quantity_input not in validated:
                return _unresolvable(table_id, row_word, col_word,
                                     f"additional material quantity input missing: {material_quantity_input}")
            source_citations = resolve_cites(material.get("cite"))
            if not source_citations:
                return _unresolvable(table_id, row_word, col_word,
                                     "note-based additional material requires a source citation")
            try:
                source_rate = parse_table_number(material["source_rate"])
            except (ValueError, ZeroDivisionError):
                return _unresolvable(table_id, row_word, col_word,
                                     "note-based additional material rate is invalid")
            if source_rate < 0:
                return _unresolvable(table_id, row_word, col_word,
                                     "negative note-based additional material rate")
            material_basis = parse_basis(material.get("basis"))
            material_input_unit = material.get("quantity_unit") or fields[material_quantity_input].get("unit")
            if material_basis is None:
                return _unresolvable(table_id, row_word, col_word,
                                     "note-based additional material basis unavailable")
            material_base, material_basis_unit = material_basis
            material_factor = conversion(material_input_unit, material_basis_unit)
            if material_factor is None:
                return _unresolvable(table_id, row_word, col_word,
                                     f"note-based additional material unit mismatch: {material_input_unit}/{material_basis_unit}")
            per_quantity = source_rate * material_factor / material_base
            name = material["name"]
            unit = material.get("unit") or material_basis_unit
            lines.append({"kind": "material", "name": name,
                          "unit": f"{unit}/{material_input_unit or material_quantity_input}",
                          "exact": str(per_quantity), "applied": _exact_text(per_quantity), "places": None,
                          "formula": f"{material['source_rate']}{unit} × {material_factor} ÷ {material_base}{material_basis_unit}",
                          "rule": "cited note-based material coefficient multiplied by declared work quantity",
                          "source": material.get("source", "source note"),
                          "citations": source_citations})
            continue
        source_table = tables.get(material.get("table"))
        if source_table is None:
            return _unresolvable(str(material.get("table")), str(material.get("row", "")),
                                 str(material.get("column", "")), "additional material table missing")
        row_selector = material.get("row_selector")
        if row_selector is not None:
            row_name, row_error = _axis_key(source_table.get("values", {}), row_selector,
                                           validated, "재료 행", material["table"])
            if row_error:
                return _unresolvable(material["table"], "", str(material.get("column", "")),
                                     row_error)
        else:
            row_name = material.get("row")
        row_values = source_table.get("values", {}).get(row_name)
        if row_values is None:
            if material.get("missing_row_policy") == "block":
                return {"status": "blocked",
                        "reason": f"no source material row for exact input {row_name!r} in {material['table']}",
                        "citations": resolve_cites(material.get("missing_cell_cite"))}
            return _unresolvable(material["table"], str(row_name), str(material.get("column", "")),
                                 "additional material row missing")
        column_selector = material.get("column_selector")
        if column_selector:
            declared_material_columns = material.get("source_columns", list(row_values))
            material_columns_axis = {column: {} for column in declared_material_columns}
            column_name, selector_error = _axis_key(
                material_columns_axis, column_selector, validated,
                "재료 열", material["table"])
            if selector_error:
                return _unresolvable(material["table"], str(row_name), "", selector_error)
        else:
            column_name = material.get("column_input")
            column_name = str(validated[column_name]) if column_name else material.get("column")
        if column_name not in row_values:
            if material.get("missing_cell_policy") == "block":
                return {"status": "blocked",
                        "reason": f"no source material cell at exact intersection {material['table']}/{row_name}/{column_name}",
                        "citations": resolve_cites(material.get("missing_cell_cite"))}
            return _unresolvable(material["table"], str(row_name), str(column_name),
                                 "additional material column missing")
        citation_column = material.get("citation_column_map", {}).get(column_name, column_name)
        raw_material = row_values[column_name]
        if str(raw_material).strip() in ("-", "—", "－"):
            if material.get("dash_policy") != "source_exclusion":
                return _unresolvable(material["table"], str(row_name), str(column_name),
                                     "additional material dash lacks an explicit source policy")
            citation = cite_table(material["table"], row_name, citation_column, raw_material)
            excluded_resources.append({"trade": material.get("name", row_name),
                                       "table": material["table"], "row": row_name,
                                       "column": citation_column, "source_value": raw_material,
                                       "source": material.get("source", ""),
                                       "citations": [citation]})
            continue
        try:
            source_rate = parse_table_number(raw_material)
        except (ValueError, ZeroDivisionError):
            return _unresolvable(material["table"], str(row_name), str(column_name),
                                 "additional material cell is not numeric")
        if source_rate < 0:
            return _unresolvable(material["table"], str(row_name), str(column_name),
                                 "negative additional material rate")
        material_quantity_input = material.get("quantity_input", primary_name)
        if material_quantity_input not in validated:
            return _unresolvable(material["table"], str(row_name), str(column_name),
                                 f"additional material quantity input missing: {material_quantity_input}")
        material_basis = parse_basis(material.get("basis") or source_table.get("unit"))
        material_input_unit = material.get("quantity_unit") or fields[material_quantity_input].get("unit")
        if material_basis is None:
            return _unresolvable(material["table"], str(row_name), str(column_name),
                                 "additional material basis unavailable")
        material_base, material_basis_unit = material_basis
        material_factor = conversion(material_input_unit, material_basis_unit)
        if material_factor is None:
            return _unresolvable(material["table"], str(row_name), str(column_name),
                                 f"additional material unit mismatch: {material_input_unit}/{material_basis_unit}")
        per_quantity = source_rate * material_factor / material_base
        citation = cite_table(material["table"], row_name, citation_column, raw_material)
        material_citations = [citation, *resolve_cites(material.get("cite"))]
        name = material.get("name", row_name)
        unit = material.get("unit") or material_basis_unit
        material_table_id = material["table"]
        lines.append({"kind": "material", "name": name,
                      "unit": f"{unit}/{material_input_unit or material_quantity_input}",
                      "exact": str(per_quantity), "applied": _exact_text(per_quantity), "places": None,
                      "formula": f"{raw_material} × {material_factor} ÷ {material_base}{material_basis_unit}",
                      "rule": "source material coefficient multiplied by declared work quantity",
                      "source": f"{material_table_id} {source_table.get('source', '')}",
                      "citations": material_citations})
    quantity_adjustment_trace = []
    for adjustment in params.get("minimum_quantities", []):
        if any(validated.get(name) != expected
               for name, expected in adjustment.get("when", {}).items()):
            continue
        name = adjustment.get("input")
        if name not in validated:
            return _unresolvable(table_id, row_word, col_word,
                                 f"minimum-quantity input missing: {name}")
        try:
            minimum = parse_fraction(adjustment["minimum"])
            actual = Fraction(validated[name])
        except (KeyError, ValueError, ZeroDivisionError, TypeError):
            return _unresolvable(table_id, row_word, col_word,
                                 f"minimum-quantity rule is invalid: {name}")
        expected_unit = adjustment.get("unit")
        actual_unit = fields[name].get("unit")
        if minimum <= 0 or (expected_unit and _unit_key(expected_unit) != _unit_key(actual_unit or "")):
            return _unresolvable(table_id, row_word, col_word,
                                 f"minimum-quantity unit/value is invalid: {name}")
        if actual <= minimum:
            citations = resolve_cites(adjustment.get("cite"))
            if not citations:
                return {"status": "blocked", "reason":
                        f"minimum-quantity rule has no source citation: {name}"}
            scale = minimum / actual
            for line in lines:
                line["quantity_factor"] = str(Fraction(line.get("quantity_factor", "1")) * scale)
                line["formula"] += f" × minimum {minimum}{expected_unit or actual_unit}"
                line["rule"] += f"; source minimum quantity {minimum}{expected_unit or actual_unit} applied"
                line["citations"].extend(citations)
            quantity_adjustment_trace.append({"input": name, "actual": str(actual),
                                              "applied": str(minimum), "factor": str(scale),
                                              "citations": citations})

    # Some source tables state a derived labor item as a percentage of the
    # complete labor quantity (for example, inspection labor = 7% of labor).
    # Keep that as a distinct calculated labor line instead of spreading the
    # percentage across occupations or asking the user to enter a formula.
    proportional_resource_trace = []
    for rule in params.get("proportional_resource_additions", []):
        if any(validated.get(name) != expected for name, expected in rule.get("when", {}).items()):
            continue
        if rule.get("base") == "each_labor_line_rate":
            try:
                share = parse_fraction(rule["factor"])
            except (KeyError, ValueError, ZeroDivisionError, TypeError):
                return _unresolvable(table_id, row_word, col_word,
                                     "proportional per-line resource factor is invalid")
            if share <= 0:
                return _unresolvable(table_id, row_word, col_word,
                                     "proportional per-line resource factor must be positive")
            citations = resolve_cites(rule.get("cite"))
            if not citations:
                return {"status": "blocked", "reason":
                        "proportional per-line resource rule has no source citation"}
            excluded_trades = set(rule.get("exclude_trades", ()))
            labor_lines = [line for line in lines if line.get("kind") == "labor"
                           and line.get("name") not in excluded_trades]
            if not labor_lines:
                return _unresolvable(table_id, row_word, col_word,
                                     "proportional per-line labor base is empty")
            derived = []
            for line in labor_lines:
                quantity_input = line.get("quantity_input") or primary_name
                quantity_unit_for_line = fields[quantity_input].get("unit")
                if not quantity_unit_for_line:
                    return _unresolvable(table_id, line["name"], "",
                                         f"proportional per-line quantity has no declared unit: {quantity_input}")
                exact = Fraction(line["exact"]) * share
                derived.append({"kind": "labor", "name": rule["resource_name"],
                                "unit": f"{rule.get('resource_unit', '인')}/{quantity_unit_for_line}",
                                "exact": str(exact), "applied": _exact_text(exact), "places": 0,
                                "quantity_input": quantity_input,
                                "formula": f"{line['exact']} × {share}",
                                "rule": "source percentage of this exact task/trade rate; calculated on its declared quantity basis",
                                "source": rule.get("source", "source per-line labor percentage"),
                                "citations": list(line.get("citations", [])) + citations})
            lines.extend(derived)
            proportional_resource_trace.append({"name": rule["resource_name"],
                                                "factor": _exact_text(share),
                                                "base": "each_labor_line_rate",
                                                "excluded_trades": sorted(excluded_trades),
                                                "derived_line_count": len(derived),
                                                "derived_rates": [line["exact"] for line in derived],
                                                "citations": citations})
            continue
        if rule.get("base") != "labor_rate_total":
            return _unresolvable(table_id, row_word, col_word,
                                 "unsupported proportional resource base")
        labor_lines = [line for line in lines if line.get("kind") == "labor"]
        if not labor_lines or any(line.get("quantity_input") not in (None, primary_name)
                                  for line in labor_lines):
            return _unresolvable(table_id, row_word, col_word,
                                 "proportional labor base is empty or uses multiple quantity inputs")
        try:
            share = parse_fraction(rule["factor"])
        except (KeyError, ValueError, ZeroDivisionError, TypeError):
            return _unresolvable(table_id, row_word, col_word,
                                 "proportional resource factor is invalid")
        if share <= 0:
            return _unresolvable(table_id, row_word, col_word,
                                 "proportional resource factor must be positive")
        citations = resolve_cites(rule.get("cite"))
        if not citations:
            return {"status": "blocked", "reason": "proportional resource rule has no source citation"}
        excluded_trades = set(rule.get("exclude_trades", ()))
        exact = sum((Fraction(line["exact"]) for line in labor_lines
                     if line.get("name") not in excluded_trades), Fraction(0)) * share
        resource = rule.get("resource_name")
        resource_unit = rule.get("resource_unit", "인")
        if not isinstance(resource, str) or not resource or not isinstance(resource_unit, str) or not resource_unit:
            return _unresolvable(table_id, row_word, col_word,
                                 "proportional resource name/unit is missing")
        lines.append({"kind": "labor", "name": resource,
                      "unit": f"{resource_unit}/{quantity_label}", "exact": str(exact),
                      "applied": _exact_text(exact), "places": 0,
                      "quantity_input": primary_name,
                      "formula": f"sum(source labor rates) × {share}",
                      "rule": "source percentage of total labor quantity; emitted as a separate resource line",
                      "source": rule.get("source", "source labor percentage"),
                      "citations": citations})
        proportional_resource_trace.append({"name": resource, "factor": _exact_text(share),
                                             "base_labor_rate_total": _exact_text(sum(
                                                 (Fraction(line["exact"]) for line in labor_lines), Fraction(0))),
                                             "result_rate": _exact_text(exact), "citations": citations})

    input_adjustment_trace = []
    for adjustment in params.get("input_rate_adjustments", []):
        if any(validated.get(name) != expected
               for name, expected in adjustment.get("when", {}).items()):
            continue
        input_name = adjustment.get("value_input")
        operation = adjustment.get("operation")
        if operation == "source_table_percent_by_range":
            input_name = adjustment.get("value_input")
            if input_name not in validated:
                return _unresolvable(table_id, row_word, col_word,
                                     f"source table percent input missing: {input_name}")
            try:
                selected_value = Fraction(validated[input_name])
                ranges = adjustment.get("ranges", [])
                matched_ranges = [item for item in ranges
                                  if Fraction(item["minimum"]) <= selected_value <= Fraction(item["maximum"])]
            except (KeyError, ValueError, TypeError, ZeroDivisionError):
                return _unresolvable(table_id, row_word, col_word,
                                     f"source table percent ranges are invalid: {input_name}")
            if len(matched_ranges) != 1:
                return _unresolvable(table_id, row_word, col_word,
                                     f"no unique exact source percent band for {input_name}={selected_value}")
            source_table_id = adjustment.get("table")
            source_table = tables.get(source_table_id)
            source_row_name = adjustment.get("row")
            source_column = matched_ranges[0].get("column")
            source_row = source_table.get("values", {}).get(source_row_name) if source_table else None
            if source_row is None or source_column not in source_row:
                return _unresolvable(source_table_id or "", source_row_name or "",
                                     source_column or "", "exact source percent cell missing")
            try:
                rate_value = parse_table_number(source_row[source_column])
            except ValueError:
                return _unresolvable(source_table_id, source_row_name, source_column,
                                     "source percent cell is not numeric")
            if rate_value < 0:
                return _unresolvable(source_table_id, source_row_name, source_column,
                                     "source percent cell must be nonnegative")
            rate_value *= 100
            adjustment_formula = f"(1 + {rate_value}/100)"
            trace_input = input_name
            citations = [cite_table(source_table_id, source_row_name, source_column,
                                    source_row[source_column])]
            citations.extend(resolve_cites(adjustment.get("cite")))
        elif operation == "add_percent":
            if input_name not in validated:
                return _unresolvable(table_id, row_word, col_word,
                                     f"input rate adjustment value missing: {input_name}")
            try:
                rate_value = parse_fraction(validated[input_name])
                maximum = parse_fraction(adjustment["maximum"])
            except (KeyError, ValueError, ZeroDivisionError, TypeError):
                return _unresolvable(table_id, row_word, col_word,
                                     f"input rate adjustment is invalid: {input_name}")
            if rate_value < 0 or rate_value > maximum:
                return {"status": "rejected", "reason":
                        f"{input_name} is outside the source-backed adjustment range 0..{maximum}",
                        "input": input_name}
            operator = "-" if operation == "subtract_source_percent" else "+"
            adjustment_formula = f"(1 {operator} {rate_value}/100)"
            trace_input = input_name
        elif operation == "add_percent_per_count":
            count_input = adjustment.get("count_input")
            if count_input not in validated:
                return _unresolvable(table_id, row_word, col_word,
                                     f"input rate adjustment count missing: {count_input}")
            try:
                count = Fraction(validated[count_input])
                percent_per_count = parse_fraction(adjustment["percent_per_count"])
            except (KeyError, ValueError, ZeroDivisionError, TypeError):
                return _unresolvable(table_id, row_word, col_word,
                                     f"input rate adjustment count or rate is invalid: {count_input}")
            if (count < 0 or count.denominator != 1 or percent_per_count < 0):
                return {"status": "rejected", "reason":
                        f"{count_input} must be a nonnegative integer and its source rate nonnegative",
                        "input": count_input}
            rate_value = count * percent_per_count
            adjustment_formula = f"(1 + {count} × {percent_per_count}/100)"
            trace_input = count_input
        elif operation in ("add_source_percent", "subtract_source_percent"):
            try:
                rate_value = parse_fraction(adjustment["percent"])
            except (KeyError, ValueError, ZeroDivisionError, TypeError):
                return _unresolvable(table_id, row_word, col_word,
                                     "source percentage adjustment is invalid")
            if rate_value < 0 or (operation == "subtract_source_percent" and rate_value > 100):
                return _unresolvable(table_id, row_word, col_word,
                                     "source percentage adjustment is outside its valid range")
            operator = "-" if operation == "subtract_source_percent" else "+"
            adjustment_formula = f"(1 {operator} {rate_value}/100)"
            trace_input = adjustment.get("name", "source percentage")
            input_name = trace_input
        else:
            return _unresolvable(table_id, row_word, col_word,
                                 f"unsupported input rate adjustment: {operation}")
        multiplier = (1 - rate_value / 100 if operation == "subtract_source_percent"
                      else 1 + rate_value / 100)
        if operation != "source_table_percent_by_range":
            citations = resolve_cites(adjustment.get("cite"))
        if not citations:
            return {"status": "blocked", "reason":
                    f"{trace_input} adjustment has no source citation"}
        selected_kinds = set(adjustment.get("kinds", ("labor", "equipment")))
        selected_names = set(adjustment.get("trades", ()))
        excluded_names = set(adjustment.get("exclude_trades", ()))
        excluded_quantities = set(adjustment.get("exclude_quantity_inputs", ()))
        changed = []
        for line in lines:
            if (line["kind"] not in selected_kinds
                    or (selected_names and line["name"] not in selected_names)
                    or line["name"] in excluded_names
                    or line.get("quantity_input") in excluded_quantities):
                continue
            before = Fraction(line["exact"])
            after = before * multiplier
            line["exact"] = str(after)
            line["applied"] = _exact_text(after)
            line["formula"] += f" × {adjustment_formula}"
            line["rule"] += f"; source-backed input adjustment {trace_input}={rate_value}%"
            line["citations"].extend(citations)
            changed.append({"name": line["name"], "before": _exact_text(before),
                            "after": _exact_text(after), "kind": line["kind"]})
        if not changed:
            return _unresolvable(table_id, row_word, col_word,
                                 f"input rate adjustment selected no resource lines: {input_name}")
        input_adjustment_trace.append({"input": trace_input, "rate": _exact_text(rate_value),
                                       "operation": operation, "resources": changed,
                                       "citations": citations})

    repeat_input = params.get("repeat_input")
    if repeat_input:
        repeats = validated[repeat_input]
        if repeats < 1:
            return {"status": "rejected", "reason": "칠 횟수는 1 이상의 정수여야 함"}
        repeat_cites = resolve_cites(params["repeat_basis"])
        if not repeat_cites:
            return {"status": "blocked", "reason": "칠 횟수의 원문 기준을 확인할 수 없음"}
        for line in lines:
            line["exact"] = str(Fraction(line["exact"]) * repeats)
            line["applied"] = _exact_text(Fraction(line["exact"]))
            line["formula"] += f" × {repeats}회"
            line["rule"] += f"; 1회 기준 품에 칠 횟수 {repeats}회 적용"
            line["citations"] += repeat_cites
    adjusted = apply_adjustments(spec, validated, lines)
    if adjusted["status"] != "computed":
        return adjusted
    # Some source notes say an additional measured quantity is added to the
    # base work quantity (for example, detour distance). Keep that value as a
    # separate priced component so the estimate path can scale the same source
    # rate by each measured input without asking the user to add them manually.
    quantity_addition_trace = []
    for addition in params.get("quantity_additions", []):
        if any(validated.get(name) != expected for name, expected in addition.get("when", {}).items()):
            continue
        addition_name = addition.get("input")
        if addition_name not in validated:
            return _unresolvable(table_id, row_word, col_word,
                                 f"quantity-addition input missing: {addition_name}")
        addition_unit = fields[addition_name].get("unit")
        if not addition_unit or _unit_key(addition_unit) != _unit_key(quantity_unit):
            return _unresolvable(table_id, row_word, col_word,
                                 f"quantity-addition unit must match source quantity basis: {addition_name}")
        addition_value = validated[addition_name]
        if addition_value < 0:
            return _unresolvable(table_id, row_word, col_word,
                                 f"quantity-addition must be nonnegative: {addition_name}")
        addition_citations = resolve_cites(addition.get("cite"))
        if not addition_citations:
            return {"status": "blocked", "reason":
                    f"quantity-addition rule has no source citation: {addition_name}"}
        if addition_value:
            extra_lines = []
            for line in lines:
                extra = dict(line)
                extra["quantity_input"] = addition_name
                extra["formula"] += f" × {addition_name}={_exact_text(addition_value)}{addition_unit}"
                extra["rule"] += "; source note adds this measured quantity to the base work quantity"
                extra["citations"] = [*line.get("citations", []), *addition_citations]
                extra_lines.append(extra)
            lines.extend(extra_lines)
        quantity_addition_trace.append({"input": addition_name,
                                        "value": _exact_text(addition_value),
                                        "unit": addition_unit,
                                        "citations": addition_citations})
    for line in lines:
        if coefficient_sources:
            line["formula"] += f" × coefficient {coefficient_factor}"
            line["citations"].extend(cite_table(entry["table"], "계수", entry["cell"], entry["source_value"])
                                     for entry in coefficient_sources)
    return {"status": "computed", "unit_lines": lines, "adjustment_memos": adjusted["memos"],
            "warnings": [unit_warning] if unit_warning else [],
            "unit_basis": {"per": f"1{quantity_unit}", "daily_output": "",
                           "places": 0, "adjustable_note": "표 단위당 품을 정확히 적용"},
            "provenance": {"unit_rates": sources, "quantity_input": quantity_names,
            "coefficient_rules": coefficient_sources,
            "input_rate_adjustments": input_adjustment_trace,
            "proportional_resource_additions": proportional_resource_trace,
                           "quantity_additions": quantity_addition_trace,
            "minimum_quantities": quantity_adjustment_trace,
                           "quantity": {name: _exact_text(validated[name]) for name in quantity_names},
                           "excluded_resources": excluded_resources},
            "not_calculated": spec["not_calculated"]}
