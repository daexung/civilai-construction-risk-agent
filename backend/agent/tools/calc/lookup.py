"""Resolve source-backed lookup specifications without guessing table axes."""
from __future__ import annotations

import re
import unicodedata
from fractions import Fraction

from backend.agent.tools.calc.daily_crew import _validate, check_blocked
from backend.agent.tools.source.citation import cite_table


def _key(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value))).casefold()


def _citation_table_id(table: dict) -> str:
    """Resolve an internal selected-table alias to its exact source table citation."""
    return table.get("source_table_id") or table["id"]


def _cells_for_inputs(spec: dict, inputs: dict) -> list[dict]:
    """Return source cells consistent with every supplied categorical input."""
    matches = []
    for table in spec.get("tables", []):
        values = table.get("values", {})
        axes = []
        for value in inputs.values():
            needle = _key(value)
            row_hits = [row for row in values if _key(row) == needle]
            col_hits = [column for row in values.values() if isinstance(row, dict)
                        for column in row if _key(column) == needle]
            choices = ([('row', item) for item in dict.fromkeys(row_hits)]
                        + [('column', item) for item in dict.fromkeys(col_hits)])
            if len(choices) != 1:
                axes = []
                break
            axes.append(choices[0])
        if len(axes) != len(inputs):
            continue
        for row, columns in values.items():
            for column, raw in columns.items():
                if all((axis == "row" and row == key) or (axis == "column" and column == key)
                       for axis, key in axes):
                    matches.append({"table": table, "row": row, "column": column, "value": raw})
    return matches


def _unique_row_for_input(spec: dict, inputs: dict) -> tuple[dict, str] | None:
    """Resolve one exact row key when a lookup input intentionally identifies a record.

    A record can have several source columns (for example an equipment's operating
    hours and cost coefficients). Returning the complete, labeled row preserves the
    source rather than choosing an arbitrary column. This is deliberately limited to
    one row-axis input and one unique table/row pair; it does not infer transposes,
    aliases, or cross-table matches.
    """
    if len(inputs) != 1:
        return None
    section_no = str(spec.get("section_no", ""))
    input_name, input_value = next(iter(inputs.items()))
    needle = _key(input_value)
    field = next((f for f in spec.get("inputs", []) if f.get("name") == input_name), {})
    code = (field.get("machine_codes") or {}).get(str(input_value))
    mapped_row = None
    if isinstance(code, str) and code.startswith(section_no + "-"):
        # This spec explicitly maps the user-facing choice to a source code.
        # Resolve only the exact suffix row represented by this machine group.
        mapped_row = code[len(section_no) + 1:]
    elif isinstance(code, str) and any(
            code in table.get("values", {}) for table in spec.get("tables", [])):
        # Some catalogue IDs name a work item while the source table uses a
        # different equipment code. An explicitly declared exact full-row map
        # may cross that prefix boundary; it still resolves only an identical
        # row key and never a similar label.
        mapped_row = code
    matches = []
    for table in spec.get("tables", []):
        values = table.get("values", {})
        for row, columns in values.items():
            if _key(row) not in {needle, _key(mapped_row)} or not isinstance(columns, dict) or not columns:
                continue
            # The same label on a column is ambiguous, even if it also labels a row.
            column_hits = [column for cells in values.values() if isinstance(cells, dict)
                           for column in cells if _key(column) == needle]
            if column_hits:
                continue
            # Machine-specific entries often share a page-level matrix with other
            # machines. When the selected spec itself is identified by a machine
            # code, require that code to be present in the same source row before
            # expanding it; matching only a common capacity such as "45ø" can pick
            # another machine's record.
            if re.fullmatch(r"\d{4}-\d{4}", section_no):
                row_evidence = " ".join([row, *map(str, columns.keys()), *map(str, columns.values())])
                mapped_exact = mapped_row is not None and _key(row) == _key(mapped_row)
                if _key(section_no) not in _key(row_evidence) and not mapped_exact:
                    continue
            matches.append((table, row, columns))
    if len(matches) != 1:
        return None
    table, row, columns = matches[0]
    return {"table": table, "row": row, "columns": columns}, row


