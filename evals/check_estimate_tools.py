"""서버 도구(backend/agent/estimate/tools.py)와 품/가격 조건 분리를 오프라인으로 검사한다.

검색 후보는 운영에서 나온 순서(6-1-4, 6-1-1, 1-6-2)로 고정한다. 실제 검색을 포함한 대화 검사는 PR 2에서 따로 한다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("AGENT_OFFLINE", "1")
os.environ.setdefault("AGENT_LLM", "off")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.estimate import tools  # noqa: E402
from backend.agent.nodes.compute import CALCULATORS  # noqa: E402
from backend.agent.rules.conditions import price_fields  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402

HITS = [{"section_no": "6-1-4", "division": "공통", "rank": 1, "section": "6-1-4 콘크리트 펌프차 타설"},
        {"section_no": "6-1-1", "division": "공통", "rank": 2, "section": "6-1-1 레디믹스트콘크리트 타설"},
        {"section_no": "1-6-2", "division": "토목", "rank": 3, "section": "1-6-2 표층 인력포설"}]
PUMP = {"pump_size": "32m", "structure": "철근", "slump_band": "15㎝", "facility_type": "Type-Ⅱ",
        "site_type": "Type-Ⅱ", "placement": "붐", "vibrator_used": True, "reset_status": "없음"}
# check_api A4와 같은 입력·기준일의 원가계산서 합계(기존 그래프 결과).
A4_TOTALS = {"materials": 178360, "labor": 4922974, "expenses": 2263523, "net_cost": 7364857,
             "management": 589188, "profit": 1166352, "total_cost": 9120397, "vat": 912039,
             "contract_amount": 10032436}


def spec_of(section_no: str) -> dict:
    return next(spec for spec in load_specs().values() if spec["section_no"] == section_no and spec["division"] == "공통")


def answer(session, **values):
    return tools.set_conditions(session, "", values={name: {"value": value} for name, value in values.items()},
                                source="answer")


def fields_of(result) -> list[str]:
    return [question["field"] for question in result["missing"]]


def sample_inputs(spec: dict) -> dict:
    """각 입력의 첫 허용값(수치는 1)으로 만든 입력. when 조건은 맞을 때만 넣는다."""
    values = {}
    for field in spec["inputs"]:
        allowed = field.get("allowed_values")
        values[field["name"]] = allowed[0] if isinstance(allowed, list) else "1"
    return {name: value for name, value in values.items()
            if not (when := next(f for f in spec["inputs"] if f["name"] == name).get("when"))
            or values.get(when["input"]) == when["equals"]}


def started(text: str):
    session = tools.new_estimate(text, "2026-10-01")
    tools.find_work(session, hits=HITS)
    return session


def guarded(checks: list, name: str, check) -> None:
    """한 검사의 예외가 나머지 검사를 막지 않게 하고, 예외는 실패로 기록한다."""
    try:
        passed = bool(check())
    except Exception as exc:  # noqa: BLE001 - 회귀 재현(KeyError 등)을 실패로 남긴다
        print(f"  {name}: {type(exc).__name__}: {exc}")
        passed = False
    checks.append((name, passed))


def check_per_unit_basis() -> bool:
    door = [{"section_no": "10-1-7", "division": "건축", "rank": 1, "section": "10-1-7 자동문 설치"}]
    session = tools.new_estimate("자동문 3개소 설치", "2026-10-01")
    found = tools.find_work(session, hits=door)
    labor = tools.compute_labor(session)
    basis = tools.explain_basis(session)
    return (found["status"] == "ok" and load_specs()[found["data"]["spec_id"]]["quantity_model"]["name"] == "per_unit"
            and labor["status"] == "ok" and labor["data"]["quantity"] == "3"
            and basis["status"] == "ok" and len(basis["data"]["citations"]) > 0)


def check_evidence_values() -> bool:
    session = started("콘크리트 1m3 품셈")
    tools.set_conditions(session, "", work="6-1-4", source="answer")
    item = session["items"][session["item_order"][0]]
    say = lambda text, **kwargs: tools.set_conditions(session, text, **kwargs)  # noqa: E731
    wrong_number = say("1m3", quantity={"value": "999", "unit": "m3", "evidence": "1m3"})
    kept = item["quantity"] is None
    unit_alias = say("1m3", quantity={"value": "1", "unit": "㎥", "evidence": "1m3"})
    rube = say("2루베로 바꿔", quantity={"value": "2", "unit": "m3", "evidence": "2루베"})
    wrong_unit = say("2㎡", quantity={"value": "2", "unit": "m3", "evidence": "2㎡"})
    volume_field = say("1m3", values={"volume": {"value": "5", "evidence": "1m3"}})
    pump_wrong = say("펌프차 32m", values={"pump_size": {"value": "36m", "evidence": "32m"}})
    pump_right = say("펌프차 32m", values={"pump_size": {"value": "32m", "evidence": "32m"}})
    structure_wrong = say("철근콘크리트", values={"structure": {"value": "무근", "evidence": "철근콘크리트"}})
    structure_right = say("철근콘크리트", values={"structure": {"value": "철근", "evidence": "철근콘크리트"}})
    price_right = say("레미콘 단가 9만원", values={"ready_mix_price": {"value": "90000", "evidence": "9만원"}})
    price_wrong = say("레미콘 단가 9만원", values={"ready_mix_price": {"value": "80000", "evidence": "9만원"}})
    duration_right = say("공사기간 8개월", values={"duration": {"value": "7~12개월", "evidence": "8개월"}})
    duration_wrong = say("공사기간 8개월", values={"duration": {"value": "13~36개월", "evidence": "8개월"}})
    return ("quantity" in wrong_number["rejected"] and kept
            and unit_alias["data"]["applied"] == {"quantity": "1"} and rube["data"]["applied"] == {"quantity": "2"}
            and "quantity" in wrong_unit["rejected"] and "volume" in volume_field["rejected"]
            and "pump_size" in pump_wrong["rejected"] and pump_right["data"]["applied"] == {"pump_size": "32m"}
            and "structure" in structure_wrong["rejected"] and structure_right["data"]["applied"] == {"structure": "철근"}
            and price_right["data"]["applied"] == {"ready_mix_price": "90000"} and "ready_mix_price" in price_wrong["rejected"]
            and duration_right["data"]["applied"] == {"duration": "7~12개월"} and "duration" in duration_wrong["rejected"]
            and item["quantity"]["value"] == "2")


def stale_checks():
    """각 변경 직후에는 이전 원가계산서가 최신이 아니고, 재계산 후에는 필요한 단계만 다시 한다."""
    session = started("철근콘크리트 벽체 260㎥ 펌프차로 타설 비용")
    tools.set_conditions(session, "", work="6-1-4", source="answer")
    answer(session, **PUMP, concrete_supply="관급")
    tools.estimate_cost(session)
    item = session["items"][session["item_order"][0]]
    original_labor, original_price = CALCULATORS["adjusted_daily_crew"], tools.price_unit
    counts = {"labor": 0, "price": 0}

    def labor(*args, **kwargs):
        counts["labor"] += 1
        return original_labor(*args, **kwargs)

    def price(*args, **kwargs):
        counts["price"] += 1
        return original_price(*args, **kwargs)

    def change_then_recalculate(change, labor_runs: int, price_runs: int, after=lambda result: True):
        def check():
            before_amount = tools.current_estimate(session)
            change()
            stale = tools.current_estimate(session) is None
            counts.update(labor=0, price=0)
            with patch.dict(CALCULATORS, {"adjusted_daily_crew": labor}), patch.object(tools, "price_unit", price):
                result = tools.estimate_cost(session)
            fresh = tools.current_estimate(session)
            if not stale or before_amount is None:
                print(f"    재계산 전 판정: 이전 결과 있음={before_amount is not None}, 무효화={stale}")
            return (stale and result["status"] == "ok" and fresh is not None
                    and fresh["statement"] is session["statement"]
                    and counts == {"labor": labor_runs, "price": price_runs} and after(result))
        return check

    from backend.agent.estimate.state import set_common  # 도구를 거치지 않은 변경도 판정해야 한다
    return [
        ("C13 처음 계산 직후 원가계산서는 최신", lambda: tools.current_estimate(session) is not None),
        ("C13 공통 조건 변경: 재계산 전 무효, 후 품·가격 재사용하고 원가만 갱신",
         change_then_recalculate(lambda: answer(session, duration="7~12개월"), 0, 0,
                                 lambda r: r["data"]["statement"]["conditions"]["duration"] == "7~12개월")),
        ("C13 도구 밖 공통 조건 변경도 무효로 판정",
         change_then_recalculate(lambda: set_common(session, "contractor_type", "전문건설업"), 0, 0)),
        ("C13 가격 조건 변경: 재계산 전 무효, 후 가격만 다시",
         change_then_recalculate(lambda: answer(session, concrete_supply="사급", ready_mix_price="90000"), 0, 1)),
        ("C13 물량 변경: 재계산 전 무효, 후 품·가격 다시",
         change_then_recalculate(lambda: tools.set_conditions(
             session, "300㎥", quantity={"value": "300", "unit": "㎥", "evidence": "300㎥"}), 1, 1,
             lambda r: r["data"]["quantity"] == "300")),
        ("C13 품 조건 변경: 재계산 전 무효, 후 품·가격 다시",
         change_then_recalculate(lambda: answer(session, slump_band="18㎝이상"), 1, 1)),
        ("C13 기준일 변경: 재계산 전 무효, 후 가격만 다시",
         change_then_recalculate(lambda: session.update(basis_date="2026-12-01"), 0, 1,
                                 lambda r: item["result_revision"] == item["input_revision"])),
    ]


def main() -> int:
    checks = []
    pump, manual = spec_of("6-1-4"), spec_of("6-1-1")

    # 1. 조건 분류
    checks.append(("C1 6-1-4 가격 조건", price_fields(pump) == {"concrete_supply", "ready_mix_price"}))
    checks.append(("C1 6-1-1 가격 조건", price_fields(manual) == {"concrete_supply"}))
    checks.append(("C1 품 계산에 이름이 나오면 품 조건(딸린 입력 포함)",
                   price_fields({**pump, "quantity_model": {**pump["quantity_model"], "x": ["concrete_supply"]}}) == set()))
    blocked = {**pump, "blocked": [*pump["blocked"], {"blocked_if": {"input": "ready_mix_price", "op": ">", "value": "0"}}]}
    # 레미콘 단가가 품 조건이 되면, 그 필요 여부를 정하는 관급/사급도 품 조건으로 남는다.
    checks.append(("C1 보류 조건에 쓰이면 품 조건(그 입력을 정하는 조건 포함)", price_fields(blocked) == set()))
    probe = subprocess.run([sys.executable, "-c", "import sys; import backend.agent.rules.conditions; "
                            "print(any(m.startswith(('backend.agent.rules.specs', 'backend.agent.tools')) for m in sys.modules))"],
                           cwd=ROOT, capture_output=True, text=True)
    checks.append(("C1 분류 모듈은 명세·계산기를 가져오지 않음", probe.stdout.strip() == "False"))

    # 2. 계산기 기본 검증 유지, 품 산출 모드에서만 가격 조건 제외 (가격 조건이 있는 모든 명세)
    default_ok, labor_ok, priced_specs = True, True, 0
    for spec in load_specs().values():
        excluded = price_fields(spec)
        if not excluded:
            continue
        priced_specs += 1
        calculate = CALCULATORS[spec["quantity_model"]["name"]]
        inputs = {name: value for name, value in sample_inputs(spec).items() if name not in excluded}
        default = calculate(spec, inputs)
        labor = calculate(spec, inputs, labor_only=True)
        default_ok &= default.get("status") == "ask" and bool(set(default.get("missing", [])) & excluded)
        labor_ok &= labor.get("status") != "ask" or not set(labor.get("missing", [])) & excluded
    checks.append((f"C2 기본 모드는 가격 조건 누락을 계속 물음({priced_specs}개 명세)", priced_specs >= 2 and default_ok))
    checks.append(("C2 품 산출 모드는 가격 조건 없이 진행", labor_ok))

    # 3. 대화 흐름: 공종만 → 품 조건만 → 품 → 물량 변경 → 가격 조건 → 원가
    session = tools.new_estimate("콘크리트 1㎥ 품셈 알려줘", "2026-10-01")
    first = tools.find_work(session, hits=HITS)
    checks.append(("C3 공종 미확정이면 공종만", first["status"] == "needs_input" and fields_of(first) == ["work"]
                   and tools.compute_labor(session)["missing"][0]["field"] == "work"))
    tools.set_conditions(session, "", work="6-1-4", source="answer")
    labor_questions = tools.compute_labor(session)
    checks.append(("C3 품 단계 질문에 가격 조건 없음", labor_questions["status"] == "needs_input"
                   and set(fields_of(labor_questions)) == set(PUMP)
                   and all(question["stage"] == "labor" for question in labor_questions["missing"])))
    checks.append(("C3 질문 선택지는 목록 또는 null", all(q["choices"] is None or isinstance(q["choices"], list)
                                                  for q in labor_questions["missing"])))
    answer(session, **PUMP)
    one = tools.compute_labor(session)
    direct = CALCULATORS["adjusted_daily_crew"](pump, {**PUMP, "volume": "1"}, labor_only=True)
    checks.append(("C3 1㎥ 품은 계산기 직접 결과와 같음", one["status"] == "ok" and one["data"]["quantity"] == "1"
                   and one["data"]["unit_lines"] == direct["unit_lines"]
                   and one["data"]["work_days"] == direct["work_days"]))
    tools.set_conditions(session, "같은 조건으로 100㎥ 비용 계산해줘",
                         quantity={"value": "100", "unit": "㎥", "evidence": "100㎥"})
    hundred = tools.estimate_cost(session)
    checks.append(("C4 물량 변경: 1단위 품 유지, 작업일수·인일·장비 100배",
                   hundred["data"]["unit_lines"] == one["data"]["unit_lines"]
                   and Fraction(hundred["data"]["work_days"]) == 100 * Fraction(one["data"]["work_days"])
                   and all(Fraction(hundred["data"]["person_days"][k]) == 100 * Fraction(v)
                           for k, v in one["data"]["person_days"].items())
                   and all(Fraction(hundred["data"]["equipment_days"][k]) == 100 * Fraction(v)
                           for k, v in one["data"]["equipment_days"].items())))
    checks.append(("C5 가격 단계에서만 관급/사급", hundred["status"] == "needs_input"
                   and fields_of(hundred) == ["concrete_supply"] and hundred["missing"][0]["stage"] == "price"))
    answer(session, concrete_supply="사급")
    private = tools.estimate_cost(session)
    checks.append(("C5 사급이면 레미콘 단가를 가격 단계에서 물음", fields_of(private) == ["ready_mix_price"]))

    # 4. 기존 금액 보존: check_api A4와 같은 입력이면 같은 합계
    legacy = started("철근콘크리트 벽체 260㎥ 펌프차로 타설 비용")
    tools.set_conditions(legacy, "", work="6-1-4", source="answer")
    answer(legacy, **PUMP, concrete_supply="관급")
    cost = tools.estimate_cost(legacy)
    checks.append(("C6 260㎥ 원가계산서 합계가 기존 그래프(A4)와 같음",
                   cost["status"] == "ok" and cost["data"]["statement"]["totals"] == A4_TOTALS))

    # 5. 재계산 범위: 가격 조건만 바꾸면 품을 다시 계산하지 않음
    calls = []
    original = CALCULATORS["adjusted_daily_crew"]

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    with patch.dict(CALCULATORS, {"adjusted_daily_crew": counted}):
        tools.estimate_cost(legacy)
        answer(legacy, concrete_supply="사급", ready_mix_price="90000")
        repriced = tools.estimate_cost(legacy)
        price_only_calls = len(calls)
        answer(legacy, slump_band="18㎝이상")
        relabored = tools.estimate_cost(legacy)
        labor_calls = len(calls)
        tools.set_conditions(legacy, "300㎥로", quantity={"value": "300", "unit": "㎥", "evidence": "300㎥"})
        requantity = tools.estimate_cost(legacy)
    checks.append(("C7 가격 조건만 변경: 품 재계산 0회, 금액은 갱신", price_only_calls == 0
                   and repriced["status"] == "ok"
                   and repriced["data"]["statement"]["totals"]["contract_amount"] != A4_TOTALS["contract_amount"]))
    checks.append(("C7 품 조건 변경: 품 재계산 1회", labor_calls == 1 and relabored["status"] == "ok"
                   and relabored["data"]["daily_volume_m3"] != cost["data"]["daily_volume_m3"]))
    checks.append(("C7 물량 변경: 품 재계산, 작업일수·금액 갱신", len(calls) == 2 and requantity["status"] == "ok"
                   and Fraction(requantity["data"]["work_days"]) == Fraction(300, 260) * Fraction(relabored["data"]["work_days"])
                   and requantity["data"]["statement"]["totals"]["contract_amount"]
                   > relabored["data"]["statement"]["totals"]["contract_amount"]))
    common = tools.set_conditions(legacy, "", values={"duration": {"value": "7~12개월"}}, source="answer")
    with patch.dict(CALCULATORS, {"adjusted_daily_crew": counted}):
        recommon = tools.estimate_cost(legacy)
    checks.append(("C7 공통 조건 변경: 품 재계산 없이 원가계산서 갱신", common["rejected"] == {} and len(calls) == 2
                   and recommon["data"]["statement"]["conditions"]["duration"] == "7~12개월"))

    # 6. 입력 검증
    guard = started("콘크리트 1㎥ 품셈 알려줘")
    bad_work = tools.set_conditions(guard, "", work="9-9-9", source="answer")
    tools.set_conditions(guard, "", work="6-1-4", source="answer")
    no_evidence = tools.set_conditions(guard, "펌프차 32m로", values={"pump_size": {"value": "36m", "evidence": "36m"}})
    no_field = tools.set_conditions(guard, "펌프차 32m", values={"pump_size": {"value": "32m"}})
    invalid = tools.set_conditions(guard, "", values={"slump_band": {"value": "99㎝"}}, source="answer")
    unknown = tools.set_conditions(guard, "", values={"wood_supply": {"value": "관급"}}, source="answer")
    wrong_unit = tools.set_conditions(guard, "100㎡", quantity={"value": "100", "unit": "㎡", "evidence": "100㎡"})
    grounded = tools.set_conditions(guard, "펌프차 32m로 해줘", values={"pump_size": {"value": "32m", "evidence": "32m"}})
    checks.append(("C8 후보 밖 공종·근거 없는 값·허용값 밖·없는 조건·단위 불일치 거부",
                   "work" in bad_work["rejected"] and "pump_size" in no_evidence["rejected"]
                   and "pump_size" in no_field["rejected"] and "slump_band" in invalid["rejected"]
                   and "wood_supply" in unknown["rejected"] and "quantity" in wrong_unit["rejected"]
                   and grounded["data"]["applied"] == {"pump_size": "32m"} and not grounded["rejected"]))

    # 7. 공종 변경: 맞지 않는 조건 버림, 물량 유지, 새 공종 조건만 물음
    switch = started("철근콘크리트 1㎥ 타설 품")
    tools.set_conditions(switch, "", work="6-1-4", source="answer")
    answer(switch, pump_size="32m", slump_band="15㎝")
    tools.set_conditions(switch, "", work="6-1-1", source="answer")
    switched = tools.compute_labor(switch)
    item = switch["items"][switch["item_order"][0]]
    checks.append(("C9 펌프차→인력 변경: 펌프차 조건 버림, 물량·구조 유지, 가격 조건 미질문",
                   switched["status"] == "needs_input"
                   and not set(fields_of(switched)) & {"pump_size", "slump_band", "concrete_supply"}
                   and {d["field"] for d in item.get("dropped_conditions", [])} >= {"pump_size", "slump_band"}
                   and item["conditions"].get("volume") == "1" and item["conditions"].get("structure") == "철근구조물"))

    # 8. 근거 도구
    finished = tools.explain_basis(legacy)
    legacy_item = legacy["items"][legacy["item_order"][0]]
    checks.append(("C10 완료된 견적의 근거 조회는 완료 상태를 유지", finished["status"] == "ok"
                   and legacy_item["status"] == "PRICED"
                   and legacy_item["result_revision"] == legacy_item["input_revision"]))
    basis = tools.explain_basis(session)
    standard = tools.search_standard("콘크리트 펌프차 타설 인력편성")
    checks.append(("C10 근거(daily_crew 6-1-4): 계산 결과의 원문 인용",
                   basis["status"] == "ok" and len(basis["data"]["citations"]) > 0))
    checks.append(("C10 search_standard는 원문 자료만", standard["status"] == "ok"
                   and set(standard["data"]) == {"sections"}
                   and all(set(s) == {"section", "truncated", "text", "chunk_ids"} for s in standard["data"]["sections"])))
    guarded(checks, "C11 근거(per_unit 10-1-7 자동문): 품 계산 후 원문 인용", check_per_unit_basis)

    # 9. 근거 구절과 값·단위 대조
    guarded(checks, "C12 근거와 다른 값·단위는 거부, 표기 정규화는 허용", check_evidence_values)

    # 10. 원가계산서 최신 판정: 변경 직후(재계산 전)와 재계산 후
    for name, check in stale_checks():
        guarded(checks, name, check)

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
