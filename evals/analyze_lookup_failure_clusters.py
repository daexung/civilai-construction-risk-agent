"""Group current lookup-only path failures by source/table mapping evidence.

This is diagnostic only: normalization similarities are reported as clues and are
never used to resolve a lookup or change a pass/fail outcome.
"""
from __future__ import annotations

import ast
import json
import re
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.tools.calc.lookup import _cells_for_inputs, _key  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402


def _input_values(reason: str) -> dict:
    marker = " inputs="
    if marker not in reason:
        return {}
    try:
        return ast.literal_eval(reason.split(marker, 1)[1])
    except (SyntaxError, ValueError):
        return {}


def _table_diag(table: dict, inputs: dict, chunk: dict | None) -> dict:
    values = table.get("values", {})
    columns = list(dict.fromkeys(c for row in values.values() if isinstance(row, dict) for c in row))
    axes = {}
    for name, raw in inputs.items():
        needle = _key(raw)
        rows = [r for r in values if _key(r) == needle]
        cols = [c for c in columns if _key(c) == needle]
        axes[name] = {"row_hits": rows, "column_hits": cols,
                      "exact_axis_hits": len(rows) + len(cols)}
    labels = list(values) + columns
    missing = []
    for name, raw in inputs.items():
        if axes[name]["exact_axis_hits"]:
            continue
        norm = _key(raw)
        nearby = sorted(((SequenceMatcher(None, norm, _key(label)).ratio(), label)
                         for label in labels), reverse=True)[:3]
        missing.append({"input": name, "value": raw,
                        "diagnostic_near_labels": [{"ratio": round(score, 3), "label": label}
                                                    for score, label in nearby if score >= 0.55]})
    return {
        "table_id": table.get("id"), "role": table.get("role"), "unit": table.get("unit"),
        "row_count": len(values), "column_count": len(columns),
        "cell_count": sum(len(v) for v in values.values() if isinstance(v, dict)),
        "multiline_labels": sum("\n" in str(x) for x in labels),
        "longest_header_line_count": max((str(x).count("\n") + 1 for x in columns), default=0),
        "row_column_counts_vary": len({len(v) for v in values.values() if isinstance(v, dict)}) > 1,
        "axes": axes, "unmatched_inputs": missing,
        "source_chunk": None if chunk is None else {
            "structure": chunk.get("structure"), "issues": chunk.get("issues", []),
            "uncertain_record_count": len(chunk.get("uncertain_record_ids", [])),
            "text_chars": len(chunk.get("text", "")),
            "bbox": chunk.get("source", {}).get("bbox"),
        },
    }


def main() -> int:
    saved = json.loads((ROOT / "evals/runtime_validation/targeted-lookup-continuation-2026-10-19.json")
                       .read_text(encoding="utf-8"))
    chunks = load_chunks(ROOT / "data/processed/chunks.all.jsonl")
    specs_root = ROOT / "data/drafts/specs"
    by_id = {}
    for path in specs_root.rglob("*.json"):
        package = json.loads(path.read_text(encoding="utf-8"))
        by_id[package.get("draft", {}).get("id")] = (path, package)

    items = []
    for failure in saved["current_lookup_failures"]:
        reason_class = failure["reason"].split(":", 1)[0]
        path, package = by_id[failure["id"]]
        spec = package["draft"]
        inputs = _input_values(failure["reason"])
        tables = []
        for table in spec.get("tables", []):
            chunk = chunks.get(table.get("id"))
            tables.append(_table_diag(table, inputs, chunk))
        validation = validate_one(path, specs_root, chunks, None)
        candidates = len(_cells_for_inputs(spec, inputs)) if inputs else None
        hit_tables = [t for t in tables if all(
            axes["exact_axis_hits"] > 0 for axes in t["axes"].values())]
        missing_globally = [name for name in inputs if not any(
            t["axes"].get(name, {}).get("exact_axis_hits", 0) for t in tables)]
        if reason_class == "format_or_citation":
            root_cause = "format_or_citation_preflight"
        elif not tables:
            root_cause = "no_declared_table_matrix"
        elif candidates and candidates > 1:
            root_cause = "multiple_exact_cells_or_tables"
        elif missing_globally:
            root_cause = "input_axis_label_missing_from_all_tables"
        elif not hit_tables:
            root_cause = "axes_split_across_different_tables"
        elif candidates == 0:
            root_cause = "all_axes_present_but_no_declared_intersection"
        else:
            root_cause = "unique_cell_should_resolve"
        items.append({
            "id": failure["id"], "division": spec.get("division"),
            "section_no": spec.get("section_no"), "title": spec.get("title"),
            "reason_class": reason_class,
            "reason": failure["reason"], "inputs": inputs,
            "candidate_cell_count": candidates, "root_cause_cluster": root_cause,
            "tables_containing_all_input_axes": [t["table_id"] for t in hit_tables],
            "input_axes_missing_from_all_tables": missing_globally,
            "input_fields": [{"name": f.get("name"), "unit": f.get("unit"),
                              "type": f.get("type"), "allowed_count": len(f.get("allowed_values", []))}
                             for f in spec.get("inputs", [])],
            "tables": tables, "format_issues": validation["format_issues"],
            "citation_issues": validation["citation_issues"],
            "open_questions": spec.get("open_questions", []),
        })

    reason_counts = Counter(x["reason_class"] for x in items)
    division_counts = Counter(x["division"] for x in items)
    table_counts = Counter(t["table_id"] for item in items for t in item["tables"])
    structure_counts = Counter(
        (t["source_chunk"] or {}).get("structure", "missing_chunk")
        for item in items for t in item["tables"])
    issue_counts = Counter(issue for item in items for t in item["tables"]
                           for issue in ((t["source_chunk"] or {}).get("issues", [])))
    unmatched = Counter(field["input"] for item in items for t in item["tables"]
                        for field in t["unmatched_inputs"])
    out = {
        "method": "Saved failed lookup paths joined to current spec matrices and source chunks; exact axis diagnostics only. Similarity labels are advisory and never resolve a cell.",
        "candidate_count": len(items), "reason_counts": dict(reason_counts),
        "root_cause_clusters": dict(Counter(x["root_cause_cluster"] for x in items)),
        "candidate_cell_counts": dict(Counter(str(x["candidate_cell_count"]) for x in items)),
        "division_counts": dict(division_counts), "referenced_table_counts": dict(table_counts),
        "source_chunk_structure_counts": dict(structure_counts),
        "source_chunk_issue_counts": dict(issue_counts),
        "unmatched_input_field_counts": dict(unmatched), "items": items,
    }
    out_path = ROOT / "evals/runtime_validation/lookup-failure-root-causes-2026-10-19.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "items"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