def _selected_source_table(spec: dict, inputs: dict) -> tuple[dict, str, str] | None:
    """Return a table chosen by an exact source_table_map input."""
    fields = {field.get("name"): field for field in spec.get("inputs", [])}
    selected = []
    for name, value in inputs.items():
        mapping = fields.get(name, {}).get("source_table_map")
        if isinstance(mapping, dict) and str(value) in mapping:
            selected.append((name, mapping[str(value)]))
    if len(selected) != 1:
        return None
    field_name, table_id = selected[0]
    matches = [table for table in spec.get("tables", []) if table.get("id") == table_id]
    if len(matches) != 1 or not isinstance(matches[0].get("values"), dict):
        return None
    return matches[0], field_name, table_id


def _selected_source_tables(spec: dict, inputs: dict) -> tuple[list[dict], str, list[str]] | None:
    """Resolve an exact category→one-or-more-table mapping without inference."""
    if len(inputs) != 1:
        return None
    field_name, selected = next(iter(inputs.items()))
    field = next((item for item in spec.get("inputs", []) if item.get("name") == field_name), None)
    mapping = (field or {}).get("source_table_map")
    table_ids = mapping.get(str(selected)) if isinstance(mapping, dict) else None
    if isinstance(table_ids, str):
        table_ids = [table_ids]
    if not isinstance(table_ids, list) or not table_ids or any(not isinstance(item, str) for item in table_ids):
        return None
    if len(set(table_ids)) != len(table_ids):
        return None
    by_id = {table.get("id"): table for table in spec.get("tables", [])}
    if any(table_id not in by_id or not isinstance(by_id[table_id].get("values"), dict)
           or not by_id[table_id]["values"] for table_id in table_ids):
        return None
    return [by_id[table_id] for table_id in table_ids], field_name, table_ids


def _is_spec_value_field(field: dict) -> bool:
    return "규격" in " ".join(str(field.get(key, "")) for key in ("name", "ask", "source"))


def _field_is_required(field: dict, inputs: dict) -> bool:
    condition = field.get("required_when") or field.get("when")
    if not isinstance(condition, dict):
        return bool(field.get("required"))
    return inputs.get(condition.get("input")) == condition.get("equals")


def _mapped_source_row(spec: dict, inputs: dict) -> tuple[dict, str] | None:
    """Resolve one exact source row after an exact table-selector choice."""
    selectors = []
    fields = {field.get("name"): field for field in spec.get("inputs", [])}
    for name, value in inputs.items():
        mapping = fields.get(name, {}).get("source_table_map")
        if isinstance(mapping, dict) and str(value) in mapping:
            selectors.append((name, value))
    if len(selectors) != 1:
        return None
    selector_name, selector_value = selectors[0]
    selected = _selected_source_tables(spec, {selector_name: selector_value})
    if selected is None or len(selected[0]) != 1:
        return None
    remaining = [(name, value) for name, value in inputs.items() if name != selector_name]
    if len(remaining) != 1 or not fields.get(remaining[0][0], {}).get("source_row_key"):
        return None
    table, _, _ = selected
    row_key = str(remaining[0][1])
    rows = table[0].get("values", {})
    matches = [row for row in rows if _key(row) == _key(row_key)]
    if len(matches) != 1 or not isinstance(rows[matches[0]], dict) or not rows[matches[0]]:
        return None
    row = matches[0]
    return {"table": table[0], "row": row, "columns": rows[row]}, row


def _mapped_source_record(spec: dict, inputs: dict) -> tuple[dict, str] | None:
    """Resolve one exact source row from a declared record map across source tables."""
    if len(inputs) != 1:
        return None
    input_name, input_value = next(iter(inputs.items()))
    field = next((item for item in spec.get("inputs", []) if item.get("name") == input_name), {})
    record = (field.get("source_record_map") or {}).get(str(input_value))
    if not isinstance(record, dict):
        return None
    table_id, row = record.get("table_id"), record.get("row")
    if not isinstance(table_id, str) or not isinstance(row, str):
        return None
    tables = [table for table in spec.get("tables", []) if table.get("id") == table_id]
    if len(tables) != 1:
        return None
    values = tables[0].get("values", {})
    columns = values.get(row)
    if not isinstance(columns, dict) or not columns:
        return None
    return {"table": tables[0], "row": row, "columns": columns}, row


