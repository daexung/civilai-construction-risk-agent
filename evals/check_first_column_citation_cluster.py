"""Focused source/citation and basic execution check for six repaired tables."""
from __future__ import annotations

import itertools
import json
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals"))
from pipeline.validate_drafts import check_citations, file_sha256, load_chunks, validate_one  # noqa: E402
from check_draft_executability import CALCULATORS, _values  # noqa: E402
from repair_first_column_citation_chunks import TRANSCRIPTIONS  # noqa: E402

CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
SPECS = ROOT / "data/drafts/specs"


def check_case(table_id: str, division: str, section: str, expected: dict) -> dict:
    package_path = SPECS / division / f"{section}.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(t for t in spec["tables"] if t["id"] == table_id)
    assert table["values"] == expected, table_id
    chunk = load_chunks(CHUNKS)[table_id]
    chunk_text = chunk["text"]
    for row, cells in expected.items():
        assert row in chunk_text, (table_id, row)
        for column, value in cells.items():
            assert column in chunk_text and value in chunk_text, (table_id, row, column, value)
    cites = [c for c in package["citations"] if c.get("table_id") == table_id]
    assert check_citations({table_id: chunk}, cites) == [], table_id
    validation = validate_one(package_path, ROOT / "data/drafts", load_chunks(CHUNKS), file_sha256(CHUNKS))
    assert not validation["format_issues"] and not validation["citation_issues"], validation

    kind = package["calc_type"]
    blocked_by: dict[str, list] = {}
    for item in spec.get("blocked", []):
        cond = item.get("blocked_if")
        if cond:
            blocked_by.setdefault(cond["input"], []).append(cond)
    params = spec["quantity_model"].get("params", {})
    adjustments = params.get("surcharges", []) + params.get("note_adjustments", [])
    choices = [_values(field, blocked_by.get(field["name"], []), adjustments) for field in spec["inputs"]]
    assert all(choices), f"unsupported input domain: {section}"
    states, base_status, failure = Counter(), None, None
    tested = 0
    for index, values in enumerate(itertools.islice(itertools.product(*choices), 64)):
        inputs = dict(zip((f["name"] for f in spec["inputs"]), values))
        for rule in params.get("conditional_ranges", []):
            when = rule.get("when", {})
            if when and all(inputs.get(name) == expected_value for name, expected_value in when.items()) \
                    and rule.get("input") in inputs:
                low, high = Fraction(str(rule["minimum"])), Fraction(str(rule["maximum"]))
                mid = (low + high) / 2
                inputs[rule["input"]] = str(mid.numerator) if mid.denominator == 1 else f"{mid.numerator}/{mid.denominator}"
        result = CALCULATORS[kind](spec, inputs)
        status, asked = result.get("status"), result.get("status") == "ask"
        if index == 0:
            base_status = status
        if asked:
            questions = result.get("questions", [])
            if not questions or any(q.get("default") is not None for q in questions):
                failure = f"invalid discretionary question: {section}"
                break
            for answer in ("예", "아니오"):
                answered = CALCULATORS[kind](spec, {**inputs, **{q["name"]: answer for q in questions}})
                if answered.get("status") not in ("computed", "blocked"):
                    failure = f"answer {answer}: {answered.get('status')} {section}"
                    break
            if failure:
                break
            status = "computed"
        if index == 0 and (status != "computed" or asked):
            failure = f"basic combination {status}: {result.get('reason', '')}"
            break
        if status not in ("computed", "blocked"):
            failure = f"{status}: {result.get('reason', '')}"
            break
        states[status] += 1
        tested += 1
    assert failure is None, {"section": section, "failure": failure}
    if table_id == "p778-t3":
        expected_rates = {"조립 및 설치": {"계장공": "34/5"},
                          "시험 및 조정": {"기사": "19/10"}}
        expected_excluded = {"조립 및 설치": ("기사", "-"),
                             "시험 및 조정": ("계장공", "-")}
        for process, rates in expected_rates.items():
            result = CALCULATORS[kind](spec, {"quantity": "1", "process": process})
            actual = {line["name"]: line["exact"] for line in result["unit_lines"]}
            assert result["status"] == "computed" and actual == rates, (process, result)
            excluded = result["provenance"]["excluded_resources"]
            assert any(item["trade"] == expected_excluded[process][0]
                       and item["citations"][0]["value"] == expected_excluded[process][1]
                       for item in excluded), (process, excluded)
    return {"section": f"{division}/{section}", "table_id": table_id,
            "source_rows": len(expected), "source_value_cells": sum(map(len, expected.values())),
            "citation_issues": 0, "basic_status": base_status,
            "sampled_calculation_cases": tested, "calculation_statuses": dict(states),
            "all_rules_verified": False}


def main() -> int:
    checked = [check_case(table_id, division, section, expected)
               for table_id, (division, section, expected) in TRANSCRIPTIONS.items()]
    print(json.dumps({"status": "pass", "cause": "first-column/table-row extraction loss",
                      "affected_specs": len(checked), "source_value_cells": sum(x["source_value_cells"] for x in checked),
                      "citation_issues": 0, "cases": checked}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
