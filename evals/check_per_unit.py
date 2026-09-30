"""단위당 품 표의 행·열 식별과 기준 단위 계산을 검사한다."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.rules.specs import load_specs  # noqa: E402
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
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"통과 {sum(ok for _, ok in checks)} / 전체 {len(checks)}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