def _mapped_spec_row(spec: dict, inputs: dict) -> tuple[dict, str] | None:
    """Resolve an exact 규격 cell within its explicitly selected source table."""
    selected = _selected_source_table(spec, inputs)
    if selected is None:
        return None
    table, table_field_name, _ = selected
    remaining = [(name, value) for name, value in inputs.items() if name != table_field_name]
    if len(remaining) != 1:
        return None
    name, value = remaining[0]
    field = next((item for item in spec.get("inputs", []) if item.get("name") == name), {})
    if not _is_spec_value_field(field):
        return None
    numeric_value = None
    try:
        numeric_value = Fraction(str(value).replace(",", ""))
    except (ValueError, ZeroDivisionError):
        pass

    row_hits = []
    for row, columns in table["values"].items():
        if not isinstance(columns, dict):
            continue
        spec_columns = [column for column in columns if _key(column).startswith(_key("규격"))]
        if len(spec_columns) != 1:
            continue
        raw = columns[spec_columns[0]]
        exact = _key(raw) == _key(value)
        if numeric_value is not None:
            try:
                exact = Fraction(str(raw).replace(",", "")) == numeric_value
            except (ValueError, ZeroDivisionError):
                pass
        if exact:
            row_hits.append((row, columns))
    if len(row_hits) != 1:
        return None
    row, columns = row_hits[0]
    return {"table": table, "row": row, "columns": columns}, row


def _numeric_source_range_hit(spec: dict, inputs: dict) -> dict | None:
    """Map one numeric input through declared, exact source intervals."""
    if len(inputs) != 1:
        return None
    name, raw = next(iter(inputs.items()))
    field = next((item for item in spec.get("inputs", []) if item.get("name") == name), {})
    routes = field.get("source_range_map")
    if not isinstance(routes, list) or not routes:
        return None
    try:
        value = Fraction(str(raw))
    except (ValueError, ZeroDivisionError):
        return None

    matching = []
    for route in routes:
        lower = Fraction(str(route["min"])) if route.get("min") is not None else None
        upper = Fraction(str(route["max"])) if route.get("max") is not None else None
        above_lower = (lower is None or value > lower or
                       (value == lower and route.get("min_inclusive", False)))
        below_upper = (upper is None or value < upper or
                       (value == upper and route.get("max_inclusive", False)))
        if above_lower and below_upper:
            matching.append(route)
    if len(matching) != 1:
        return None
    route = matching[0]
    table = next((item for item in spec.get("tables", []) if item.get("id") == route.get("table_id")), None)
    if table is None:
        return None
    row, column = route.get("row"), route.get("column")
    values = table.get("values", {})
    if row not in values or not isinstance(values[row], dict) or column not in values[row]:
        return None
    return {"table": table, "row": row, "column": column, "value": values[row][column]}


def _row_reference_result(spec: dict, row_data: dict, row: str) -> dict:
    table = row_data["table"]
    unit_lines = []
    citations = []
    for column, raw in row_data["columns"].items():
        source_column = table.get("source_column_map", {}).get(column, column)
        citation = cite_table(_citation_table_id(table), row, source_column, raw)
        citations.append(citation)
        unit_lines.append({"kind": "lookup", "name": f"{table.get('role', table['id'])} — {column}",
                           "exact": raw, "unit": None, "source": table["source"], "citations": [citation]})
    return {"status": "computed", "value": dict(row_data["columns"]), "unit": None,
            "unit_lines": unit_lines, "row_reference": True,
            "provenance": {"table": table["id"], "row": row, "columns": dict(row_data["columns"]),
                           "source": table["source"], "citations": citations},
            "not_calculated": spec.get("not_calculated", []),
            "scope_notes": {"blocked": spec.get("blocked", []),
                            "open_questions": spec.get("open_questions", [])}}


