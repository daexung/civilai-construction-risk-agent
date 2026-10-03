"""전체 명세 초안을 오프라인 계산기로 시험하고 실행 가능 목록을 저장한다."""

from __future__ import annotations

import itertools
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from agent.tools.calc.per_unit import per_unit  # noqa: E402
from agent.tools.calc.adjustments import classify_adjustment  # noqa: E402

CALCULATORS = {"daily_crew": adjusted_daily_crew, "per_unit": per_unit}
OUTPUT = ROOT / "data/drafts/executable.json"


def _values(field: dict, blocked: list[dict] | None = None,
            adjustments: list[dict] | None = None) -> list:
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
    if kind in ("positive_rational", "nonnegative_integer"):
        lower = re.search(r"(\d+)\s*이상의\s*정수", str(field.get("allowed_values", "")))
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
        if blocked:
            return ["0" if kind == "nonnegative_integer" else "1"]
        return ["100"]
    return []


def evaluate() -> dict:
    report = json.loads((ROOT / "data/drafts/report.json").read_text(encoding="utf-8"))
    valid = {Path(item["path"]).name + "/" + item["division"] + "/" + item["section_no"]
             for item in report["results"] if item["ok"]}
    attempts = Counter()
    success = Counter()
    reasons = Counter()
    executable = []
    failed = []
    chapter = defaultdict(lambda: Counter())
    adjustment_counts = Counter()
    for path in sorted((ROOT / "data/drafts/specs").rglob("*.json")):
        package = json.loads(path.read_text(encoding="utf-8"))
        spec = package["draft"]
        kind = package["calc_type"]
        scope = "공통/6장" if spec["division"] == "공통" and spec["section_no"].startswith("6-") else "기타"
        chapter[scope]["total"] += 1
        if kind not in CALCULATORS:
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
            choices = [_values(field, blocked_by_field[field["name"]], adjustments) for field in fields]
            if any(not options for options in choices):
                reason = "입력 타입 미지원"
            else:
                reason = ""
                base_computed = False
                for index, values in enumerate(itertools.islice(itertools.product(*choices), 64)):
                    inputs = dict(zip((field["name"] for field in fields), values))
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
            failed.append({"id": spec["id"], "reason": reason})
            reasons[reason.split(":", 1)[0]] += 1
        else:
            executable.append(spec["id"])
            success[kind] += 1
            chapter[scope]["executable"] += 1
    return {"executable": sorted(executable), "failed": failed,
            "summary": {"total": sum(value["total"] for value in chapter.values()),
                        "by_calc_type": {kind: {"attempted": attempts[kind], "executable": success[kind]}
                                         for kind in CALCULATORS},
                        "failure_reasons_top10": reasons.most_common(10),
                        "by_scope": dict(chapter),
                        "adjustment_items": dict(adjustment_counts)}}


def main() -> int:
    result = evaluate()
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"실행 가능 {len(result['executable'])} / 시도 {len(result['executable']) + len(result['failed'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
