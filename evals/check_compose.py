"""compose 노드의 숫자 잠금과 LLM 실패 대체를 오프라인으로 검사한다."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ["AGENT_OFFLINE"] = "1"
os.environ.setdefault("AGENT_LLM", "off")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langgraph.types import Command  # noqa: E402

from agent.graph import build_graph  # noqa: E402
from agent.nodes.compose import (_josa, build_facts, build_template, compose,
                                 validate_amount_basis, validate_numbers)  # noqa: E402
from agent.nodes.compute import compute  # noqa: E402
from agent.nodes.gate import gate  # noqa: E402
from agent.nodes.price import price  # noqa: E402
from agent.nodes.statement import statement  # noqa: E402
from agent.rules.specs import load_specs  # noqa: E402
from agent.state import new_state  # noqa: E402
from agent.tools.llm.client import LLMUnavailable  # noqa: E402
from agent.tools.llm import client as llm_client  # noqa: E402


PUMP_SPEC = next(spec for spec in load_specs().values() if spec["section_no"] == "6-1-4")
PUMP_INPUTS = {
    "pump_size": "32m", "volume": "260", "structure": "철근", "slump_band": "15㎝",
    "facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ", "placement": "붐",
    "vibrator_used": True, "reset_status": "없음", "concrete_supply": "관급",
    "work_category": "기타 토목공사", "duration": "1~6개월", "contractor_type": "종합건설업",
    "project_scale": "이 견적만",
}


def partial_state() -> dict:
    state = {"spec_id": PUMP_SPEC["id"], "inputs": PUMP_INPUTS,
             "selection": {"section_no": "6-1-4", "section": PUMP_SPEC["title"]},
             "basis_date": "2026-10-01"}
    state.update(gate(state))
    state.update(compute(state))
    state.update(price(state))
    state.update(statement(state))
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
    priced_facts = facts["priced"]
    checks.append(("C0 facts 금액에 단위·참고 기준 표시",
                   "1㎥당 합계(부분)" in priced_facts
                   and "합계" not in priced_facts
                   and "260㎥ 기준 참고 금액(부분)" in priced_facts
                   and priced_facts["260㎥ 기준 참고 금액(부분)"] == "5,650,840원"
                   and all(key.startswith("1㎥당 ") for key in priced_facts["1㎥당 소계"])))
    checks.append(("C0b 6-1-4 제외·미산정에 펌프차 기계경비 없음",
                   all("펌프차 기계경비" not in item["name"]
                       for field in ("excluded", "unpriced") for item in priced_facts[field])))
    checks.append(("C0c 원가계산서 도급액 facts",
                   facts["statement"]["totals"]["전체 물량 기준 도급액(부가세 포함)"] == "10,032,436원"
                   and facts["statement"]["totals"]["전체 물량 기준 순공사원가"] == "7,364,857원"))

    template = build_template(facts)
    checks.append(("C0d template 첫 문장 전체 물량 도급액",
                   template.split(".", 1)[0].startswith("철근콘크리트 벽체 260㎥ 콘크리트 펌프차 붐타설 공사비는 전체 물량 기준 부가세 포함 총 10,032,436원(도급액)")))
    duplicate_facts = json.loads(json.dumps(facts, ensure_ascii=False))
    for field in ("excluded", "unpriced"):
        if duplicate_facts["priced"][field]:
            duplicate_facts["priced"][field].append(duplicate_facts["priced"][field][0])
            duplicate_facts["statement"][field].append(duplicate_facts["statement"][field][0])
    duplicate_text = build_template(duplicate_facts)
    duplicate_names = [item["name"] for field in ("excluded", "unpriced")
                       for item in facts["priced"][field]]
    checks.append(("C0e 빠진 항목 이름 중복 제거",
                   duplicate_text.count("빠진 항목:") == 1
                   and all(duplicate_text.count(name) == 1 for name in duplicate_names)))
    checks.append(("C0f 숫자·괄호 뒤 조사 선택",
                   f"912,039원{_josa('912,039원', '을/를')}" == "912,039원을"
                   and f"(6-1-4){_josa('타설(6-1-4)', '은/는')}" == "(6-1-4)은"
                   and f"(부분){_josa('참고 금액(부분)', '은/는')}" == "(부분)은"
                   and "912,039원을 반영했습니다." in template
                   and "타설(6-1-4)은" in template
                   and "참고 금액(부분)은" in template))

    def good_llm(prompt: str, system: str) -> str:
        return (f"{facts['work']['title']} 계산 결과 1㎥당 합계(부분)는 "
                f"{facts['priced']['1㎥당 합계(부분)']}입니다. "
                f"260㎥ 기준 참고 금액(부분)은 {facts['priced']['260㎥ 기준 참고 금액(부분)']}입니다. "
                "미산정 항목이 포함되지 않았습니다. "
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

    ok, bad_numbers = validate_numbers("6-1-4 절의 합계는 21,734원입니다.", facts)
    checks.append(("C6 숫자 정규화(쉼표·절 번호)", ok and not bad_numbers))
    ok2, bad_numbers2 = validate_numbers("약 21735.5원입니다.", facts)
    checks.append(("C7 facts에 없는 소수도 거부", not ok2 and "21735.5" in bad_numbers2))

    basis_missing_text = "총 공사비 21,734원입니다."
    checks.append(("C7b 금액 기준 표시 누락은 template 대체",
                   validate_numbers(basis_missing_text, facts)[0]
                   and not validate_amount_basis(basis_missing_text)
                   and compose(state, generate_fn=lambda *_: basis_missing_text)["answer_source"] == "template"))

    class FakeServiceError(Exception):
        def __init__(self, message: str, code: int):
            super().__init__(message)
            self.code = code

    def env_for_fake(name: str) -> str | None:
        return "fake-test-key" if name == "VERTEX_API_KEY" else None

    def retry_backend(model: str, prompt: str, system: str, timeout_ms: int) -> str:
        retry_calls.append((model, timeout_ms))
        if len(retry_calls) < 3:
            raise FakeServiceError("UNAVAILABLE", 503)
        return good_llm(prompt, system)

    retry_calls = []
    with patch.dict(os.environ, {"AGENT_LLM": "on", "LLM_PROVIDER": "vertex"}, clear=False), \
            patch.object(llm_client, "_env_value", env_for_fake):
        retried = compose(state, generate_fn=lambda prompt, system: llm_client.generate(
            prompt, system, request_fn=retry_backend, sleep_fn=lambda _seconds: None))
    checks.append(("C11 503 두 번 후 성공 재시도", retried["answer_source"] == "llm"
                   and retried["llm_info"]["provider"] == "vertex"
                   and retried["llm_info"]["attempts"] == 3 and len(retry_calls) == 3))

    def bad_request(model: str, prompt: str, system: str, timeout_ms: int) -> str:
        raise FakeServiceError("invalid argument", 400)

    with patch.dict(os.environ, {"AGENT_LLM": "on", "LLM_PROVIDER": "vertex"}, clear=False), \
            patch.object(llm_client, "_env_value", env_for_fake):
        rejected = compose(state, generate_fn=lambda prompt, system: llm_client.generate(
            prompt, system, request_fn=bad_request, sleep_fn=lambda _seconds: None))
    checks.append(("C12 400 즉시 template", rejected["answer_source"] == "template"
                   and rejected["llm_info"]["attempts"] == 1))

    with patch.dict(os.environ, {"AGENT_LLM": "on", "LLM_PROVIDER": "vertex"}, clear=False), \
            patch.object(llm_client, "_env_value", lambda _name: None):
        no_vertex_key = compose(state)
    checks.append(("C13 Vertex 키 없음은 LLMUnavailable", no_vertex_key["answer_source"] == "template"
                   and no_vertex_key["llm_info"]["provider"] == "vertex"
                   and no_vertex_key["llm_info"]["error"] == "VERTEX_API_KEY 없음"))

    graph = build_graph()
    config = {"configurable": {"thread_id": "compose-g1"}}
    graph.invoke(new_state("철근콘크리트 벽체 260㎥ 32m 펌프차로 타설 비용"), config)
    final = graph.invoke(Command(resume="기타 토목공사 6개월 종합건설업 이 견적만 15cm 타입2 현장 2유형 붐 진동기 사용 재셋팅 없음 레미콘 관급"), config)
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