def _lookup_axes_after_blocked_checks(spec: dict, inputs: dict) -> dict:
    """Drop checked policy dimensions that are not source-table axes.

    Some reference tables add a user confirmation solely to gate applicability
    (for example, whether an item's service life has expired). `check_blocked`
    has already enforced that condition before this helper is reached; requiring
    such a value to also occur as a table row/column would make a valid lookup
    impossible. If a checked value is itself a table axis, keep it in the match.
    """
    policy_inputs = set()
    for item in spec.get("blocked", []):
        conditions = item.get("blocked_if_all") or ([item["blocked_if"]]
                                                      if item.get("blocked_if") else [])
        policy_inputs.update(condition.get("input") for condition in conditions)
    range_mapped_inputs = {field.get("name") for field in spec.get("inputs", [])
                           if field.get("source_range_map")}
    ignored = {name for name in policy_inputs & inputs.keys()
               if name not in range_mapped_inputs
               and not _cells_for_inputs(spec, {name: inputs[name]})}
    return {name: value for name, value in inputs.items() if name not in ignored}


def _source_table_reference(spec: dict, inputs: dict) -> dict | None:
    """Return explicitly mapped source table(s) when a choice selects them.

    This is for categorical choices that identify a whole source table rather
    than a row/column label. The table mapping is authored explicitly in the
    input field and is matched exactly; no title similarity or nearest table
    selection is performed. All source rows are returned so multi-spec tables
    remain complete rather than silently choosing a row.
    """
    if len(inputs) != 1:
        return None
    field_name, selected = next(iter(inputs.items()))
    field = next((item for item in spec.get("inputs", [])
                  if item.get("name") == field_name), None)
    mapping = (field or {}).get("source_table_map")
    if not isinstance(mapping, dict):
        return None
    selected_tables = _selected_source_tables(spec, inputs)
    if selected_tables is None:
        return None
    tables, _, table_ids = selected_tables
    citations = []
    unit_lines = []
    values_by_table = {}
    for table, table_id in zip(tables, table_ids):
        values = table.get("values")
        if not isinstance(values, dict) or not values:
            return None
        values_by_table[table_id] = values
        for row, columns in values.items():
            if not isinstance(columns, dict) or not columns:
                return None
            for column, raw in columns.items():
                citation = cite_table(table_id, row, column, raw)
                citations.append(citation)
                unit_lines.append({"kind": "lookup", "name": f"{table.get('role', table_id)} — {row} — {column}",
                                   "exact": raw, "unit": None, "source": table.get("source"),
                                   "citations": [citation]})
    single = len(tables) == 1
    provenance = ({"table": table_ids[0], "rows": values_by_table[table_ids[0]],
                   "source": tables[0].get("source"), "citations": citations} if single else
                  {"tables": table_ids, "rows_by_table": values_by_table,
                   "sources": [table.get("source") for table in tables], "citations": citations})
    return {"status": "computed", "value": values_by_table[table_ids[0]] if single else values_by_table,
            "unit": None, "unit_lines": unit_lines, "table_reference": True,
            "provenance": provenance,
            "not_calculated": spec.get("not_calculated", []),
            "scope_notes": {"blocked": spec.get("blocked", []),
                            "open_questions": spec.get("open_questions", [])}}


