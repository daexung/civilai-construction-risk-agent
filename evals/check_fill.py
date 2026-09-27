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
COMPLETE = "철근 260㎥ 슬럼프 15cm Type-Ⅱ 현장조건 Type-Ⅱ 붐타설 진동기 사용 재셋팅 없음"


def state(query: str, *, confirmed: bool = True, inputs: dict | None = None) -> dict:
    return {"query": query, "status": "RUNNING", "spec_id": SPEC["id"],
            "selection": {"decision": "chosen" if confirmed else "provisional", "confirmed": confirmed},
            "candidates": CANDIDATES, "inputs": inputs or {},
            "input_sources": {name: "질문" for name in (inputs or {})}}


def main() -> int:
    checks = []
    first = fill(state("철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"))
    names = [question["name"] for question in first["questions"]]
    facility = next(question for question in first["questions"] if question["name"] == "facility_type")
    checks.append(("F1", first["inputs"] == {"volume": "260", "structure": "철근"}
                   and names == ["slump_band", "facility_type", "site_type", "placement", "vibrator_used", "reset_status"]
                   and facility.get("hint") == {"value": "Type-Ⅱ", "matched": "벽"}))

    complete = fill(state(COMPLETE))
    checks.append(("F2", not complete["questions"] and "status" not in complete
                   and len(complete["inputs"]) == 8
                   and extract_inputs("철근 260㎥ 15cm", SPEC)[0]["volume"] == "260"
                   and complete["inputs"]["facility_type"] == "Type-Ⅱ"
                   and complete["inputs"]["site_type"] == "Type-Ⅱ"
                   and complete["inputs"]["reset_status"] == "없음"))

    two_structures = fill(state("무근 철근 100㎥ 펌프차 타설"))
    checks.append(("F3", "structure" not in two_structures["inputs"] and any(
        question["name"] == "structure" and question.get("reason") for question in two_structures["questions"])))

    two_volumes = fill(state("철근 100㎥ 또는 120㎥"))
    checks.append(("F4", "volume" not in two_volumes["inputs"] and any(
        question["name"] == "volume" and question.get("reason") for question in two_volumes["questions"])))

    no_unit = fill(state("철근 100 펌프차 타설"))
    checks.append(("F5", "volume" not in no_unit["inputs"] and any(
        question["name"] == "volume" and "단위" in question.get("reason", "") for question in no_unit["questions"])))

    inherited = fill(state("15cm, 타입2, 현장 2유형, 붐, 진동기 사용, 재셋팅 없음",
                           inputs={"volume": "260", "structure": "철근"}))
    checks.append(("F6", len(inherited["inputs"]) == 8 and not inherited["questions"]
                   and inherited["input_sources"]["volume"] == "질문"
                   and inherited["input_sources"]["slump_band"] == "답변"))

    provisional = fill(state(COMPLETE, confirmed=False))
    checks.append(("F7", provisional["status"] == "MISSING_INFO"
                   and provisional["questions"][0]["name"] == "work"
                   and provisional["questions"][0]["default"] == "6-1-4"
                   and len(provisional["questions"][0]["choices"]) == 3))

    calculated = adjusted_daily_crew(SPEC, complete["inputs"])
    checks.append(("F8", calculated["status"] == "computed"))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    if not all(passed for _, passed in checks):
        print("F2 inputs:", complete["inputs"], "questions:", [q["name"] for q in complete["questions"]])
        print("F6 inputs:", inherited["inputs"], "questions:", [q["name"] for q in inherited["questions"]])
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
