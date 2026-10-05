"""4504 원문 추출과 펌프차 구성 금액을 손계산으로 검사한다."""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from fastapi.testclient import TestClient

os.environ["AGENT_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.nodes.fill import extract_inputs, fill  # noqa: E402
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_equipment_version, select_rate_version  # noqa: E402
from pipeline.equipment_rates import build  # noqa: E402
from backend.api.main import app  # noqa: E402


def main() -> int:
    checks = []
    data = build()
    saved = json.loads((ROOT / "data/rates/equipment_rates.json").read_text(encoding="utf-8"))
    machines = data["machines"]
    checks.append(("E1 PDF 재추출", data == saved and len(machines) == 8))
    checks.append(("E2 32m", tuple(machines["4504-0032"][key] for key in (
        "price_thousand_won", "hourly_depreciation", "fuel_l_per_hr",
        "misc_pct_of_fuel", "operator_per_day")) == (275000, 72600, "17.3", 35, 1)))
    checks.append(("E3 52m", tuple(machines["4504-0052"][key] for key in (
        "price_thousand_won", "hourly_depreciation", "fuel_l_per_hr")) == (519667, 137192, "31.0")))
    checks.append(("E4 손료계수 8개", all(
        (Decimal(entry["price_thousand_won"]) * 1000 * Decimal(2640) / Decimal(10_000_000))
        .to_integral_value(rounding=ROUND_DOWN) == entry["hourly_depreciation"]
        for entry in machines.values())))
    spec = json.loads((ROOT / "backend/agent/rules/specs/common/6-1-4_pump.json").read_text(encoding="utf-8"))
    cases = json.loads((ROOT / "evals/cases/common_6-1-4_pump.json").read_text(encoding="utf-8"))["cases"]
    version = select_rate_version("2026-10-01")
    a = cases[0]["input"] | {"pump_size": "32m"}
    units_a = adjusted_daily_crew(spec, a)["unit_lines"]
    priced_a = price_unit(spec, units_a, version, a, "2026-10-01")
    a_rows = {row["name"]: row for row in priced_a["equipment_lines"]}
    checks.append(("E5 사례 A 손료", a_rows["펌프차 기계손료"]["amount_exact"] == "4464.9"
                   and a_rows["펌프차 기계손료"]["amount"] == "4464.9"))
    checks.append(("E6 사례 A 운전원", a_rows["펌프차 운전원"]["unit_price"] == "35415.375"
                   and a_rows["펌프차 운전원"]["amount_exact"] == "2178.0455625"
                   and a_rows["펌프차 운전원"]["amount"] == "2178.0"))
    checks.append(("E7 연료 미산정", a_rows["펌프차 연료·잡재료비"]["amount"] is None
                   and a_rows["펌프차 연료·잡재료비"]["fuel_l_per_unit"] == "1.06395"
                   and priced_a["partial"]))
    checks.append(("E8 5% 기준은 작업조 노무비", all(
        Decimal(cost["amount_exact"]) == Decimal(priced_a["labor_subtotal"]) * Decimal("0.05")
        for cost in priced_a["cost_lines"])))
    d = cases[3]["input"] | {"pump_size": "52m"}
    priced_d = price_unit(spec, adjusted_daily_crew(spec, d)["unit_lines"], version, d, "2026-10-01")
    d_rows = {row["name"]: row for row in priced_d["equipment_lines"]}
    checks.append(("E9 사례 D 52m 손료", d_rows["펌프차 기계손료"]["amount_exact"] == "12210.088"
                   and d_rows["펌프차 기계손료"]["amount"] == "12210.0"))
    checks.append(("E10 사례 D 운전원", d_rows["펌프차 운전원"]["amount_exact"] == "3151.968375"
                   and d_rows["펌프차 운전원"]["amount"] == "3151.9"))
    checks.append(("E11 28m 제외", "pump_size" not in extract_inputs("28m 펌프차", spec)[0]
                   and "80㎥/hr" in extract_inputs("28m 펌프차", spec)[1]["pump_size"]
                   and "pump_size" in extract_inputs("32미터 펌프차", spec)[0]))
    state = {"spec_id": spec["id"], "query": "철근콘크리트 260㎥ 펌프차 타설",
             "selection": {"confirmed": True}, "inputs": {}, "input_sources": {}, "reply": ""}
    questions = fill(state)["questions"]
    checks.append(("E12 규격 누락 되묻기", any(question["name"] == "pump_size" for question in questions)))
    checks.append(("E13 근거", all(row["citations"] for row in priced_a["equipment_lines"])
                   and any(citation["section_no"] == "8-1-6" for citation in a_rows["펌프차 운전원"]["citations"])
                   and any(citation["section_no"] == "1-2-2" for citation in a_rows["펌프차 기계손료"]["citations"])))
    client = TestClient(app)
    start = client.post("/api/chat", json={"message": "철근콘크리트 벽체 260㎥ 32m 펌프차로 타설 비용",
                                            "basis_date": "2026-10-01"}).json()
    computed = client.post("/api/chat", json={"thread_id": start["thread_id"], "answers": {
        "slump_band": "15㎝", "facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ",
        "placement": "붐", "vibrator_used": True, "reset_status": "없음", "concrete_supply": "관급",
        "work_category": "기타 토목공사", "duration": "1~6개월", "contractor_type": "종합건설업",
        "project_scale": "이 견적만",
    }}).json()
    checks.append(("E14 API 구성 금액", computed["status"] == "PARTIAL"
                   and [row["amount"] for row in computed["priced"]["equipment_lines"]]
                   == ["4464.9", "2178.0", None]
                   and computed["priced"]["equipment_rate_version"]["version"] == "2026"
                   and computed["priced"]["equipment_rate_version"]["published"] == "2026-01-08"))
    rejected = fill({**state, "query": "철근콘크리트 260㎥ 28m 펌프차 타설"})
    checks.append(("E15 28m 거부 안내", any(question["name"] == "pump_size"
                   and "80㎥/hr" in question.get("reason", "") for question in rejected["questions"])))
    checks.append(("E16 2025년 자료 없음", select_equipment_version("2025-12-01") is None))
    old = price_unit(spec, units_a, None, a, "2025-12-01")
    checks.append(("E17 2025년 장비 미산정", old["equipment_rate_version"] is None
                   and old["total"] is None
                   and all(row["amount"] is None for row in old["equipment_lines"])
                   and all(row["reason"] == "기준일에 적용 가능한 건설기계 경비산출표 없음"
                           for row in old["equipment_lines"][:2])))
    checks.append(("E18 2026년 적용·2027년 자료 없음",
                   select_equipment_version("2026-10-01")["version"] == "2026"
                   and select_equipment_version("2027-01-01") is None
                   and all(row["amount"] is None for row in
                           price_unit(spec, units_a, None, a, "2027-01-01")["equipment_lines"])))
    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