def _source_options(spec: dict, field: dict, inputs: dict, later_axes_missing: bool) -> list | None:
    """Derive safe enum choices from source table axes, when the table supports it."""
    # A source-row selector needs the selected matrix itself to enumerate row
    # labels. Resolve it before ordinary table narrowing removes the selector
    # input; otherwise exact row choices disappear for mapped tables.
    if field.get("source_row_key"):
        selected = _selected_source_tables(spec, inputs)
        if selected is None or len(selected[0]) != 1:
            return None
        row_keys = list(selected[0][0].get("values", {}))
        allowed = field.get("allowed_values")
        if field.get("type") == "enum" and isinstance(allowed, list):
            row_keys = [key for key in row_keys if key in allowed]
        return row_keys or None
    selected_context = _selected_source_table(spec, inputs)
    if selected_context is not None and not _is_spec_value_field(field):
        selected_table, selector_name, _table_id = selected_context
        spec = {**spec, "tables": [selected_table]}
        inputs = {name: value for name, value in inputs.items() if name != selector_name}
    allowed = field.get("allowed_values")
    # A declared exact category→table mapping is itself a source-backed axis.
    # Offer only categories whose mapped table is present and non-empty, so a
    # spec-valued selector can be asked after the user has selected its table.
    table_map = field.get("source_table_map")
    if field.get("type") == "enum" and isinstance(allowed, list) and isinstance(table_map, dict):
        available_tables = {table.get("id") for table in spec.get("tables", [])
                            if isinstance(table.get("values"), dict) and table["values"]}
        def mapped_tables_exist(value: object) -> bool:
            mapped = table_map.get(str(value))
            mapped = [mapped] if isinstance(mapped, str) else mapped
            return (isinstance(mapped, list) and bool(mapped)
                    and all(isinstance(table_id, str) and table_id in available_tables for table_id in mapped))

        mapped_choices = [value for value in allowed if mapped_tables_exist(value)]
        if mapped_choices:
            return mapped_choices
    if field.get("type") != "enum" or not isinstance(allowed, list):
        selected = _selected_source_table(spec, inputs)
        if selected is None or not _is_spec_value_field(field):
            return None
        table = selected[0]
        options = []
        for columns in table["values"].values():
            if not isinstance(columns, dict):
                continue
            spec_columns = [column for column in columns if _key(column).startswith(_key("규격"))]
            if len(spec_columns) != 1:
                continue
            raw = columns[spec_columns[0]]
            normalized, error = _validate(field, raw)
            if error is None and normalized not in options:
                options.append(normalized)
        return options or None
    selected = _selected_source_table(spec, inputs)
    if selected is not None and _is_spec_value_field(field):
        table = selected[0]
        options = []
        for columns in table["values"].values():
            if not isinstance(columns, dict):
                continue
            spec_columns = [column for column in columns if _key(column).startswith(_key("규격"))]
            if len(spec_columns) == 1:
                raw = columns[spec_columns[0]]
                normalized, error = _validate(field, raw)
                if error is None and normalized not in options:
                    options.append(normalized)
        if options:
            return options
    if field.get("type") != "enum":
        return None
    supported = []
    axis_found = False
    for value in allowed:
        probe = {**inputs, field["name"]: value}
        cells = _cells_for_inputs(spec, probe)
        if cells:
            axis_found = True
            if later_axes_missing or len(cells) == 1:
                supported.append(value)
            elif _unique_row_for_input(spec, probe) is not None:
                # For a single row-key input, a unique exact source row is a valid
                # reference choice even when the row has multiple output columns.
                supported.append(value)
    if not axis_found:
        return None
    return supported or None


def source_domain_options(spec: dict, field_name: str, inputs: dict) -> list | None:
    """Return the source-derived choices for a currently missing lookup field."""
    field = next((field for field in spec.get("inputs", []) if field.get("name") == field_name), None)
    if field is None:
        return None
    missing = [row for row in spec.get("inputs", [])
               if _field_is_required(row, inputs) and row.get("name") not in inputs]
    if field_name not in {row.get("name") for row in missing}:
        return None
    return _source_options(spec, field, inputs, len(missing) > 1)


