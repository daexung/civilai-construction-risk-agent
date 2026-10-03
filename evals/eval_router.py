"""고정 시험지로 LLM/규칙 라우터를 따로 채점하고 같은 보고서에서 비교한다.

AGENT_LLM=on일 때 실제 LLM을 호출한다. run_quick/run_all에서는 실행하지 않는다.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.nodes.route import route  # noqa: E402
from agent.state import new_state  # noqa: E402

LABELS = ("estimate", "qa", "out_of_scope")
CRITERIA = {"overall_accuracy_min": 0.9, "boundary_accuracy_min": 0.8,
            "estimate_to_out_of_scope_max": 0, "mean_latency_ms_max": 1500}
TESTSET = ROOT / "evals/router_testset.jsonl"
RESULTS = ROOT / "evals/results"


def evaluate(cases: list[dict]) -> dict:
    rows = []
    for case in cases:
        state = new_state(case["q"])
        if case.get("context"):
            state["previous_context"] = case["context"]
        started = time.monotonic()
        outcome = route(state)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        rows.append({
            "id": case["id"], "question": case["q"], "expected": case["label"],
            "predicted": outcome["route"], "confidence": outcome["route_confidence"],
            "source": outcome["route_source"], "reason": outcome["route_reason"],
            "latency_ms": elapsed_ms, "boundary": case.get("boundary", False),
            "correct": case["label"] == outcome["route"],
        })
    boundary = [row for row in rows if row["boundary"]]
    matrix = {expected: {predicted: sum(row["expected"] == expected and row["predicted"] == predicted
                                        for row in rows) for predicted in LABELS} for expected in LABELS}
    summary = {
        "count": len(rows), "overall_accuracy": sum(row["correct"] for row in rows) / len(rows),
        "boundary_count": len(boundary),
        "boundary_accuracy": sum(row["correct"] for row in boundary) / len(boundary),
        "confusion_matrix": matrix,
        "estimate_to_out_of_scope": matrix["estimate"]["out_of_scope"],
        "mean_latency_ms": round(sum(row["latency_ms"] for row in rows) / len(rows), 1),
        "max_latency_ms": max(row["latency_ms"] for row in rows),
        "rule_fallback_count": sum(row["source"] == "rule" for row in rows),
        "low_confidence_count": sum(row["source"] == "llm_low_confidence" for row in rows),
        "wrong": [{key: row[key] for key in ("id", "question", "expected", "predicted", "reason")}
                  for row in rows if not row["correct"]],
    }
    summary["criteria_pass"] = {
        "overall_accuracy": summary["overall_accuracy"] >= CRITERIA["overall_accuracy_min"],
        "boundary_accuracy": summary["boundary_accuracy"] >= CRITERIA["boundary_accuracy_min"],
        "estimate_to_out_of_scope": summary["estimate_to_out_of_scope"] <= CRITERIA["estimate_to_out_of_scope_max"],
        "mean_latency_ms": summary["mean_latency_ms"] <= CRITERIA["mean_latency_ms_max"],
    }
    return {"summary": summary, "items": rows}


def _print_summary(mode: str, summary: dict) -> None:
    print(f"\n{mode}: 전체 {summary['overall_accuracy']:.1%} ({summary['count']}문항), "
          f"boundary {summary['boundary_accuracy']:.1%} ({summary['boundary_count']}문항)")
    print(f"estimate→out_of_scope {summary['estimate_to_out_of_scope']}건, "
          f"지연 평균 {summary['mean_latency_ms']}ms / 최대 {summary['max_latency_ms']}ms, "
          f"규칙 대체 {summary['rule_fallback_count']}건, 낮은 확신 {summary['low_confidence_count']}건")
    print("혼동표 (정답 행 / 예측 열):", " | ".join(LABELS))
    for label in LABELS:
        print(label, " | ".join(str(summary["confusion_matrix"][label][predicted]) for predicted in LABELS))
    print("틀린 문항:")
    for item in summary["wrong"]:
        print(f"- {item['id']} {item['question']} | 정답 {item['expected']} | 예측 {item['predicted']} | {item['reason']}")


def main() -> int:
    setting = os.environ.get("AGENT_LLM", "off")
    if setting not in ("on", "off"):
        raise SystemExit("AGENT_LLM은 on 또는 off로 설정하세요")
    mode = "llm" if setting == "on" else "rule"
    cases = [json.loads(line) for line in TESTSET.read_text(encoding="utf-8").splitlines() if line]
    if len(cases) != 46 or len({case["id"] for case in cases}) != 46:
        raise SystemExit("라우터 시험지가 원본 46문항과 다릅니다")
    result = evaluate(cases)
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"router_{date.today().isoformat()}.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "testset": "evals/router_testset.jsonl", "criteria": CRITERIA, "modes": {}}
    report["modes"][mode] = result
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _print_summary(mode, result["summary"])
    if len(report["modes"]) == 2:
        print("\n비교 (규칙 / LLM):")
        for name, key in (("전체 정답률", "overall_accuracy"), ("boundary 정답률", "boundary_accuracy"),
                          ("estimate→범위 밖", "estimate_to_out_of_scope"), ("평균 지연(ms)", "mean_latency_ms")):
            print(f"{name}: {report['modes']['rule']['summary'][key]} / {report['modes']['llm']['summary'][key]}")
    print("합격 기준:", CRITERIA)
    print("LLM 판정:", result["summary"]["criteria_pass"] if mode == "llm" else "미실행")
    print("결과:", path)
    return 0 if mode == "rule" or all(result["summary"]["criteria_pass"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
