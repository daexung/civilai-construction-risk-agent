"""compose 노드의 숫자 잠금과 LLM 실패 대체를 오프라인으로 검사한다."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["AGENT_OFFLINE"] = "1"
os.environ.setdefault("AGENT_LLM", "off")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langgraph.types import Command  # noqa: E402

from agent.graph import build_graph  # noqa: E402
from agent.nodes.compose import build_facts, build_template, compose, validate_numbers  # noqa: E402
from agent.nodes.compute import compute  # noqa: E402
from agent.nodes.gate import gate  # noqa: E402
from agent.nodes.price import price  # noqa: E402
from agent.rules.specs import load_specs  # noqa: E402
from agent.state import new_state  # noqa: E402
from agent.tools.llm.client import LLMUnavailable  # noqa: E402


PUMP_SPEC = next(spec for spec in load_specs().values() if spec["section_no"] == "6-1-4")
PUMP_INPUTS = {
    "pump_size": "32m", "volume": "260", "structure": "철근", "slump_band": "15㎝",
    "facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ", "placement": "붐",
    "vibrator_used": True, "reset_status": "없음", "concrete_supply": "관급",
}


def partial_state() -> dict:
    state = {"spec_id": PUMP_SPEC["id"], "inputs": PUMP_INPUTS,
             "selection": {"section_no": "6-1-4", "section": PUMP_SPEC["title"]},
             "basis_date": "2026-10-01"}
    state.update(gate(state))
    state.update(compute(state))
    state.update(price(state))
    return state


def blocked_state() -> dict:
    inputs = {**PUMP_INPUTS, "reset_status": "있음"}
    state = {"spec_id": PUMP_SPEC["id"], "inputs": inputs,
             "selection": {"section_no": "6-1-4", "section": PUMP_SPEC["title"]}}
    state.update(gate(state))
    return state


def evidence_state() -> dict:
    return {"status": "EVIDENCE_ONLY", "reason": "6-3-1 절의 계산 명세가 없습니다",
            "hits": [{"section_no": "6-3-1", "section": "6-3-1 합판거푸집 설치",
                     "page": 120, "table_id": None, "text": "합판거푸집 설치 인력편성"}]}


def out_of_scope_state() -> dict:
    return {"status": "OUT_OF_SCOPE", "reason": "공사비·품셈 계산 질문이 아닙니다"}


def main() -> int:
    checks = []
    state = partial_state()
    checks.append(("사전조건: 부분 계산 상태", state["status"] == "PARTIAL"))
    facts = build_facts(state)

    def good_llm(prompt: str, system: str) -> str:
        return (f"{facts['work']['title']} 계산 결과 합계는 {facts['priced']['합계']}원입니다. "
                "표준품셈 기준 금액이며 시장 가격과 다를 수 있습니다.")

    good = compose(state, generate_fn=good_llm)
    checks.append(("C1 facts 숫자만 쓰면 llm 채택", good["answer_source"] == "llm"
                   and good["answer"] == good_llm("", "")))

    def bad_number_llm(prompt: str, system: str) -> str:
        return "이번 계산은 약 25,000원 정도로 예상됩니다."

    bad = compose(state, generate_fn=bad_number_llm)
    checks.append(("C2 facts에 없는 숫자는 거부", bad["answer_source"] == "template"
                   and "25000" in bad["llm_info"]["bad_numbers"]
                   and bad["answer"] == build_template(facts)))

    def raising_llm(prompt: str, system: str) -> str:
        raise RuntimeError("모의 LLM 실패")

    failed = compose(state, generate_fn=raising_llm)
    checks.append(("C3 가짜 LLM 예외는 template", failed["answer_source"] == "template"
                   and failed["answer"] == build_template(facts)))

    def unavailable_llm(prompt: str, system: str) -> str:
        raise LLMUnavailable("모의 실패")

    unavailable = compose(state, generate_fn=unavailable_llm)
    checks.append(("C3b LLMUnavailable도 template", unavailable["answer_source"] == "template"))

    original_env = os.environ.get("AGENT_LLM")
    os.environ["AGENT_LLM"] = "off"
    try:
        off_result = compose(state)  # generate_fn 주입 없이 실제 client.generate 경로 — 네트워크 호출 없음
    finally:
        if original_env is None:
            os.environ.pop("AGENT_LLM", None)
        else:
            os.environ["AGENT_LLM"] = original_env
    checks.append(("C4 AGENT_LLM=off는 호출 없이 template", off_result["answer_source"] == "template"
                   and off_result["llm_info"]["error"] == "AGENT_LLM=off"))

    per_status = {
        "PARTIAL": state,
        "BLOCKED": blocked_state(),
        "EVIDENCE_ONLY": evidence_state(),
        "OUT_OF_SCOPE": out_of_scope_state(),
    }
    for status, st in per_status.items():
        result = compose(st, generate_fn=raising_llm)
        template_text = result["answer"]
        checks.append((f"C5 {status} template 비어있지 않음", bool(template_text.strip())))
        checks.append((f"C5 {status} status 불변", "status" not in result))
    checks.append(("C5 상태 확인", all(st["status"] == status for status, st in per_status.items())))

    ok, bad_numbers = validate_numbers("6-1-4 절의 합계는 21,735원입니다.", facts)
    checks.append(("C6 숫자 정규화(쉼표·절 번호)", ok and not bad_numbers))
    ok2, bad_numbers2 = validate_numbers("약 21735.5원입니다.", facts)
    checks.append(("C7 facts에 없는 소수도 거부", not ok2 and "21735.5" in bad_numbers2))

    graph = build_graph()
    config = {"configurable": {"thread_id": "compose-g1"}}
    graph.invoke(new_state("철근콘크리트 벽체 260㎥ 32m 펌프차로 타설 비용"), config)
    final = graph.invoke(Command(resume="15cm 타입2 현장 2유형 붐 진동기 사용 재셋팅 없음 레미콘 관급"), config)
    checks.append(("C8 그래프 전체: PARTIAL 유지", final["status"] == "PARTIAL"))
    checks.append(("C9 그래프 전체: answer 필드 추가", bool(final.get("answer"))
                   and final.get("answer_source") in ("llm", "template")))

    out_of_scope = graph.invoke(new_state("오늘 현장 날씨 어때?"), {"configurable": {"thread_id": "compose-g2"}})
    checks.append(("C10 그래프 전체: OUT_OF_SCOPE도 answer 추가", out_of_scope["status"] == "OUT_OF_SCOPE"
                   and bool(out_of_scope.get("answer"))))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
