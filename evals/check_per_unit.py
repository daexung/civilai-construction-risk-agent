"""단위당 품 표의 행·열 식별과 기준 단위 계산을 검사한다."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.rules.specs import load_specs  # noqa: E402
from agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from agent.tools.calc.per_unit import clean_label, per_unit  # noqa: E402


def main() -> int:
    specs = {(spec["division"], spec["section_no"]): spec for spec in load_specs().values()}
    mixed = specs[("공통", "6-1-2")]
    finish = specs[("공통", "6-1-3")]
    mixed_inputs = {"mixing_type": "기계비빔타설", "structure": "수량 철근구조물", "volume": "100"}
    checks = []
    result = per_unit(mixed, mixed_inputs)
    checks.append(("합성 행과 머리글 열", result["status"] == "computed"
                   and [(line["name"], line["applied"]) for line in result["unit_lines"]]
                   == [("콘크리트공", "0.17"), ("보통인부", "0.68")]
                   and all(line["citations"][0]["internal_id"] == "p185-t1"
                           for line in result["unit_lines"])))
    surface = per_unit(finish, {"area": "200"})
    checks.append(("문자 그대로 행과 100㎡ 기준", surface["status"] == "computed"
                   and surface["unit_lines"][0]["exact"] == "17/5000"
                   and surface["unit_lines"][0]["applied"] == "0.0034"
                   and surface["unit_basis"]["per"] == "1㎡"))
    checks.append(("선택지 표시 이름", clean_label("수량 철근구조물") == "철근구조물"
                   and clean_label("기계비빔타설 | 구분 콘크리트공") == "기계비빔타설 콘크리트공"))
    missing = copy.deepcopy(mixed)
    missing["tables"][0]["values"] = {"다른 행": {"수량 철근구조물": "0.17"}}
    checks.append(("행 없음", per_unit(missing, mixed_inputs)["status"] == "unresolvable"))
    duplicate = copy.deepcopy(mixed)
    duplicate["tables"][0]["values"]["기계비빔타설 | 작업조 콘크리트공"] = {
        "수량 철근구조물": "0.17"}
    checks.append(("행 중복", per_unit(duplicate, mixed_inputs)["status"] == "unresolvable"))
    bad_unit = copy.deepcopy(finish)
    bad_unit["tables"][0]["unit"] = "품"
    checks.append(("단위 해석 실패", per_unit(bad_unit, {"area": "200"})["status"] == "unresolvable"))
    sole = copy.deepcopy(finish)
    sole["quantity_model"]["params"]["unit_rate_table"].pop("row_input")
    sole["quantity_model"]["params"]["unit_rate_table"].pop("column_input")
    checks.append(("행·열 하나면 지정 없이 계산", per_unit(sole, {"area": "200"})["unit_lines"][0]["applied"]
                   == "0.0034"))
    ambiguous = copy.deepcopy(mixed)
    ambiguous["quantity_model"]["params"]["unit_rate_table"].pop("row_input")
    bad = per_unit(ambiguous, mixed_inputs)
    checks.append(("행 둘 이상이면 지정 없음", bad["status"] == "unresolvable"
                   and "행 지정 없음" in bad["reason"]))
    comma = copy.deepcopy(finish)
    comma["tables"][0]["values"]["미장공"]["수량"] = "２，７００"
    checks.append(("전각·쉼표 숫자", per_unit(comma, {"area": "200"})["unit_lines"][0]["applied"] == "27"))
    threshold = copy.deepcopy(finish)
    threshold["blocked"] = [{"blocked_if": {"input": "area", "op": ">", "value": "100"},
                             "reason": "시험 보류", "source": "시험"}]
    checks.append(("문자열 숫자 보류 비교", per_unit(threshold, {"area": "200"})["status"] == "blocked"))
    threshold["blocked"][0]["blocked_if"]["value"] = "숫자 아님"
    checks.append(("숫자 아닌 보류 값은 미해결", per_unit(threshold, {"area": "200"})["status"]
                   == "unresolvable"))
    crew_spec = copy.deepcopy(specs[("공통", "6-1-1")])
    crew_spec["quantity_model"]["params"]["base_output"].pop("row_input")
    checks.append(("일당 작업조 기준 행 복수 거부", adjusted_daily_crew(crew_spec, {
        "placement_method": "인력운반 타설", "structure": "철근구조물", "volume": "100",
        "scattered_small_volume": False, "concrete_supply": "관급"})["status"] == "unresolvable"))
    crew_spec = copy.deepcopy(specs[("공통", "6-1-1")])
    for row in crew_spec["tables"][0]["values"].values():
        row.pop("장비사용 타설")
    crew_spec["quantity_model"]["params"]["crew"].pop("column_input")
    checks.append(("일당 작업조 직종 열 하나 선택", adjusted_daily_crew(crew_spec, {
        "placement_method": "인력운반 타설", "structure": "철근구조물", "volume": "100",
        "scattered_small_volume": False, "concrete_supply": "관급"})["status"] == "computed"))
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"통과 {sum(ok for _, ok in checks)} / 전체 {len(checks)}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
