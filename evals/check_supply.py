"""레미콘 관급/사급 처리(제외 vs 미산정)를 오프라인으로 검사한다."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ["AGENT_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.nodes.fill import extract_inputs, fill  # noqa: E402
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_rate_version  # noqa: E402


def main() -> int:
    checks = []
    spec = json.loads((ROOT / "backend/agent/rules/specs/common/6-1-4_pump.json").read_text(encoding="utf-8"))
    base_input = {
        "pump_size": "32m", "volume": "260", "structure": "철근", "slump_band": "15㎝",
        "facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ", "placement": "붐",
        "vibrator_used": True, "reset_status": "없음",
    }
    version = select_rate_version("2026-10-01")

    public = {**base_input, "concrete_supply": "관급"}
    units_public = adjusted_daily_crew(spec, public)["unit_lines"]
    priced_public = price_unit(spec, units_public, version, public, "2026-10-01")
    supply_public = {line["name"]: line for line in priced_public["supply_lines"]}
    checks.append(("S1 관급 제외", supply_public["레미콘(콘크리트) 재료비"]["status"] == "제외"
                   and supply_public["레미콘(콘크리트) 재료비"]["reason"]
                   == "관급자재(발주처 지급) — 시공사 일위대가에서 제외"
                   and not any("레미콘" in item["name"] for item in priced_public["unpriced"])
                   and any("레미콘" in item["name"] for item in priced_public["excluded"])))
    checks.append(("S2 관급 partial은 연료 미산정 때문에 유지", priced_public["partial"]
                   and any("연료" in item["name"] for item in priced_public["unpriced"])))

    private = {**base_input, "concrete_supply": "사급", "ready_mix_price": "모름"}
    units_private = adjusted_daily_crew(spec, private)["unit_lines"]
    priced_private = price_unit(spec, units_private, version, private, "2026-10-01")
    supply_private = {line["name"]: line for line in priced_private["supply_lines"]}
    checks.append(("S3 사급 단가 모름은 미산정", supply_private["레미콘(콘크리트) 재료비"]["status"] == "미산정"
                   and supply_private["레미콘(콘크리트) 재료비"]["reason"] == "사급 레미콘 단가 미입력"
                   and any("레미콘" in item["name"] for item in priced_private["unpriced"])
                   and not any("레미콘" in item["name"] for item in priced_private["excluded"])))

    checks.append(("S4 관급·사급 계는 이전과 같음(레미콘 제외)",
                   priced_public["total"] == priced_private["total"]
                   and priced_public["total_exact"] == priced_private["total_exact"]))

    state = {"spec_id": spec["id"],
             "query": "철근콘크리트 260㎥ 펌프차 32m 붐타설 슬럼프 15cm 시설유형 Type-Ⅱ 현장조건 Type-Ⅱ 진동기 사용 재셋팅 없음",
             "selection": {"confirmed": True}, "inputs": {}, "input_sources": {}, "reply": ""}
    questions = fill(state)["questions"]
    checks.append(("S5 입력 없음 되묻기", any(question["name"] == "concrete_supply" for question in questions)))

    values, _ = extract_inputs("레미콘 관급자재로 진행", spec)
    checks.append(("S6 관급자재 동의어", values.get("concrete_supply") == "관급"))
    values2, _ = extract_inputs("레미콘은 발주처 지급입니다", spec)
    checks.append(("S7 발주처 지급 동의어", values2.get("concrete_supply") == "관급"))
    values3, _ = extract_inputs("레미콘 사급자재로 구매", spec)
    checks.append(("S8 사급자재 동의어", values3.get("concrete_supply") == "사급"))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
