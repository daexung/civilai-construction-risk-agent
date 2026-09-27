"""route부터 fill까지 그래프 흐름과 되묻기 재개를 오프라인으로 검사한다."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["AGENT_OFFLINE"] = "1"

from langgraph.types import Command  # noqa: E402

from agent.graph import build_graph  # noqa: E402
from agent.state import new_state  # noqa: E402
from agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from agent.rules.specs import load_specs  # noqa: E402


def interrupted(state: dict) -> bool:
    return bool(state.get("__interrupt__"))


def questions_of(state: dict) -> list[dict]:
    return state["__interrupt__"][0].value["questions"]


def main() -> int:
    checks = []

    graph = build_graph()

    state_g1 = graph.invoke(new_state("오늘 현장 날씨 어때?"), {"configurable": {"thread_id": "g1"}})
    checks.append(("G1", state_g1["status"] == "OUT_OF_SCOPE" and state_g1["hits"] == []))

    state_g2 = graph.invoke(new_state("합판거푸집 설치 인건비"), {"configurable": {"thread_id": "g2"}})
    checks.append(("G2", state_g2["status"] == "EVIDENCE_ONLY"))

    config_g3 = {"configurable": {"thread_id": "g3"}}
    state_g3 = graph.invoke(new_state("철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"), config_g3)
    g3_questions = questions_of(state_g3) if interrupted(state_g3) else []
    facility_g3 = next((q for q in g3_questions if q["name"] == "facility_type"), None)
    state_g3 = graph.invoke(Command(resume="15cm 타입2 현장 2유형 붐 진동기 사용 재셋팅 없음"), config_g3)
    calc_g3 = adjusted_daily_crew(load_specs()[state_g3["spec_id"]], state_g3["inputs"]) if state_g3.get("spec_id") else {}
    checks.append(("G3", len(g3_questions) == 6
                   and facility_g3 is not None and facility_g3.get("hint", {}).get("value") == "Type-Ⅱ"
                   and not interrupted(state_g3)
                   and len(state_g3["inputs"]) == 8
                   and calc_g3.get("status") == "computed"
                   and calc_g3.get("person_days", {}).get("콘크리트공") == "8"))

    config_g4 = {"configurable": {"thread_id": "g4"}}
    state_g4 = graph.invoke(new_state("철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"), config_g4)
    state_g4 = graph.invoke(Command(resume="15cm 붐"), config_g4)
    g4_remaining = questions_of(state_g4) if interrupted(state_g4) else []
    state_g4 = graph.invoke(Command(resume="타입2 현장 2유형 진동기 사용 재셋팅 없음"), config_g4)
    checks.append(("G4", len(g4_remaining) == 4 and not interrupted(state_g4)
                   and len(state_g4["inputs"]) == 8))

    config_a = {"configurable": {"thread_id": "g5-a"}}
    config_b = {"configurable": {"thread_id": "g5-b"}}
    state_a = graph.invoke(new_state("철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"), config_a)
    state_b = graph.invoke(new_state("무근콘크리트 슬래브 100㎥ 펌프차로 타설 비용"), config_b)
    state_b = graph.invoke(Command(resume="8~12cm 배관 타입1 현장 1유형 진동기 없이 재셋팅 있음"), config_b)
    state_a = graph.invoke(Command(resume="15cm 타입2 현장 2유형 붐 진동기 사용 재셋팅 없음"), config_a)
    checks.append(("G5", not interrupted(state_a) and not interrupted(state_b)
                   and state_a["inputs"]["structure"] == "철근" and state_a["inputs"]["volume"] == "260"
                   and state_b["inputs"]["structure"] == "무근" and state_b["inputs"]["volume"] == "100"))

    checks.append(("G6", isinstance(json.dumps(state_g3, ensure_ascii=False), str)))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    if not all(passed for _, passed in checks):
        print("G3 questions:", [q["name"] for q in g3_questions], "inputs:", state_g3.get("inputs"))
        print("G4 remaining:", [q["name"] for q in g4_remaining], "inputs:", state_g4.get("inputs"))
        print("G5 a:", state_a.get("inputs"), "b:", state_b.get("inputs"))
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
