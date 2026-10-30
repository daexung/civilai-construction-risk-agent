"""단위당 품 표의 행·열 식별과 기준 단위 계산을 검사한다."""

from __future__ import annotations

import copy
import json
from fractions import Fraction
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from backend.agent.tools.calc.per_unit import clean_label, conversion, parse_basis, per_unit  # noqa: E402
from backend.agent.tools.calc.numbers import parse_table_number  # noqa: E402
from evals.check_draft_executability import _values  # noqa: E402


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
                   and "행 후보 2개" in bad["reason"]))
    checks.append(("행 미지정 직종으로 유일한 행", per_unit(sole, {"area": "200"})["status"] == "computed"))
    epoxy = json.loads((ROOT / "data/drafts/specs/공통/6-1-5.json").read_text(encoding="utf-8"))["draft"]
    epoxy_inputs = {"area": "100", "type": "신구-콘크리트 접착제바르기",
                    "ceiling_applied": False, "scaffold_used": False,
                    "floor_level": "지하층 및 1∼3층", "floor_level_19_plus": 19,
                    "thickness_adjusted": False, "thickness": "1"}
    epoxy_result = per_unit(epoxy, epoxy_inputs)
    checks.append(("전치 표 6-1-5 직종 열", epoxy_result["status"] == "computed"
                   and epoxy_result["unit_lines"][0]["applied"] == "0.12"))
    materials = {line["name"]: line for line in epoxy_result["unit_lines"]
                 if line["kind"] == "material"}
    checks.append(("재료량과 단가 미산정", materials["Epoxy신구-콘크리트접착제"]["applied"] == "1.2"
                   and materials["Epoxy신구-콘크리트접착제"]["unit"] == "kg/㎡"
                   and materials["시너"]["applied"] == "0.2"
                   and materials["시너"]["unit"] == "ℓ/㎡"))
    mechanical = json.loads((ROOT / "data/drafts/specs/공통/6-2-5.json").read_text(encoding="utf-8"))["draft"]
    direct = per_unit(mechanical, {"quantity": "1", "rebar_diameter": 35, "work_height": "10m 미만"})
    direct_lines = {line["name"]: line for line in direct.get("unit_lines", [])}
    checks.append(("6-2-5 기본품과 재료", direct["status"] == "computed"
                   and direct_lines["용접공"]["applied"] == "0.06"
                   and direct_lines["아세틸렌"]["applied"] == "133"
                   and direct_lines["산소"]["applied"] == "744"))
    checks.append(("초안 정수 하한", _values(mechanical["inputs"][1]) == ["35"]))
    checks.append(("합성 입력이 정수 상한 안에 머묾",
                   _values({"name": "pump_count_per_location", "type": "nonnegative_integer",
                            "allowed_values": "1 이상 5 이하의 정수"}) == ["1"]))
    checks.append(("표 음수 퍼센트·장비 대수", parse_table_number("- 17%") == Fraction(-17, 100)
                   and parse_table_number("-30%") == Fraction(-3, 10)
                   and parse_table_number("1대(80㎥/hr 이상)") == 1))
    no_unit = copy.deepcopy(finish)
    no_unit["tables"][0]["unit"] = None
    checks.append(("단위 없음 1단위 경고", "단위 표기 없음" in per_unit(no_unit, {"area": "200"})
                   .get("warnings", [""])[0]))
    with_equipment = json.loads((ROOT / "data/drafts/specs/공통/3-4-2.json").read_text(encoding="utf-8"))["draft"]
    equipment_inputs = {field["name"]: (field["allowed_values"][0] if field["type"] == "enum" else "100")
                        for field in with_equipment["inputs"]}
    equipment_result = adjusted_daily_crew(with_equipment, equipment_inputs)
    checks.append(("장비 목록 형식", equipment_result["status"] in ("computed", "blocked")))
    for unit, expected in (("인/100㎡", (100, "㎡")), ("100㎡당", (100, "㎡")),
                           ("㎡당", (1, "㎡")), ("인/개소", (1, "개소")),
                           ("인/ton", (1, "ton")), ("인/t", (1, "t")),
                           ("인/1,000개", (1000, "개")), ("인/10m", (10, "m")),
                           ("인, hr / 1,000㎡", (1000, "㎡"))):
        checks.append((f"단위 해석 {unit}", parse_basis(unit) == expected))
    checks.append(("길이 환산", conversion("km", "m") == 1000))
    checks.append(("질량 환산", conversion("t", "kg") == 1000))
    checks.append(("개수 환산", conversion("1000개", "개") == 1000))
    checks.append(("다른 차원 거부", conversion("㎡", "m") is None))
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
    fireproof = json.loads((ROOT / "data/drafts/specs/건축/1-4-3.json").read_text(encoding="utf-8"))["draft"]
    fireproof_result = per_unit(fireproof, {"area": "100", "thickness": "2",
                                            "is_vermiculite_wet": True})
    fireproof_lines = {line["name"]: line for line in fireproof_result.get("unit_lines", [])}
    checks.append(("원문 1-4-3 복합 단위 분모·수량 대조", fireproof_result["status"] == "computed"
                   and fireproof_lines["도장공"]["exact"] == "31/50000"
                   and fireproof_lines["도장공"]["unit"] == "인/㎡·㎜"
                   and fireproof_lines["그라우팅믹서"]["exact"] == "9/5000"
                   and fireproof_result["provenance"]["quantity"] == {"area": "100", "thickness": "2"}))
    glass = json.loads((ROOT / "data/drafts/specs/건축/10-3-1.json").read_text(encoding="utf-8"))["draft"]
    glass_result = per_unit(glass, {"glass_type": "판유리", "thickness": "3mm이하",
                                    "quantity": "100", "is_special_glass": False})
    glass_lines = {line["name"]: line for line in glass_result.get("unit_lines", [])}
    checks.append(("원문 10-3-1 그룹 열의 직종별 기준값", glass_result["status"] == "computed"
                   and glass_lines["유리공"]["exact"] == "9/125"
                   and glass_lines["보통인부"]["exact"] == "11/1000"
                   and all(line["citations"][0]["value"] in ("0.072", "0.011")
                           for line in glass_result.get("unit_lines", []))))
    pump = json.loads((ROOT / "data/drafts/specs/공통/8-2-27.json").read_text(encoding="utf-8"))["draft"]
    pump["quantity_model"]["params"]["quantity_input"] = ["locations", "operating_days"]
    pump_result = per_unit(pump, {"operation_condition": "작업시배수 상용전원",
                                  "locations": "2", "operating_days": "3",
                                  "pump_count_per_location": "1"})
    checks.append(("원문 인/개소·일 분모와 개소·일 수량 스키마", pump_result["status"] == "computed"
                   and pump_result["unit_lines"][0]["exact"] == "3/25"
                   and pump_result["unit_lines"][0]["source"].startswith("p273-t0")
                   and pump_result["unit_lines"][0]["citations"][0]["value"] == "0.12"
                   and pump_result["provenance"]["quantity"] == {"locations": "2", "operating_days": "3"}))
    glass_out_of_table = per_unit(glass, {"glass_type": "판유리", "thickness": "16mm이하",
                                          "quantity": "100", "is_special_glass": False})
    checks.append(("원문 무기재 유리 조합의 정상 보류", glass_out_of_table["status"] == "blocked"
                   and glass_out_of_table.get("citations", [{}])[0].get("internal_id") == "p688-t2"))
    equipment_only = json.loads((ROOT / "data/drafts/specs/공통/3-6-1.json").read_text(encoding="utf-8"))["draft"]
    equipment_result = adjusted_daily_crew(equipment_only, {"volume": "100",
                                                            "soil_type": "점토, 점질토, 모래, 사질토"})
    checks.append(("원문 3-6-1 장비 전용 일당 산출", equipment_result["status"] == "computed"
                   and equipment_result["work_days"] == "5/53"
                   and equipment_result["equipment_days"]["굴착기"] == "5/53"
                   and equipment_result["unit_lines"][0]["exact"] == "2/265"))
    no_surcharge = json.loads((ROOT / "data/drafts/specs/유지관리/2-4-8.json").read_text(encoding="utf-8"))["draft"]
    no_surcharge_result = adjusted_daily_crew(no_surcharge,
                                               {"volume": "100", "site_condition": "해당 없음"})
    checks.append(("원문 무할증 열을 단위 인자로 조회", no_surcharge_result["status"] == "computed"
                   and no_surcharge_result["daily_volume_m3"] == "9.8"))
    one_surcharge = adjusted_daily_crew(no_surcharge,
        {"volume": "100", "site_condition": "하수도 내부의 준설토가 굳어져 있거나, 준설토 외에 폐기물 등이 존재하는 경우"})
    checks.append(("원문 -15% 시공량 조정", one_surcharge["status"] == "computed"
                   and one_surcharge["daily_volume_m3"] == "8.33"))
    both_surcharges = adjusted_daily_crew(no_surcharge,
        {"volume": "100", "site_condition": "둘 다 해당"})
    checks.append(("복수 감산 결합 미명시 보류", both_surcharges["status"] == "blocked"
                   and "원문에 명시되어 있지 않아" in both_surcharges["reason"]))
    missing_model = copy.deepcopy(json.loads((ROOT / "data/drafts/specs/기계설비/13-5-5.json").read_text(encoding="utf-8"))["draft"])
    # 13-5-5 now has a valid routed model; remove it in the fixture to keep
    # this assertion focused on the runner's missing-model guard.
    missing_model["quantity_model"]["params"].pop("unit_rate_table", None)
    missing_model_result = per_unit(missing_model, {field["name"]: "1" for field in missing_model["inputs"]})
    checks.append(("실행기 미선언 명세는 구조 결함으로 분류", missing_model_result["status"] == "unresolvable"
                   and "unit_rate_table" in missing_model_result["reason"]))
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"통과 {sum(ok for _, ok in checks)} / 전체 {len(checks)}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
