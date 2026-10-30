"""price·equipment 경로의 외부 의존 없는 집중 검사(라이브 모델·pdfplumber·HTTP 서버 불필요).

1) 기존 장비(펌프차) 경비 계산 E2~E13·E16~E18: 저장된 경비산출표 JSON으로 확인(PDF 재추출 E1과 API E14는 제외).
2) 이번에 바뀐 경로: 조건부 공구손료(cost_rules.when), 총량 줄의 분수 값, 조회 줄 제외, 물량 입력이 없는 명세의 기준 1,
   장비의 omit_if_zero·본문 장비 대수(count)·같은 이름 누적·additional_work 장비와 그 근거(provenance).
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.nodes.fill import extract_inputs  # noqa: E402
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from backend.agent.tools.calc.price import price_unit, select_equipment_version, select_rate_version  # noqa: E402


def package(key: str) -> dict:
    division, section = key.split("/")
    return json.loads((ROOT / f"data/drafts/specs/{division}/{section}.json").read_text(encoding="utf-8"))["draft"]


def main() -> int:
    checks = []
    saved = json.loads((ROOT / "data/rates/equipment_rates.json").read_text(encoding="utf-8"))
    machines = saved["machines"]
    checks.append(("E2 32m", tuple(machines["4504-0032"][k] for k in (
        "price_thousand_won", "hourly_depreciation", "fuel_l_per_hr", "misc_pct_of_fuel", "operator_per_day"))
        == (275000, 72600, "17.3", 35, 1)))
    checks.append(("E4 손료계수 8개", len(machines) == 8 and all(
        (Decimal(e["price_thousand_won"]) * 1000 * Decimal(2640) / Decimal(10_000_000))
        .to_integral_value(rounding=ROUND_DOWN) == e["hourly_depreciation"] for e in machines.values())))
    spec = json.loads((ROOT / "backend/agent/rules/specs/common/6-1-4_pump.json").read_text(encoding="utf-8"))
    cases = json.loads((ROOT / "evals/cases/common_6-1-4_pump.json").read_text(encoding="utf-8"))["cases"]
    version = select_rate_version("2026-10-01")
    a = cases[0]["input"] | {"pump_size": "32m"}
    units_a = adjusted_daily_crew(spec, a)["unit_lines"]
    priced_a = price_unit(spec, units_a, version, a, "2026-10-01")
    rows = {row["name"]: row for row in priced_a["equipment_lines"]}
    checks.append(("E5 사례 A 손료", rows["펌프차 기계손료"]["amount_exact"] == "4464.9"))
    checks.append(("E6 사례 A 운전원", rows["펌프차 운전원"]["amount_exact"] == "2178.0455625"
                   and rows["펌프차 운전원"]["amount"] == "2178.0"))
    checks.append(("E7 연료 미산정", rows["펌프차 연료·잡재료비"]["amount"] is None and priced_a["partial"]))
    checks.append(("E8 5% 기준은 작업조 노무비", all(
        Decimal(c["amount_exact"]) == Decimal(priced_a["labor_subtotal"]) * Decimal("0.05")
        for c in priced_a["cost_lines"])))
    d = cases[3]["input"] | {"pump_size": "52m"}
    priced_d = price_unit(spec, adjusted_daily_crew(spec, d)["unit_lines"], version, d, "2026-10-01")
    d_rows = {row["name"]: row for row in priced_d["equipment_lines"]}
    checks.append(("E9 사례 D 52m", d_rows["펌프차 기계손료"]["amount_exact"] == "12210.088"
                   and d_rows["펌프차 운전원"]["amount"] == "3151.9"))
    checks.append(("E11 28m 제외", "pump_size" not in extract_inputs("28m 펌프차", spec)[0]))
    checks.append(("E13 근거", all(row["citations"] for row in priced_a["equipment_lines"])))
    checks.append(("E16~18 기준일 밖 장비 미산정", select_equipment_version("2025-12-01") is None
                   and select_equipment_version("2027-01-01") is None
                   and all(r["amount"] is None
                           for r in price_unit(spec, units_a, None, a, "2027-01-01")["equipment_lines"])))

    # --- 조건부 공구손료 ---
    block = package("유지관리/2-1-30")
    rates = select_rate_version("2026-06-01")
    for precision, rate in ((True, "0.05"), (False, "0.02")):
        inputs = {"volume": "300", "type": "B-Type", "tactile_block": False, "precision_cut": precision}
        priced = price_unit(block, adjusted_daily_crew(block, inputs)["unit_lines"], rates, inputs)
        want = (Decimal(priced["labor_subtotal"]) * Decimal(rate)).quantize(Decimal("0.1"), rounding=ROUND_DOWN)
        checks.append((f"C1 정밀절단={precision} 공구손료 {rate} 하나만",
                       len(priced["cost_lines"]) == 1 and Decimal(priced["cost_lines"][0]["amount"]) == want))
    pipe = package("토목/6-2-2")
    for size, rate in (("300", "0.04"), ("600", "0.03"), ("700", "0.02")):
        inputs = {"installation_method": "장비", "pipe_diameter": size, "quantity": "9",
                  "use_anti_separation_ring": False}
        priced = price_unit(pipe, adjusted_daily_crew(pipe, inputs)["unit_lines"], rates, inputs)
        checks.append((f"C2 관경 {size} 공구손료 {rate}",
                       len(priced["cost_lines"]) == 1 and priced["cost_lines"][0]["rate"] == rate))

    # --- 총량 줄(분수)·조회 줄·물량 기준 ---
    lines = [{"kind": "labor", "name": "특별인부", "exact": "1/3", "applied": "1/3", "unit": "인·일",
              "formula": "x", "source": "s", "citations": []},
             {"kind": "lookup", "name": "손율", "exact": "4%", "applied": "4%", "unit": "%",
              "source": "s", "citations": []}]
    total_spec = {"quantity_model": {"params": {}}, "cost_rules": [], "inputs": [], "not_calculated": [],
                  "supply_rules": []}
    totals = price_unit(total_spec, lines, rates, {})
    wage = Decimal(next(r for r in rates["rates"].values() if r["name"] == "특별인부")["daily"])
    checks.append(("T1 분수 총량 줄 금액", abs(Decimal(totals["lines"][0]["amount_exact"])
                                              - Decimal(1) / Decimal(3) * wage) < Decimal("0.000001")))
    checks.append(("T2 조회 줄은 금액에서 빠지고 사유가 남음", len(totals["lines"]) == 1 and any(
        item["name"] == "손율" and "조회" in item["reason"] for item in totals["unpriced"])))
    checks.append(("T3 물량 입력이 없으면 기준 1", totals["reference_amounts"]["volume"] == "1"))

    # --- 장비: omit_if_zero · 본문 장비 대수 · 같은 이름 누적 · additional_work 장비 ---
    tree = package("공통/4-3-3")
    r = adjusted_daily_crew(tree, {"method": "인력시공", "diameter": "8~9(7~8)", "quantity": "30",
                                    "has_root_ball": True, "is_wild": False})
    checks.append(("Q1 omit_if_zero: 작업조에 없는 장비는 결과에 없음",
                   r["equipment_days"] == {} and not any(l["kind"] == "equipment" for l in r["unit_lines"])))
    asphalt = package("유지관리/2-1-6")
    r = adjusted_daily_crew(asphalt, {"work_type": "덧씌우기 포장", "pavement_type": "개질아스팔트", "quantity": "3600"})
    checks.append(("Q2 본문 장비 대수(+1)·같은 이름 누적", r["equipment_days"]["머캐덤롤러 10∼12t"] == "4"
                   and "타이어롤러 8∼15t" not in r["equipment_days"]))
    macadam = [l for l in r["unit_lines"] if l["name"] == "머캐덤롤러 10∼12t"]
    checks.append(("Q3 누적 장비 줄마다 근거", len(macadam) == 2 and all(l["citations"] for l in macadam)))
    net = package("토목/1-9-4")
    r = adjusted_daily_crew(net, {"volume": "800", "installation_method": "기계식", "net_type": "포켓식",
                                   "foundation_drilling": True})
    checks.append(("Q4 additional_work 장비·직종 근거", r["equipment_days"]["공기압축기"] == "1"
                   and "소형브레이커" in r["provenance"]["equipment_days"] and "착암공" in r["provenance"]["person_days"]))
    eq_priced = price_unit(net, r["unit_lines"], rates, {"volume": "800"})
    checks.append(("Q5 단가표 없는 장비는 미산정 사유",
                   any("기계경비 단가 자료 없음" in u["reason"] for u in eq_priced["unpriced"])))
    checks.append(("Q6 장비 줄 단위는 hr/물량단위",
                   all(l["unit"].startswith("hr/") for l in r["unit_lines"] if l["kind"] == "equipment")))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
