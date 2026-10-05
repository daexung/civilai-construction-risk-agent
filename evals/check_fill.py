"""검색 없이 6-1-4 fill의 추출, 확인 질문, 계산 연결을 검사한다."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.nodes.fill import extract_inputs, fill  # noqa: E402
from agent.rules.specs import load_specs  # noqa: E402
from agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402


SPEC = next(spec for spec in load_specs().values() if spec["section_no"] == "6-1-4")
CANDIDATES = [
    {"section_no": "6-1-4", "section": "6-1-4 콘크리트 펌프차 타설"},
    {"section_no": "6-1-1", "section": "6-1-1 레디믹스트콘크리트 타설"},
    {"section_no": "6-1-2", "section": "6-1-2 현장비빔 타설"},
]
COMPLETE = "기타 토목공사 6개월 종합건설업 이 견적만 철근 260㎥ 펌프차 32m 슬럼프 15cm Type-Ⅱ 현장조건 Type-Ⅱ 붐타설 진동기 사용 재셋팅 없음 레미콘 관급"


def state(query: str, *, confirmed: bool = True, inputs: dict | None = None, reply="") -> dict:
    return {"query": query, "status": "RUNNING", "spec_id": SPEC["id"],
            "selection": {"decision": "chosen" if confirmed else "provisional", "confirmed": confirmed},
            "candidates": CANDIDATES, "inputs": inputs or {},
            "input_sources": {name: "질문" for name in (inputs or {})}, "reply": reply}


def main() -> int:
    checks = []
    first = fill(state("철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"))
    names = [question["name"] for question in first["questions"]]
    pump_size = next(question for question in first["questions"] if question["name"] == "pump_size")
    facility = next(question for question in first["questions"] if question["name"] == "facility_type")
    checks.append(("F1", first["inputs"] == {"volume": "260", "structure": "철근", "work_category": "기타 토목공사",
                                             "duration": "1~6개월", "contractor_type": "종합건설업",
                                             "project_scale": "이 견적만"}
                   and not {"work_category", "duration", "contractor_type", "project_scale"} & set(names)
                   and first["input_sources"]["work_category"] == "기본값(부문)"
                   and all(first["input_sources"][n] == "기본값" for n in
                           ("duration", "contractor_type", "project_scale"))
                   and pump_size["choices"] == ["32m", "36m", "41m", "43m", "47m", "52m"]
                   and facility.get("hint") == {"value": "Type-Ⅱ", "matched": "벽"}))

    complete = fill(state(COMPLETE))
    checks.append(("F2", not complete["questions"] and "status" not in complete
                    and len(complete["inputs"]) == 14
                   and extract_inputs("철근 260㎥ 15cm", SPEC)[0]["volume"] == "260"
                   and complete["inputs"]["facility_type"] == "Type-Ⅱ"
                   and complete["inputs"]["site_type"] == "Type-Ⅱ"
                   and complete["inputs"]["reset_status"] == "없음"
                   and complete["inputs"]["concrete_supply"] == "관급"))

    two_structures = fill(state("무근 철근 100㎥ 펌프차 타설"))
    checks.append(("F3", "structure" not in two_structures["inputs"] and any(
        question["name"] == "structure" and question.get("reason") for question in two_structures["questions"])))

    two_volumes = fill(state("철근 100㎥ 또는 120㎥"))
    checks.append(("F4", "volume" not in two_volumes["inputs"] and any(
        question["name"] == "volume" and question.get("reason") for question in two_volumes["questions"])))

    no_unit = fill(state("철근 100 펌프차 타설"))
    checks.append(("F5", "volume" not in no_unit["inputs"] and any(
        question["name"] == "volume" and "단위" in question.get("reason", "") for question in no_unit["questions"])))

    inherited = fill(state("기타 토목공사 6개월 종합건설업 15cm, 타입2, 현장 2유형, 붐, 진동기 사용, 재셋팅 없음, 레미콘 관급",
                           inputs={"volume": "260", "structure": "철근", "pump_size": "32m"}))
    checks.append(("F6", len(inherited["inputs"]) == 14 and not inherited["questions"]
                   and inherited["input_sources"]["volume"] == "질문"
                   and inherited["input_sources"]["slump_band"] == "답변"))

    provisional = fill(state(COMPLETE, confirmed=False))
    checks.append(("F7", provisional["status"] == "MISSING_INFO"
                   and provisional["questions"][0]["name"] == "work"
                   and provisional["questions"][0]["default"] == "6-1-4"
                   and len(provisional["questions"][0]["choices"]) == 3))

    calculated = adjusted_daily_crew(SPEC, {name: value for name, value in complete["inputs"].items()
                                            if name in {field["name"] for field in SPEC["inputs"]}})
    checks.append(("F8", calculated["status"] == "computed"))

    dict_answers = {"pump_size": "32m", "slump_band": "15㎝", "facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ",
                     "placement": "붐", "vibrator_used": True, "reset_status": "없음", "concrete_supply": "관급",
                     "work_category": "기타 토목공사", "duration": "1~6개월",
                     "contractor_type": "종합건설업", "project_scale": "이 견적만"}
    dict_complete = fill(state("", inputs=first["inputs"], reply=dict_answers))
    checks.append(("F9", not dict_complete["questions"] and "status" not in dict_complete
                    and len(dict_complete["inputs"]) == 14
                   and dict_complete["inputs"]["vibrator_used"] is True
                   and dict_complete["input_sources"]["slump_band"] == "선택"
                   and dict_complete["input_sources"]["vibrator_used"] == "선택"))

    bad_dict = {**dict_answers, "facility_type": "Type-X"}
    dict_partial = fill(state("", inputs=first["inputs"], reply=bad_dict))
    checks.append(("F10", "facility_type" not in dict_partial["inputs"]
                   and dict_partial["inputs"].get("slump_band") == "15㎝"
                   and any(question["name"] == "facility_type" and question.get("reason") == "허용값이 아닙니다"
                           for question in dict_partial["questions"])))

    combo_reply = {"answers": {"vibrator_used": True}, "text": "기타 토목공사 6개월 종합건설업 펌프차 32m 15cm 타입2 현장 2유형 붐 재셋팅 없음 레미콘 관급"}
    combo = fill(state("", inputs=first["inputs"], reply=combo_reply))
    checks.append(("F11", not combo["questions"] and len(combo["inputs"]) == 14
                   and combo["input_sources"]["vibrator_used"] == "선택"
                   and combo["input_sources"]["slump_band"] == "답변"))

    provisional_state = state(COMPLETE, confirmed=False)
    first_provisional = fill(provisional_state)
    resumed_work = fill({**provisional_state, "reply": {"work": "6-1-4"},
                        "inputs": first_provisional["inputs"],
                        "input_sources": first_provisional["input_sources"]})
    checks.append(("F12", resumed_work.get("selection", {}).get("confirmed") is True
                   and resumed_work.get("selection", {}).get("section_no") == "6-1-4"
                   and not resumed_work["questions"] and "status" not in resumed_work
                    and len(resumed_work["inputs"]) == 14))

    bad_work = fill({**provisional_state, "reply": {"work": "9-9-9"},
                     "inputs": first_provisional["inputs"],
                     "input_sources": first_provisional["input_sources"]})
    checks.append(("F13", bad_work["status"] == "MISSING_INFO"
                   and bad_work["questions"][0]["name"] == "work"
                   and bad_work["questions"][0].get("reason") == "선택한 공종을 후보에서 찾을 수 없습니다"))

    apt = fill(state("아파트 철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"))
    checks.append(("F14 아파트 → 건축", apt["inputs"]["work_category"] == "주택 외 건축"
                   and apt["input_sources"]["work_category"] == "질문"
                   and apt["input_sources"]["duration"] == "기본값"))
    months = fill(state("도로 공사 철근콘크리트 벽체 260㎥ 펌프차로 타설 비용 8개월"))
    checks.append(("F15 N개월 → 기간 구간", months["inputs"]["duration"] == "7~12개월"
                   and months["inputs"]["work_category"] == "도로"
                   and months["input_sources"]["duration"] == "질문"))
    sub = fill(state("하도급 전문건설 철근콘크리트 벽체 260㎥ 펌프차로 타설 비용 전체 공사 30억"))
    checks.append(("F16 전문건설·전체 규모", sub["inputs"]["contractor_type"] == "전문건설업"
                   and sub["inputs"]["project_scale"] == "3000000000"
                   and sub["input_sources"]["project_scale"] == "질문"))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    if not all(passed for _, passed in checks):
        print("F2 inputs:", complete["inputs"], "questions:", [q["name"] for q in complete["questions"]])
        print("F6 inputs:", inherited["inputs"], "questions:", [q["name"] for q in inherited["questions"]])
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
