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

import agent.nodes.compute as compute_module  # noqa: E402
from agent.graph import build_graph  # noqa: E402
from agent.state import new_state  # noqa: E402


QUERY = "철근콘크리트 벽체 260㎥ 32m 펌프차로 타설 비용"
COMPLETE = "기타 토목공사 6개월 종합건설업 이 견적만 15cm 타입2 현장 2유형 붐 진동기 사용 재셋팅 없음 레미콘 관급"


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
    checks.append(("G2", evidence["status"] == "MISSING_INFO" and bool(questions(evidence))))

    initial = graph.invoke(new_state(QUERY), config("g3"))
    first_questions = questions(initial)
    facility = next((item for item in first_questions if item["name"] == "facility_type"), {})
    completed = graph.invoke(Command(resume=COMPLETE), config("g3"))
    checks.append(("G3", len(first_questions) == 7
                   and facility.get("hint") == {"value": "Type-Ⅱ", "matched": "벽"}
                   and completed["status"] == "PARTIAL" and not questions(completed)
                    and len(completed["inputs"]) == 14
                   and completed["result"]["person_days"]["콘크리트공"] == "8"
                   and completed["result"]["equipment_days"]["콘크리트펌프차"] == "2"))

    graph.invoke(new_state(QUERY), config("g4"))
    partial = graph.invoke(Command(resume="15cm 붐"), config("g4"))
    remaining = questions(partial)
    finished = graph.invoke(Command(resume="기타 토목공사 6개월 종합건설업 이 견적만 타입2 현장 2유형 진동기 사용 재셋팅 없음 레미콘 관급"), config("g4"))
    checks.append(("G4", len(remaining) == 5 and not questions(finished)
                    and len(finished["inputs"]) == 14 and finished["status"] == "PARTIAL"))

    graph.invoke(new_state(QUERY), config("g5a"))
    other = graph.invoke(new_state("오늘 현장 날씨 어때?"), config("g5b"))
    saved_a = graph.get_state(config("g5a"))
    saved_b = graph.get_state(config("g5b"))
    checks.append(("G5", len(saved_a.values["questions"]) == 7
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
                                                  "vibrator_used": True, "reset_status": "없음",
                                                  "concrete_supply": "관급", "work_category": "기타 토목공사",
                                                  "duration": "1~6개월", "contractor_type": "종합건설업",
                                                  "project_scale": "이 견적만"}), config("g7"))
    checks.append(("G7", not questions(dict_completed) and dict_completed["status"] == "PARTIAL"
                    and len(dict_completed["inputs"]) == 14
                   and dict_completed["input_sources"]["vibrator_used"] == "선택"))

    graph.invoke(new_state(QUERY), config("g8"))
    bad_dict_result = graph.invoke(Command(resume={"slump_band": "15㎝", "facility_type": "Type-X",
                                                   "site_type": "Type-Ⅱ", "placement": "붐",
                                                   "vibrator_used": True, "reset_status": "없음",
                                                    "concrete_supply": "관급", "work_category": "기타 토목공사",
                                                    "duration": "1~6개월", "contractor_type": "종합건설업",
                                                    "project_scale": "이 견적만"}), config("g8"))
    bad_questions = questions(bad_dict_result)
    checks.append(("G8", any(question["name"] == "facility_type" and question.get("reason")
                             for question in bad_questions)))

    graph.invoke(new_state(QUERY), config("g9"))
    reset_present = graph.invoke(Command(resume="기타 토목공사 6개월 종합건설업 15cm 타입2 현장 2유형 붐 진동기 사용 재셋팅 있음 레미콘 관급"), config("g9"))
    checks.append(("G9", reset_present["status"] == "BLOCKED" and not questions(reset_present)
                   and reset_present["result"]["input"] == "reset_status"))

    graph.invoke(new_state(QUERY), config("g10"))
    reset_unknown = graph.invoke(Command(resume="기타 토목공사 6개월 종합건설업 15cm 타입2 현장 2유형 붐 진동기 사용 재셋팅 모름 레미콘 관급"), config("g10"))
    checks.append(("G10", reset_unknown["status"] == "BLOCKED" and not questions(reset_unknown)
                   and reset_unknown["result"]["input"] == "reset_status"))

    graph.invoke(new_state("철근콘크리트 100㎥ 32m 펌프차로 타설"), config("g11"))
    case_d = graph.invoke(Command(resume={
        "slump_band": "18㎝이상", "facility_type": "Type-Ⅲ", "site_type": "Type-Ⅲ",
        "placement": "붐", "vibrator_used": True, "reset_status": "없음", "concrete_supply": "관급",
        "work_category": "기타 토목공사", "duration": "1~6개월", "contractor_type": "종합건설업",
        "project_scale": "이 견적만",
    }), config("g11"))
    checks.append(("G11", case_d["status"] == "PARTIAL"
                   and case_d["result"]["person_days"]["콘크리트공"] == "125/28"))

    fake_spec = {"quantity_model": {"name": "no_such_calculator"}}
    original_load_specs = compute_module.load_specs
    compute_module.load_specs = lambda: {"fake": fake_spec}
    try:
        unregistered = compute_module.compute({"spec_id": "fake", "inputs": {}})
    finally:
        compute_module.load_specs = original_load_specs
    checks.append(("G12", unregistered["status"] == "ERROR" and "no_such_calculator" in unregistered["reason"]))

    unit_lines = {line["name"]: line for line in completed["result"].get("unit_lines", [])}
    checks.append(("G13", completed["result"].get("unit_basis") == {
        "per": "1㎥", "daily_output": "130", "places": 4,
        "adjustable_note": "1-2-8은 조정 가능 조항. 기본 자릿수 적용",
    } and unit_lines.get("콘크리트공", {}).get("exact") == "2/65"
                   and unit_lines.get("콘크리트공", {}).get("applied") == "0.0308"
                   and unit_lines.get("콘크리트펌프차", {}).get("applied") == "0.0615"))

    draft_cases = [
        ("R1", "레디믹스트 콘크리트 100㎥ 인력운반 타설 비용", "6-1-1",
         {"placement_method": "인력운반 타설", "structure": "철근구조물", "volume": "100",
          "scattered_small_volume": False, "concrete_supply": "관급"}, "68693", 13150196),
        ("M1", "현장비빔타설 기계비빔 철근구조물 100㎥ 비용", "6-1-2",
         {"mixing_type": "기계비빔타설", "structure": "수량 철근구조물", "volume": "100"},
         "164403", 31648540),
        ("S1", "콘크리트 표면 마무리 200㎡ 비용", "6-1-3",
         {"area": "200"}, "948", 364982),
    ]
    for label, query, section, values, total, contract in draft_cases:
        thread = f"draft-{label}"
        start = graph.invoke(new_state(query, "2026-10-01"), config(thread))
        answers = {**values, **({"work": section} if any(q["name"] == "work" for q in questions(start)) else {})}
        done = graph.invoke(Command(resume=answers), config(thread))
        checks.append((f"G14 {label} 질문·답변·가격", bool(questions(start))
                       and not questions(done) and done.get("status") in ("OK", "PARTIAL")
                       and done.get("review_status") == "AI 초안 · 검토 전"
                       and done["priced"]["total"] == total
                       and done["statement"]["totals"]["contract_amount"] == contract))

    epoxy_inputs = {"area": "100", "type": "신구-콘크리트 접착제바르기",
                    "ceiling_applied": False, "scaffold_used": False,
                    "floor_level": "지하층 및 1∼3층", "floor_level_19_plus": 19,
                    "thickness_adjusted": False, "thickness": "1"}
    for label, ceiling, scaffold, total, contract in (
            ("E0", False, False, "32830", 6284801),
            ("E1", True, False, "39396", 7541741),
            ("E2", True, True, None, None)):
        thread = f"draft-{label}"
        start = graph.invoke(new_state("에폭시 콘크리트 접착제 바르기 100㎡ 비용", "2026-10-01"), config(thread))
        answers = {**epoxy_inputs, "ceiling_applied": ceiling, "scaffold_used": scaffold}
        if any(q["name"] == "work" for q in questions(start)):
            answers["work"] = "6-1-5"
        done = graph.invoke(Command(resume=answers), config(thread))
        if label == "E2":
            ok = (done.get("status") == "BLOCKED"
                  and done.get("result", {}).get("citations", [{}])[0].get("internal_id") == "p188-x6")
        else:
            ok = (done.get("status") == "PARTIAL" and done["priced"]["total"] == total
                  and done["statement"]["totals"]["contract_amount"] == contract)
        checks.append((f"G15 {label} 에폭시", ok))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
