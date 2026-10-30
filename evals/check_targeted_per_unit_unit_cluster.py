"""저장된 실행 기준과 비교해 ton 계열 단위의 per_unit 후보만 재검사한다."""
from __future__ import annotations

import itertools
import json
import re
import sys
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.rules.misfiled import misfiled_ids  # noqa: E402
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from evals.check_draft_executability import _values  # noqa: E402


def quantity_names(value: object) -> list[str]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [name.strip() for name in value.split(",")]
    return []


def has_ton_conversion_surface(spec: dict) -> bool:
    params = spec["quantity_model"].get("params", {})
    names = quantity_names(params.get("quantity_input"))
    fields = {field["name"]: field for field in spec.get("inputs", [])}
    units = [str(fields[name].get("unit") or "").casefold()
             for name in names if name in fields]
    tables = {table["id"]: table for table in spec.get("tables", [])}
    rate = params.get("unit_rate_table", {})
    table = tables.get(rate.get("table"), {})
    basis = str(table.get("unit") or "").casefold()
    return (any(unit in ("t", "ton", "톤") for unit in units)
            or bool(re.search(r"/(?:t|ton|톤)(?:[,· ]|$)", basis)))


def evaluate_spec(spec: dict) -> tuple[str, str]:
    fields = spec["inputs"]
    blocked_by_field = defaultdict(list)
    for item in spec.get("blocked", []):
        condition = item.get("blocked_if")
        if condition:
            blocked_by_field[condition["input"]].append(condition)
    adjustments = (spec["quantity_model"]["params"].get("surcharges", [])
                   + spec["quantity_model"]["params"].get("note_adjustments", []))
    choices = [_values(field, blocked_by_field[field["name"]], adjustments) for field in fields]
    if any(not options for options in choices):
        return "failed", "입력 타입 미지원"
    for index, values in enumerate(itertools.islice(itertools.product(*choices), 64)):
        inputs = dict(zip((field["name"] for field in fields), values))
        for rule in spec["quantity_model"].get("params", {}).get("conditional_ranges", []):
            when = rule.get("when", {})
            if when and all(inputs.get(name) == expected for name, expected in when.items()):
                lower, upper = Fraction(str(rule["minimum"])), Fraction(str(rule["maximum"]))
                midpoint = (lower + upper) / 2
                inputs[rule["input"]] = (str(midpoint.numerator) if midpoint.denominator == 1
                                           else f"{midpoint.numerator}/{midpoint.denominator}")
        try:
            result = per_unit(spec, inputs)
            status = result.get("status")
            was_ask = status == "ask"
            if was_ask:
                questions = result.get("questions", [])
                if not questions or any(question.get("default") is not None for question in questions):
                    return "failed", "재량 할증 질문 또는 기본값 오류"
                for answer in ("예", "아니오"):
                    answered = per_unit(spec, {**inputs, **{q["name"]: answer for q in questions}})
                    if answered.get("status") not in ("computed", "blocked"):
                        return "failed", f"재량 할증 답변 {answer}: {answered.get('status')}"
            if index == 0 and (status != "computed" or was_ask):
                return "failed", f"기본 조합 {status}: {result.get('reason', '')}"
            if status not in ("computed", "blocked") and not was_ask:
                return "failed", f"{status}: {result.get('reason', '')}"
        except Exception as exc:  # noqa: BLE001
            return "failed", f"{type(exc).__name__}: {exc}"
    return "pass", ""


def main() -> int:
    baseline = json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))
    baseline_status = {item: "pass" for item in baseline["executable"]}
    baseline_status.update({item["id"]: "fail" for item in baseline["failed"]})
    baseline_status.update({item["id"]: "excluded" if item.get("stage") == "inventory_exclusion"
                            else "unsupported" for item in baseline["skipped"]})

    # The latest replay used this validation report; report.json is an older saved baseline.
    report = json.loads((ROOT / "tmp/replay-draft-validation-current.json").read_text(encoding="utf-8"))
    valid = {Path(item["path"]).name + "/" + item["division"] + "/" + item["section_no"]
             for item in report["results"] if item["ok"]}
    chunks = [json.loads(line) for line in
              (ROOT / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    label_shift = {chunk["chunk_id"] for chunk in chunks
                   if any(str(issue).startswith("label_shift") for issue in chunk.get("issues", []))}

    before = Counter(baseline_status.values())
    after = Counter(before)
    outcomes = []
    excluded = misfiled_ids()
    expected_improvements = {
        "2026-정오표1차/기계설비/13-7-2/노정장입장치기기설치",
        "2026-정오표1차/기계설비/13-7-3/노체4본주및DECK설치",
    }
    for path in sorted((ROOT / "data/drafts/specs").rglob("*.json")):
        package = json.loads(path.read_text(encoding="utf-8"))
        spec = package["draft"]
        if package.get("calc_type") != "per_unit" or not has_ton_conversion_surface(spec):
            continue
        identifier = spec["id"]
        if identifier in excluded:
            continue
        key = path.name + "/" + spec["division"] + "/" + spec["section_no"]
        if key not in valid:
            new_status, reason = "fail", "형식 또는 인용 불일치"
        elif any(ref in label_shift for ref in _referenced_ids(spec)):
            new_status, reason = "fail", "표 이름 줄 밀림 — 원문 재확인 필요"
        else:
            new_status, reason = evaluate_spec(spec)
        old_status = baseline_status.get(identifier, "not_in_baseline")
        if old_status not in ("pass", "fail"):
            continue
        if new_status == "failed":
            new_status = "fail"
        if old_status != new_status:
            after[old_status] -= 1
            after[new_status] += 1
        outcomes.append({"id": identifier, "before": old_status, "after": new_status, "reason": reason})

    changed = {item["id"] for item in outcomes if item["before"] != item["after"]}
    if changed != expected_improvements:
        print(json.dumps({"candidate_count": len(outcomes), "changed": sorted(changed),
                          "expected": sorted(expected_improvements),
                          "other_deltas": [x for x in outcomes if x["before"] != x["after"]]},
                         ensure_ascii=False, indent=2))
        return 1
    print(f"PASS targeted per_unit ton-family cases {len(outcomes)}; only 13-7-2/3 fail→pass")
    print(json.dumps({"before": before, "after_targeted_delta": after,
                      "changed_ids": sorted(changed)}, ensure_ascii=False, indent=2))
    return 0


def _referenced_ids(value: object) -> set[str]:
    if isinstance(value, dict):
        if set(value) == {"table"} and isinstance(value["table"], str):
            return {value["table"]}
        return set().union(*(_referenced_ids(child) for child in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(_referenced_ids(child) for child in value)) if value else set()
    if isinstance(value, str) and re.fullmatch(r"p\d+-t\d+", value):
        return {value}
    return set()


if __name__ == "__main__":
    raise SystemExit(main())
