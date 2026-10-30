"""Group saved active table failures by exact axes and source structure."""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE_ID = re.compile(r"p\d+-t\d+")
TABLE_CLASSES = {"row_axis_zero_match", "column_axis_zero_match", "cell_value_parse",
                 "ambiguous_axis", "table_route_missing"}
LINK_CLASSES = {"row_axis_zero_match", "column_axis_zero_match", "cell_value_parse"}


def refs(value):
    if isinstance(value, dict):
        return set().union(*(refs(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(refs(item) for item in value)) if value else set()
    if isinstance(value, str):
        return set(TABLE_ID.findall(value))
    return set()


def classify_root(category, rate, inputs, tables):
    names = {field.get("name") for field in inputs}
    selected = [("row", rate.get("row_input")), ("column", rate.get("column_input"))]
    for table_id, row_input in rate.get("row_input_by_table", {}).items():
        selected.append((f"row@{table_id}", row_input))
    invalid = [f"{axis}:{name}" for axis, name in selected if name is not None and name not in names]
    if category == "cell_value_parse":
        values = [str(value) for table in tables for row in (table.get("values") or {}).values()
                  if isinstance(row, dict) for value in row.values()]
        if any(value.strip() == "-" for value in values):
            return "source_dash_requires_conditional_exclusion", invalid
        if any(re.search(r"\d\s*[∼~～]\s*\d", value) for value in values):
            return "source_range_requires_explicit_policy", invalid
        if any(re.search(r"\d\s*\([^)]*\)", value) for value in values):
            return "parenthetical_source_value_requires_interpretation", invalid
        return "numeric_cell_format_or_extraction_mismatch", invalid
    if invalid:
        return "literal_header_or_missing_axis_used_as_selector", invalid
    if any(table.get("chunk_structure") not in (None, "ok") for table in tables):
        return "source_extraction_needs_visual_review", invalid
    if category == "ambiguous_axis":
        return "multiple_exact_source_axes_need_explicit_selection", invalid
    if category == "table_route_missing":
        return "missing_exact_source_table_route", invalid
    # A declared input exists, but its exact value is absent from this table's
    # row/column key set. Further routing must be source-authored, never fuzzy.
    return "declared_axis_does_not_match_exact_source_keys", invalid


def main():
    index = json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf8"))
    chunks = {item["chunk_id"]: item for item in (
        json.loads(line) for line in (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf8").splitlines()
        if line.strip())}
    packages = {}
    for path in (ROOT / "data/drafts/specs").rglob("*.json"):
        package = json.loads(path.read_text(encoding="utf8"))
        packages[package["draft"]["id"]] = package

    categories = Counter()
    details = []
    for failure in index["failed"]:
        reason = failure.get("reason", "")
        if "행 후보 0개" in reason:
            category = "row_axis_zero_match"
        elif "열 후보 0개" in reason:
            category = "column_axis_zero_match"
        elif "셀 값 파싱 실패" in reason:
            category = "cell_value_parse"
        elif "열 후보 2개" in reason or "후보 3개" in reason:
            category = "ambiguous_axis"
        elif "표 없음" in reason or "후보 표 0개" in reason:
            category = "table_route_missing"
        elif "기준 단위 파싱 실패" in reason or "물량 단위 불일치" in reason:
            category = "unit_basis_or_normalization"
        else:
            category = failure.get("stage", "other")
        categories[category] += 1
        if category not in TABLE_CLASSES:
            continue
        package = packages[failure["id"]]
        draft = package["draft"]
        rate = draft.get("quantity_model", {}).get("params", {}).get("unit_rate_table", {})
        table_map = {table["id"]: table for table in draft.get("tables", [])}
        table_details = []
        for table_id in sorted(refs(draft)):
            table = table_map.get(table_id)
            chunk = chunks.get(table_id)
            values = (table or {}).get("values", {})
            rows = list(values) if isinstance(values, dict) else []
            columns = sorted({str(key) for row in values.values() if isinstance(row, dict) for key in row})
            table_details.append({
                "table_id": table_id, "unit": (table or {}).get("unit"), "role": (table or {}).get("role"),
                "row_count": len(rows), "row_samples": rows[:6], "column_count": len(columns),
                "column_samples": columns[:10], "configured_row_input": rate.get("row_input"),
                "configured_column_input": rate.get("column_input"),
                "chunk_structure": (chunk or {}).get("structure"), "chunk_issues": (chunk or {}).get("issues", []),
                "chunk_chars": len((chunk or {}).get("text", "")),
                "merged_or_multilevel_header_signal": any(" " in col or "\n" in col or "|" in col for col in columns),
            })
        root, invalid_selectors = classify_root(category, rate, draft.get("inputs", []),
                                               [table_map[x] for x in table_map if x in refs(draft)])
        details.append({
            "failure_id": failure["id"], "division": draft.get("division"),
            "section_no": draft.get("section_no"), "calc_type": package.get("calc_type"),
            "class": category, "root_cause_group": root, "invalid_selectors": invalid_selectors,
            "diagnostic": reason,
            "input_axes": [{"name": field.get("name"), "unit": field.get("unit"),
                            "allowed_values": field.get("allowed_values")} for field in draft.get("inputs", [])],
            "tables": table_details,
        })

    link_count = sum(categories[item] for item in LINK_CLASSES)
    other_count = categories["ambiguous_axis"] + categories["table_route_missing"]
    report = {
        "method": "saved active failure list joined with exact declared axes, source chunk structure, and source cells; no fuzzy resolution",
        "active_failure_total": len(index["failed"]),
        "table_link_candidate_count": link_count,
        "other_table_lookup_diagnostics_count": other_count,
        "failure_class_counts": dict(categories),
        "table_link_classes": {key: categories[key] for key in sorted(TABLE_CLASSES) if categories[key]},
        "root_cause_group_counts": dict(Counter(item["root_cause_group"] for item in details)),
        "candidates": sorted(details, key=lambda item: (item["root_cause_group"], item["division"], item["section_no"])),
    }
    output = ROOT / "evals/runtime_validation/active-table-link-root-causes-2026-10-19.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({key: value for key, value in report.items() if key != "candidates"}, ensure_ascii=False, indent=2))
    print("saved", output.relative_to(ROOT))


if __name__ == "__main__":
    main()
