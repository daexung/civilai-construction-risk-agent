"""오프라인 검색으로 route부터 fill까지의 중단·재개를 검사한다."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["AGENT_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langgraph.types import Command  # noqa: E402

from agent.graph import build_graph  # noqa: E402
from agent.rules.specs import load_specs  # noqa: E402
from agent.state import new_state  # noqa: E402
from agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402


QUERY = "철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"
COMPLETE = "15cm 타입2 현장 2유형 붐 진동기 사용 재셋팅 없음"


def config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def questions(result: dict) -> list[dict]:
    interrupts = result.get("__interrupt__", [])
    return interrupts[0].value["questions"] if interrupts else []


def main() -> int:
    graph = build_graph()
    checks = []

    outside = graph.invoke(new_state("오늘 현장 날씨 어때?"), config("g1"))
    checks.append(("G1", outside["status"] == "OUT_OF_SCOPE" and not outside["hits"]
                   and not outside.get("__interrupt__")))

    evidence = graph.invoke(new_state("합판거푸집 설치 인건비"), config("g2"))
    checks.append(("G2", evidence["status"] == "EVIDENCE_ONLY" and not evidence.get("__interrupt__")))

    initial = graph.invoke(new_state(QUERY), config("g3"))
    first_questions = questions(initial)
    facility = next((item for item in first_questions if item["name"] == "facility_type"), {})
    completed = graph.invoke(Command(resume=COMPLETE), config("g3"))
    spec = load_specs()[completed["spec_id"]]
    calculation = adjusted_daily_crew(spec, completed["inputs"])
    checks.append(("G3", len(first_questions) == 6
                   and facility.get("hint") == {"value": "Type-Ⅱ", "matched": "벽"}
                   and completed["status"] == "RUNNING" and not questions(completed)
                   and len(completed["inputs"]) == 8
                   and calculation["status"] == "computed"
                   and calculation["person_days"]["콘크리트공"] == "8"))

    graph.invoke(new_state(QUERY), config("g4"))
    partial = graph.invoke(Command(resume="15cm 붐"), config("g4"))
    remaining = questions(partial)
    finished = graph.invoke(Command(resume="타입2 현장 2유형 진동기 사용 재셋팅 없음"), config("g4"))
    checks.append(("G4", len(remaining) == 4 and not questions(finished)
                   and len(finished["inputs"]) == 8 and finished["status"] == "RUNNING"))

    graph.invoke(new_state(QUERY), config("g5a"))
    other = graph.invoke(new_state("오늘 현장 날씨 어때?"), config("g5b"))
    saved_a = graph.get_state(config("g5a"))
    saved_b = graph.get_state(config("g5b"))
    checks.append(("G5", len(saved_a.values["questions"]) == 6
                   and saved_a.values["query"] == QUERY
                   and saved_b.values["query"] == "오늘 현장 날씨 어때?"
                   and saved_b.values["status"] == "OUT_OF_SCOPE"
                   and other["status"] == "OUT_OF_SCOPE"))

    try:
        json.dumps({key: value for key, value in completed.items() if key != "__interrupt__"}, ensure_ascii=False)
        json.dumps(graph.get_state(config("g3")).values, ensure_ascii=False)
        serializable = True
    except (TypeError, ValueError):
        serializable = False
    checks.append(("G6", serializable))

    graph.invoke(new_state(QUERY), config("g7"))
    dict_completed = graph.invoke(Command(resume={"slump_band": "15㎝", "facility_type": "Type-Ⅱ",
                                                  "site_type": "Type-Ⅱ", "placement": "붐",
                                                  "vibrator_used": True, "reset_status": "없음"}), config("g7"))
    checks.append(("G7", not questions(dict_completed) and dict_completed["status"] == "RUNNING"
                   and len(dict_completed["inputs"]) == 8
                   and dict_completed["input_sources"]["vibrator_used"] == "선택"))

    graph.invoke(new_state(QUERY), config("g8"))
    bad_dict_result = graph.invoke(Command(resume={"slump_band": "15㎝", "facility_type": "Type-X",
                                                   "site_type": "Type-Ⅱ", "placement": "붐",
                                                   "vibrator_used": True, "reset_status": "없음"}), config("g8"))
    bad_questions = questions(bad_dict_result)
    checks.append(("G8", any(question["name"] == "facility_type" and question.get("reason")
                             for question in bad_questions)))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
