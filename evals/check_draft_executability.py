"""전체 명세 초안을 오프라인 계산기로 시험하고 실행 가능 목록을 저장한다."""

from __future__ import annotations

import itertools
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from backend.agent.tools.calc.formula import formula_quantity  # noqa: E402
from backend.agent.tools.calc.adjustments import classify_adjustment  # noqa: E402
from backend.agent.rules.misfiled import misfiled_ids  # noqa: E402

CALCULATORS = {"daily_crew": adjusted_daily_crew, "per_unit": per_unit,
               "lookup_only": lookup, "formula": formula_quantity}
OUTPUT = ROOT / "data/drafts/executable.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"


def _values(field: dict, blocked: list[dict] | None = None,
            adjustments: list[dict] | None = None,
            source_numeric_values: list[str] | None = None) -> list:
    blocked = blocked or []
    adjustments = adjustments or []
    kind = field["type"]
    if kind == "enum":
        options = field["allowed_values"]
        forbidden = {item["value"] for item in blocked if item.get("op") == "=="}
        return [value for value in options if value not in forbidden] + [value for value in options if value in forbidden]
    if kind == "boolean":
        return ([True, False] if any(item.get("op") == "==" and item.get("value") is False
                                  for item in blocked) else [False, True])
    if kind == "positive_currency":
        return ["100"]
    if kind in ("positive_rational", "nonnegative_integer", "percentage"):
        if source_numeric_values:
            # Table-backed numeric selectors must be sampled from the exact
            # source axis. A generic 100-unit sample may be outside that axis
            # and turn a correctly rejected input into a false spec failure.
            return source_numeric_values
        declared_range = re.search(r"(\d+)\s*이상\s*(\d+)\s*이하", str(field.get("allowed_values", "")))
        declared_minimum = (field.get("minimum") if field.get("minimum") is not None
                            else declared_range.group(1) if declared_range else None)
        declared_maximum = field.get("maximum") if field.get("maximum") is not None else (
            declared_range.group(2) if declared_range else None)
        numeric_rules = [item for item in blocked if item.get("op") in (">", ">=", "<", "<=", "==", "!=")]
        thresholds = []
        for item in numeric_rules:
            try:
                thresholds.append(Fraction(str(item["value"])))
            except (KeyError, ValueError, ZeroDivisionError):
                continue
        if thresholds:
            if kind == "positive_rational":
                minimum = Fraction(1, 1000)
            elif kind == "percentage":
                minimum = Fraction(str(declared_minimum)) if declared_minimum is not None else Fraction(0)
            else:
                if declared_minimum is None:
                    minimum_match = re.search(r"(\d+)\s*이상의\s*정수",
                                              str(field.get("allowed_values", "")))
                    declared_minimum = minimum_match.group(1) if minimum_match else 0
                minimum = Fraction(str(declared_minimum))
            maximum = Fraction(str(declared_maximum)) if declared_maximum is not None else None
            candidates = {Fraction(100), minimum, *thresholds}
            if maximum is not None:
                candidates.update((maximum, maximum + 1))
            for threshold in thresholds:
                candidates.update((threshold - 1, threshold + 1,
                                   threshold - Fraction(1, 100), threshold + Fraction(1, 100)))
            operations = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
                          "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
                          "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
            def allowed(candidate):
                if (candidate < minimum or (maximum is not None and candidate > maximum)
                        or (kind == "percentage" and candidate >= 100)
                        or (kind == "nonnegative_integer" and candidate.denominator != 1)):
                    return False
                for item in numeric_rules:
                    try:
                        bound = Fraction(str(item["value"]))
                    except (KeyError, ValueError, ZeroDivisionError):
                        continue
                    if operations[item["op"]](candidate, bound):
                        return False
                return True
            valid_candidates = sorted((v for v in candidates if allowed(v)),
                                      key=lambda v: (abs(v - 100), v))
            blocked_candidates = sorted((v for v in candidates if v >= minimum
                                         and (maximum is None or v <= maximum)
                                         and (kind != "percentage" or v < 100)
                                         and (kind != "nonnegative_integer" or v.denominator == 1)
                                         and not allowed(v)))
            ordered = valid_candidates + blocked_candidates
            return list(dict.fromkeys(str(v.numerator) if v.denominator == 1
                                      else f"{v.numerator}/{v.denominator}" for v in ordered))
        lower = re.search(r"(\d+)\s*이상의\s*정수", str(field.get("allowed_values", "")))
        if kind == "nonnegative_integer" and declared_range:
            return [declared_range.group(1)]
        if lower:
            values = [lower.group(1)]
            for item in adjustments:
                when = item.get("when") or {}
                if isinstance(when, dict) and field["name"] in when:
                    match = re.fullmatch(r">\s*(\d+)", str(when[field["name"]]))
                    if match:
                        values.append(str(int(match.group(1)) + 1))
            return list(dict.fromkeys(values))
        exact = next((item["value"] for item in blocked if item.get("op") == "!="), None)
        if exact is not None:
            return [str(exact)]
        if kind == "percentage":
            return [str(min(Fraction(10), Fraction(str(declared_maximum))))]
        if blocked:
            return ["0" if kind == "nonnegative_integer" else "1"]
        return ["100"]
    return []


