"""독립 손계산 사례를 명세 기반 계산 방식 함수와 대조한다."""

from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402


CALCULATORS = {"adjusted_daily_crew": adjusted_daily_crew}


def load_specs() -> dict[str, dict]:
    specs = {}
    for path in (ROOT / "agent/rules/specs").rglob("*.json"):
        spec = json.loads(path.read_text(encoding="utf-8"))
        if spec["id"] in specs:
            raise ValueError(f"중복 명세 id: {spec['id']}")
        specs[spec["id"]] = spec
    return specs


def differences(case: dict, result: dict, spec: dict) -> list[str]:
    expected = case["expected"]
    issues = []
    if result.get("status") != expected["status"]:
        return [f"status: 예상 {expected['status']}, 실제 {result.get('status')}"]
    status = expected["status"]
    if status == "computed":
        for key in ("daily_volume_m3", "work_days"):
            if Fraction(result[key]) != Fraction(expected[key]):
                issues.append(f"{key}: 예상 {expected[key]}, 실제 {result[key]}")
        if set(result["person_days"]) != set(expected["person_days"]):
            issues.append("직종 목록 불일치")
        for trade, number in expected["person_days"].items():
            if trade not in result["person_days"] or Fraction(result["person_days"][trade]) != Fraction(number):
                issues.append(f"{trade}: 예상 {number}, 실제 {result['person_days'].get(trade)}")
        equipment_name = spec["quantity_model"]["params"]["equipment"]["name"]
        expected_equipment = expected.get("equipment_days", {equipment_name: expected.get("pump_truck_days")})
        if set(result["equipment_days"]) != set(expected_equipment):
            issues.append("장비 목록 불일치")
        for name, number in expected_equipment.items():
            actual = result["equipment_days"].get(name)
            if actual is None or Fraction(actual) != Fraction(number):
                issues.append(f"{name}: 예상 {number}, 실제 {actual}")
        if result.get("not_calculated") != spec["not_calculated"]:
            issues.append("not_calculated 누락 또는 변경")
        provenance = result.get("provenance", {})
        if not all(key in provenance for key in ("daily_volume_m3", "work_days", "person_days", "equipment_days")):
            issues.append("숫자 출처 누락")
        else:
            daily_source = provenance["daily_volume_m3"]
            if not daily_source.get("base_output") or len(daily_source.get("coefficients", [])) != len(spec["quantity_model"]["params"]["coefficients"]):
                issues.append("일당시공량의 표·계수 출처 누락")
            if not provenance["work_days"].get("quantity_source"):
                issues.append("작업일수의 물량 출처 누락")
            if set(provenance["person_days"]) != set(result["person_days"]):
                issues.append("직종별 출처 누락")
            if set(provenance["equipment_days"]) != set(result["equipment_days"]):
                issues.append("장비별 출처 누락")
    elif status == "ask":
        if result.get("missing") != expected["missing"]:
            issues.append(f"missing: 예상 {expected['missing']}, 실제 {result.get('missing')}")
        questions = {question["name"]: question for question in result.get("questions", [])}
        if set(questions) != set(expected["missing"]):
            issues.append("질문 목록 불일치")
        if len(expected["missing"]) == 1:
            question = questions.get(expected["missing"][0], {})
            if question.get("ask") != expected.get("question"):
                issues.append("되묻기 문장 불일치")
            if "decision_table" in expected:
                table = question.get("decision_table", {})
                if table.get("id") != expected["decision_table"] or not table.get("values"):
                    issues.append("판정표 근거 누락")
    else:
        if not result.get("reason"):
            issues.append("거부·보류 사유 누락")
        if status == "blocked" and not result.get("source"):
            issues.append("보류 출처 누락")
        for field in spec["inputs"]:
            name = field["name"]
            if expected.get("reason", "").startswith(name) and result.get("input") != name:
                issues.append(f"사유 입력 이름: 예상 {name}, 실제 {result.get('input')}")
    return issues


def main() -> int:
    specs = load_specs()
    passed = total = 0
    files = sorted((ROOT / "evals/cases").glob("*.json"))
    if not files:
        print("사례 파일이 없습니다.")
        return 1
    for path in files:
        suite = json.loads(path.read_text(encoding="utf-8"))
        spec = specs[suite["spec_id"]]
        calculate = CALCULATORS[spec["quantity_model"]["name"]]
        for case in suite["cases"]:
            total += 1
            result = calculate(spec, case["input"])
            issues = differences(case, result, spec)
            if issues:
                print(f"FAIL {path.name} {case['id']}: {'; '.join(issues)}")
            else:
                passed += 1
                print(f"PASS {path.name} {case['id']}")
    print(f"통과 {passed} / 전체 {total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