def lookup(spec: dict, inputs: dict) -> dict:
    fields = {field["name"]: field for field in spec.get("inputs", [])}
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
    for name, value in validated.items():
        field = fields[name]
        if isinstance(field.get("required_when") or field.get("when"), dict) and not _field_is_required(field, validated):
            return {"status": "rejected", "reason": f"{name}는 선택한 분류에 적용되지 않습니다"}
        if not _is_spec_value_field(field):
            continue
        table_context = {key: item for key, item in validated.items() if key != name}
        if _selected_source_table(spec, table_context) is None:
            continue
        options = _source_options(spec, field, table_context, False)
        if options is not None and value not in options:
            return {"status": "rejected", "reason": f"{name}는 선택한 원문 표의 규격이 아닙니다"}
    missing = [name for name, field in fields.items()
               if _field_is_required(field, validated) and name not in validated]
    if missing:
        # A table may define a dependent domain (e.g. equipment→compatible
        # building types). Ask the first source-backed axis, then derive the next
        # enum's options from the selected row/column. Do not offer impossible
        # cross-axis combinations to the user.
        first = missing[0]
        options = _source_options(spec, fields[first], validated, len(missing) > 1)
        if options is not None:
            return {"status": "ask", "missing": [first],
                    "questions": [{"name": first, "ask": fields[first]["ask"],
                                   "allowed_values": options}]}
        return {"status": "ask", "missing": missing,
                "questions": [{"name": name, "ask": fields[name]["ask"],
                              "allowed_values": fields[name].get("allowed_values")} for name in missing]}
    blocked = check_blocked(spec, validated)
    if blocked:
        return {"status": "blocked", **blocked}

    lookup_inputs = _lookup_axes_after_blocked_checks(spec, validated)
    mapped_record = _mapped_source_record(spec, lookup_inputs)
    if mapped_record:
        row_data, row = mapped_record
        return _row_reference_result(spec, row_data, row)
    mapped_row = _mapped_source_row(spec, lookup_inputs)
    if mapped_row:
        row_data, row = mapped_row
        return _row_reference_result(spec, row_data, row)
    mapped_row = _mapped_spec_row(spec, lookup_inputs)
    if mapped_row:
        row_data, row = mapped_row
        return _row_reference_result(spec, row_data, row)
    # A one-input table selector returns the complete named table, but it must
    # not override a second input that is intended to select a row from it.
    selected_table = _selected_source_tables(spec, lookup_inputs)
    if selected_table and len(lookup_inputs) == 1:
        table_reference = _source_table_reference(spec, lookup_inputs)
        if table_reference:
            return table_reference
    selected_context = _selected_source_table(spec, lookup_inputs)
    if selected_context is not None:
        selected_table, selector_name, _table_id = selected_context
        spec = {**spec, "tables": [selected_table]}
        lookup_inputs = {name: value for name, value in lookup_inputs.items() if name != selector_name}
    # Only accept tables where every supplied categorical input names exactly one
    # row or column and together resolves a unique cell. Ambiguous layouts fail closed.
    range_hit = _numeric_source_range_hit(spec, lookup_inputs)
    matches = [range_hit] if range_hit is not None else _cells_for_inputs(spec, lookup_inputs)
    if len(matches) != 1:
        row_hit = _unique_row_for_input(spec, lookup_inputs)
        if row_hit:
            row_data, row = row_hit
            return _row_reference_result(spec, row_data, row)
        if not matches:
            table_reference = _source_table_reference(spec, lookup_inputs)
            if table_reference:
                return table_reference
    if len(matches) != 1:
        return {"status": "unresolvable", "reason":
                f"유일한 원문 표 조회 셀을 확인할 수 없음 (후보 표 {len(matches)}개)"}
    hit = matches[0]
    table = hit["table"]
    citation = cite_table(_citation_table_id(table), hit["row"], hit["column"], hit["value"])
    return {"status": "computed", "value": hit["value"], "unit": table.get("unit"),
            "unit_lines": [{"kind": "lookup", "name": table.get("role", table["id"]),
                            "exact": hit["value"], "unit": table.get("unit"), "source": table["source"],
                            "citations": [citation]}],
            "provenance": {"table": table["id"], "row": hit["row"], "column": hit["column"],
                           "value": hit["value"], "source": table["source"], "citations": [citation]},
            "not_calculated": spec.get("not_calculated", []),
            "scope_notes": {"blocked": spec.get("blocked", []),
                            "open_questions": spec.get("open_questions", [])}}