def _source_numeric_values(spec: dict, field_name: str) -> list[str]:
    """Return one valid sample from an explicitly declared table factor axis."""
    rate = spec.get("quantity_model", {}).get("params", {}).get("unit_rate_table", {})
    selector = rate.get("calculated_column_selector", {})
    if selector.get("factor_column_input") != field_name:
        return []
    tables = {table["id"]: table for table in spec.get("tables", [])}
    factor_ids = {table_id for ids in selector.get("factor_tables_by_value", {}).values()
                  for table_id in ids}
    values = set()
    for table_id in factor_ids:
        table = tables.get(table_id, {})
        for raw in table.get("values", {}).get(selector.get("factor_row"), {}):
            try:
                value = Fraction(str(raw).replace(",", ""))
            except (ValueError, ZeroDivisionError):
                continue
            if value > 0:
                values.add(value)
    if not values:
        return []
    value = min(values)
    return [str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"]


def evaluate(report_path: Path | None = None) -> dict:
    report_path = report_path or (ROOT / "data/drafts/report.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    valid = {Path(item["path"]).name + "/" + item["division"] + "/" + item["section_no"]
             for item in report["results"] if item["ok"]}
    attempts = Counter()
    success = Counter()
    reasons = Counter()
    executable = []
    failed = []
    skipped = []
    inventory_total = 0
    excluded_count = 0
    chapter = defaultdict(lambda: Counter())
    adjustment_counts = Counter()
    excluded = misfiled_ids()
    chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    label_shift_ids = {c["chunk_id"] for c in chunks if any(str(issue).startswith("label_shift") for issue in c.get("issues", []))}
    uncertain_ids = {c["chunk_id"] for c in chunks if c.get("structure") == "uncertain" and c["chunk_id"] not in label_shift_ids}
    def referenced_ids(value):
        if isinstance(value, dict):
            return set().union(*(referenced_ids(v) for v in value.values())) if value else set()
        if isinstance(value, list):
            return set().union(*(referenced_ids(v) for v in value)) if value else set()
        if isinstance(value, str) and re.fullmatch(r"p\d+-t\d+", value):
            return {value}
        return set()
    for path in sorted((ROOT / "data/drafts/specs").rglob("*.json")):
        package = json.loads(path.read_text(encoding="utf-8"))
        spec = package["draft"]
        inventory_total += 1
        if spec["id"] in excluded:
            excluded_count += 1
            skipped.append({"id": spec["id"], "calc_type": package.get("calc_type"),
                            "stage": "inventory_exclusion", "reason": "listed in data/drafts/misfiled.json"})
            continue
        kind = package["calc_type"]
        scope = "공통/6장" if spec["division"] == "공통" and spec["section_no"].startswith("6-") else "기타"
        chapter[scope]["total"] += 1
        cited = referenced_ids(spec)
        broken = sorted(cited & label_shift_ids)
        if broken:
            failed.append({"id": spec["id"], "stage": "source_preflight",
                           "reason": "표 이름 줄 밀림 — 원문 재확인 필요", "tables": broken})
            reasons["표 이름 줄 밀림 — 원문 재확인 필요"] += 1
            continue
        if kind not in CALCULATORS:
            skipped.append({"id": spec["id"], "calc_type": kind,
                            "stage": "calculator_selection",
                            "reason": "no compatible existing calculator in this runner"})
            continue
        for item in (spec["quantity_model"]["params"].get("surcharges", [])
                     + spec["quantity_model"]["params"].get("note_adjustments", [])):
            adjustment_counts[classify_adjustment(spec, item)] += 1
        attempts[kind] += 1
        chapter[scope]["attempted"] += 1
        key = path.name + "/" + spec["division"] + "/" + spec["section_no"]
        if key not in valid:
            reason = "형식 또는 인용 불일치"
        else:
            fields = spec["inputs"]
            blocked_by_field = defaultdict(list)
            for item in spec.get("blocked", []):
                condition = item.get("blocked_if")
                if condition:
                    blocked_by_field[condition["input"]].append(condition)
            adjustments = (spec["quantity_model"]["params"].get("surcharges", [])
                           + spec["quantity_model"]["params"].get("note_adjustments", []))
            choices = [_values(field, blocked_by_field[field["name"]], adjustments,
                               _source_numeric_values(spec, field["name"])) for field in fields]
            if any(not options for options in choices):
                reason = "입력 타입 미지원"
            else:
                reason = ""
                base_computed = False
                for index, values in enumerate(itertools.islice(itertools.product(*choices), 64)):
                    inputs = dict(zip((field["name"] for field in fields), values))
                    for rule in spec["quantity_model"].get("params", {}).get("conditional_ranges", []):
                        when = rule.get("when", {})
                        if (when and all(inputs.get(name) == expected for name, expected in when.items())
                                and rule.get("input") in inputs):
                            lower, upper = Fraction(str(rule["minimum"])), Fraction(str(rule["maximum"]))
                            midpoint = (lower + upper) / 2
                            inputs[rule["input"]] = (str(midpoint.numerator) if midpoint.denominator == 1
                                                      else f"{midpoint.numerator}/{midpoint.denominator}")
                    try:
                        result = CALCULATORS[kind](spec, inputs)
                        status = result.get("status")
                        was_ask = status == "ask"
                        if status == "ask":
                            questions = result.get("questions", [])
                            if not questions or any(q.get("default") is not None for q in questions):
                                reason = "재량 할증 질문 또는 기본값 오류"
                                break
                            for answer in ("예", "아니오"):
                                answered = CALCULATORS[kind](spec, {**inputs, **{q["name"]: answer for q in questions}})
                                if answered.get("status") not in ("computed", "blocked"):
                                    reason = f"재량 할증 답변 {answer}: {answered.get('status')}: {answered.get('reason', '')}"
                                    break
                            if reason:
                                break
                            status = "computed"
                        if index == 0:
                            base_computed = status == "computed" and not was_ask
                            if not base_computed:
                                reason = f"기본 조합 {status}: {result.get('reason', '')}"
                                break
                        if status not in ("computed", "blocked"):
                            reason = f"{status}: {result.get('reason', '')}"
                            break
                    except Exception as exc:
                        reason = f"{type(exc).__name__}: {exc}"
                        break
        if reason:
            failed.append({"id": spec["id"], "stage": "format_or_input_preflight" if key not in valid
                           or "입력 타입 미지원" in reason else "calculator_execution_or_rule_gate",
                           "reason": reason})
            reasons[reason.split(":", 1)[0]] += 1
        else:
            executable.append(spec["id"])
            success[kind] += 1
            chapter[scope]["executable"] += 1
    executable_uncertain = 0
    for path in sorted((ROOT / "data/drafts/specs").rglob("*.json")):
        try:
            package = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if package["draft"]["id"] in executable and referenced_ids(package["draft"]) & uncertain_ids:
            executable_uncertain += 1
    return {"executable": sorted(executable), "failed": failed, "skipped": skipped,
            "summary": {"total": sum(value["total"] for value in chapter.values()),
                        "inventory_total": inventory_total, "excluded_from_execution": excluded_count,
                        "skipped_without_compatible_calculator": sum(
                            item["stage"] == "calculator_selection" for item in skipped),
                        "skipped_misfiled": excluded_count,
                        "source_preflight_failures": sum(item.get("stage") == "source_preflight" for item in failed),
                        "by_calc_type": {kind: {"attempted": attempts[kind], "executable": success[kind]}
                                         for kind in CALCULATORS},
                        "failure_reasons_top10": reasons.most_common(10),
                        "by_scope": dict(chapter),
                        "adjustment_items": dict(adjustment_counts),
                        "executable_using_other_uncertain_tables": executable_uncertain,
                        "label_shift_table_ids": sorted(label_shift_ids)}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "data/drafts/report.json",
                        help="validation report to use without overwriting the saved baseline")
    args = parser.parse_args()
    result = evaluate(args.report)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"실행 가능 {len(result['executable'])} / 시도 {len(result['executable']) + len(result['failed'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
