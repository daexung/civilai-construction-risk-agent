"""Run response-quality evals against the current construction risk agent graph.

This script intentionally treats the graph as a black box. It does not patch,
mock, or relax agent behavior. A failing import, missing dependency, DB error,
or model/API error is recorded as an eval failure because it prevents the
current agent from producing a measurable answer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ROUTER_DIR = ROOT / "agents" / "router"
DEFAULT_CASES = Path(__file__).with_name("eval_cases.json")
DEFAULT_OUT_DIR = Path(__file__).with_name("results")


def _load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        cases = json.load(f)
    if not isinstance(cases, list):
        raise ValueError("eval_cases.json must contain a list")
    return cases


def _number_variants(value: int | float) -> set[str]:
    n = int(value)
    return {
        str(n),
        f"{n:,}",
        f"{n:,}원",
        str(n).replace(",", ""),
    }


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _contains_number(haystack: str, value: int | float) -> bool:
    compact = _compact(haystack).replace(",", "")
    return str(int(value)) in compact


def _contains_phrase(haystack: str, phrase: str) -> bool:
    return _compact(phrase) in _compact(haystack)


def _get_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _extract_delay_days(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"-?\d+", str(value))
    return int(match.group(0)) if match else None


def _build_haystack(result: dict[str, Any]) -> str:
    parts = [
        result.get("final_response") or "",
        _json_text(result.get("structured_response") or {}),
        _json_text(result.get("selected_state") or {}),
    ]
    return "\n".join(parts)


def _score_case(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    haystack = _build_haystack(result)
    structured = result.get("structured_response") or {}
    summary = structured.get("summary") if isinstance(structured, dict) else {}
    summary = summary or {}

    if result.get("runner_error"):
        failures.append(f"runner_error: {result['runner_error']}")
        return {
            "case_id": case["id"],
            "category": case.get("category"),
            "pass": False,
            "failures": failures,
            "actual_answer_type": None,
            "summary": {},
        }

    expected_type = case.get("expected_answer_type")
    actual_type = structured.get("answer_type") if isinstance(structured, dict) else None
    if expected_type and actual_type != expected_type:
        failures.append(f"answer_type expected {expected_type}, got {actual_type}")

    for phrase in case.get("required_contains") or []:
        if not _contains_phrase(haystack, phrase):
            failures.append(f"missing required phrase: {phrase}")

    for phrase in case.get("forbidden_contains") or []:
        if _contains_phrase(haystack, phrase):
            failures.append(f"forbidden phrase present: {phrase}")

    calculations = case.get("expected_calculations") or {}
    for key in ("material_cost_krw", "current_price_reference_krw", "price_diff_reference_krw"):
        if key in calculations and not _contains_number(haystack, calculations[key]):
            failures.append(f"missing calculation value {key}={calculations[key]}")

    if "labor_man_days" in calculations:
        for role, man_days in calculations["labor_man_days"].items():
            if not _contains_phrase(haystack, role):
                failures.append(f"missing labor role: {role}")
            if not (
                _contains_phrase(haystack, f"{man_days}인일")
                or _contains_phrase(haystack, f"× {man_days}")
                or _contains_phrase(haystack, f"* {man_days}")
            ):
                failures.append(f"missing labor man-days for {role}: {man_days}")

    for phrase in calculations.get("total_expression_contains") or []:
        if not _contains_phrase(haystack, phrase):
            failures.append(f"missing total expression phrase: {phrase}")

    if "recognition_rate" in calculations:
        rate = calculations["recognition_rate"]
        percent = f"{int(float(rate) * 100)}%"
        if not (_contains_phrase(haystack, percent) or _contains_phrase(haystack, str(rate))):
            failures.append(f"missing recognition_rate: {rate}")

    if "standby_days" in calculations:
        days = calculations["standby_days"]
        if not (_contains_phrase(haystack, f"{days}일") or _contains_phrase(haystack, str(days))):
            failures.append(f"missing standby_days: {days}")

    risk = case.get("expected_risk")
    if risk:
        actual_risk = summary.get("risk_level")
        actual_delay = _extract_delay_days(summary.get("expected_delay") or summary.get("delay_days"))
        if "risk_level" in risk and actual_risk != risk["risk_level"]:
            failures.append(f"risk_level expected {risk['risk_level']}, got {actual_risk}")
        if "risk_level_not" in risk and str(actual_risk) == str(risk["risk_level_not"]):
            failures.append(f"risk_level must not be {risk['risk_level_not']}")
        if "expected_delay_days" in risk and actual_delay != risk["expected_delay_days"]:
            failures.append(f"expected_delay_days expected {risk['expected_delay_days']}, got {actual_delay}")
        if "expected_delay_days_min" in risk:
            if actual_delay is None or actual_delay < risk["expected_delay_days_min"]:
                failures.append(
                    f"expected_delay_days_min expected >= {risk['expected_delay_days_min']}, got {actual_delay}"
                )
        for key in ("weather_extra_cost_krw", "equipment_standby_cost_krw"):
            if key in risk and not _contains_number(haystack, risk[key]):
                failures.append(f"missing risk value {key}={risk[key]}")

    return {
        "case_id": case["id"],
        "category": case.get("category"),
        "pass": not failures,
        "failures": failures,
        "actual_answer_type": actual_type,
        "summary": summary,
    }


def _load_graph():
    if str(ROUTER_DIR) not in sys.path:
        sys.path.insert(0, str(ROUTER_DIR))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from graph import graph  # type: ignore

    from langchain_core.messages import HumanMessage  # type: ignore

    return graph, HumanMessage


def _run_graph_case(graph: Any, human_message_cls: Any, case: dict[str, Any]) -> dict[str, Any]:
    try:
        state = {
            "messages": [human_message_cls(content=case["question"])],
            "project_id": case.get("project_id") or "PJT-001",
        }
        result = graph.invoke(state)
        selected_keys = [
            "answer_type",
            "question_type",
            "needs_weather",
            "target_agents",
            "rag_result",
            "weather_response",
            "equipment_result",
            "material_result",
            "labor_cost_result",
        ]
        return {
            "final_response": result.get("final_response"),
            "structured_response": result.get("structured_response"),
            "selected_state": {key: result.get(key) for key in selected_keys if key in result},
            "runner_error": None,
        }
    except Exception as exc:
        return {
            "final_response": None,
            "structured_response": None,
            "selected_state": {},
            "runner_error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


def _write_markdown(summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Eval Results",
        "",
        f"- Run ID: `{summary['run_id']}`",
        f"- Cases: {summary['total_cases']}",
        f"- Passed: {summary['passed']}",
        f"- Failed: {summary['failed']}",
        "",
        "## Failures",
        "",
    ]
    failed = [r for r in summary["results"] if not r["score"]["pass"]]
    if not failed:
        lines.append("No failures.")
    for item in failed:
        score = item["score"]
        lines.append(f"### {score['case_id']}")
        lines.append("")
        lines.append(f"- Category: {score.get('category')}")
        lines.append(f"- Actual answer_type: `{score.get('actual_answer_type')}`")
        for failure in score["failures"]:
            lines.append(f"- FAIL: {failure}")
        if item["raw_result"].get("runner_error"):
            lines.append("")
            lines.append("```text")
            lines.append(str(item["raw_result"].get("traceback", "")).strip())
            lines.append("```")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--case-id", action="append", default=None)
    args = parser.parse_args()

    cases = _load_cases(args.cases)
    if args.case_id:
        wanted = set(args.case_id)
        cases = [case for case in cases if case.get("id") in wanted]
        missing = wanted - {case.get("id") for case in cases}
        if missing:
            raise ValueError(f"Unknown case ids: {sorted(missing)}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    graph = None
    human_message_cls = None
    setup_error = None
    try:
        graph, human_message_cls = _load_graph()
    except Exception as exc:
        setup_error = f"{type(exc).__name__}: {exc}"
        setup_traceback = traceback.format_exc()
    else:
        setup_traceback = None

    results = []
    for case in cases:
        if setup_error:
            raw_result = {
                "final_response": None,
                "structured_response": None,
                "selected_state": {},
                "runner_error": f"setup_error: {setup_error}",
                "traceback": setup_traceback,
            }
        else:
            raw_result = _run_graph_case(graph, human_message_cls, case)
        score = _score_case(case, raw_result)
        results.append({
            "case": case,
            "raw_result": raw_result,
            "score": score,
        })

    passed = sum(1 for item in results if item["score"]["pass"])
    summary = {
        "run_id": run_id,
        "total_cases": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "setup_error": setup_error,
        "results": results,
    }

    json_path = args.out_dir / f"eval_results_{run_id}.json"
    md_path = args.out_dir / f"eval_results_{run_id}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _write_markdown(summary, md_path)

    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    print(f"passed={passed} failed={len(results) - passed} total={len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
