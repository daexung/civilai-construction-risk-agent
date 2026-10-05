"""compose 노드의 숫자 잠금과 LLM 실패 대체를 오프라인으로 검사한다."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["AGENT_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
os.environ["AGENT_LLM"] = "off"
os.environ["INDEX_CONFIG"] = str(ROOT / "evals" / "index_configs" / "6chapter_studio.json")
sys.path.insert(0, str(ROOT))

from langgraph.types import Command  # noqa: E402

from backend.agent.graph import build_graph  # noqa: E402
from backend.agent.nodes.compose import (_josa, build_facts, build_template, compose,
                                 unpriced_names, validate_amount_basis, validate_numbers)  # noqa: E402
from backend.agent.nodes.compute import compute  # noqa: E402
from backend.agent.nodes.gate import gate  # noqa: E402
from backend.agent.nodes.price import price  # noqa: E402
from backend.agent.nodes.statement import statement  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.agent.state import new_state  # noqa: E402
from backend.agent.tools.llm.client import LLMUnavailable  # noqa: E402
from backend.agent.tools.llm import client as llm_client  # noqa: E402


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
    with patch("backend.agent.nodes.compose._spec", return_value={
            "origin": "draft", "section_no": "6-1-4", "title": "draft test work",
            "inputs": [], "quantity_model": {"params": {"quantity_input": "volume"}}}):
        draft_facts = build_facts(state)
        captured_prompt = []
        draft_compose = compose(state, generate_fn=lambda prompt, _system: captured_prompt.append(prompt) or build_template(draft_facts))
    checks.append(("C0 draft-review fact omitted from compose input",
                   "draft_review" not in draft_facts and not captured_prompt
                   and draft_compose["answer_source"] == "fixed"))
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
    first_sentence = template.split("입니다.", 1)[0]
    checks.append(("C0d template 첫 문장 전체 물량 도급액",
                   facts["work"]["title"] in first_sentence and "260㎥" in first_sentence
                   and "전체 물량 기준 부가세 포함 도급액은" in first_sentence
                   and "10,032,436원" in first_sentence))
    duplicate_facts = json.loads(json.dumps(facts, ensure_ascii=False))
    for field in ("excluded", "unpriced"):
        if duplicate_facts["priced"][field]:
            duplicate_facts["priced"][field].append(duplicate_facts["priced"][field][0])
            duplicate_facts["statement"][field].append(duplicate_facts["statement"][field][0])
    duplicate_text = build_template(duplicate_facts)
    duplicate_names = unpriced_names(facts)
    checks.append(("C0e 빠진 항목 이름 중복 제거",
                   "미산정 항목:" not in duplicate_text and "빠졌습니다." in duplicate_text
                   and all(duplicate_text.count(name) == 1 for name in duplicate_names)))
    checks.append(("C0f 숫자·괄호 뒤 조사 선택",
                   f"912,039원{_josa('912,039원', '을/를')}" == "912,039원을"
                   and f"(6-1-4){_josa('타설(6-1-4)', '은/는')}" == "(6-1-4)은"
                   and f"(부분){_josa('참고 금액(부분)', '은/는')}" == "(부분)은"
                   ))

    def good_llm(prompt: str, system: str) -> str:
        return (f"{facts['work']['title']} 260㎥ 전체 물량 기준 부가세 포함 도급액은 "
                f"{facts['statement']['totals']['전체 물량 기준 도급액(부가세 포함)']}입니다. "
                f"미산정 항목: {', '.join(unpriced_names(facts))}.")

    good = compose(state, generate_fn=good_llm)
    checks.append(("C1 견적은 fixed 문장 사용", good["answer_source"] == "fixed"
                   and good["answer"] == build_template(facts)))

    estimate_facts = {
        "status": "PARTIAL", "work": {"title": "자동문 설치", "section_no": "10-1-7"},
        "quantity": "3", "unit": "개소", "inputs": [],
        "priced": {"unpriced": [{"name": "유리공사"}], "excluded": []},
        "statement": {"totals": {"전체 물량 기준 도급액(부가세 포함)": "2,727,421원"},
                      "unpriced": [{"name": "유리공사"}], "excluded": []},
    }
    estimate_answer = ("자동문 설치 3개소 전체 물량 기준 부가세 포함 도급액은 "
                       "2,727,421원입니다. 유리공사는 단가가 없어 빠졌습니다.")
    with patch("backend.agent.nodes.compose.build_facts", return_value=estimate_facts):
        estimate_llm = compose({"status": "PARTIAL", "priced": {"unpriced": []}}, generate_fn=lambda *_: estimate_answer)
    checks.append(("C1b VAT-inclusive contract amount with unpriced item accepted",
                   estimate_llm["answer_source"] == "fixed" and estimate_llm["answer"] == estimate_answer))

    def legacy_compose(st, generate_fn=None):
        # No calculated tables: exercise the unchanged LLM validation/client path.
        with patch("backend.agent.nodes.compose.build_facts", return_value=facts):
            return compose({"status": st["status"]}, generate_fn=generate_fn)

    def bad_number_llm(prompt: str, system: str) -> str:
        return "이번 계산은 약 25,000원 정도로 예상됩니다."

    bad = legacy_compose(state, generate_fn=bad_number_llm)
    checks.append(("C2 facts에 없는 숫자는 거부", bad["answer_source"] == "template"
                   and "25000" in bad["llm_info"]["bad_numbers"]
                   and bad["answer"] == build_template(facts)))

    def raising_llm(prompt: str, system: str) -> str:
        raise RuntimeError("모의 LLM 실패")

    failed = legacy_compose(state, generate_fn=raising_llm)
    checks.append(("C3 가짜 LLM 예외는 template", failed["answer_source"] == "template"
                   and failed["answer"] == build_template(facts)))

    def unavailable_llm(prompt: str, system: str) -> str:
        raise LLMUnavailable("모의 실패")

    unavailable = legacy_compose(state, generate_fn=unavailable_llm)
    checks.append(("C3b LLMUnavailable도 template", unavailable["answer_source"] == "template"))

    original_env = os.environ.get("AGENT_LLM")
    os.environ["AGENT_LLM"] = "off"
    try:
        off_result = legacy_compose(state)  # generate_fn 주입 없이 실제 client.generate 경로 — 네트워크 호출 없음
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
                   and legacy_compose(state, generate_fn=lambda *_: basis_missing_text)["answer_source"] == "template"))

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
        retried = legacy_compose(state, generate_fn=lambda prompt, system: llm_client.generate(
            prompt, system, request_fn=retry_backend, sleep_fn=lambda _seconds: None))
    checks.append(("C11 503 두 번 후 성공 재시도", retried["answer_source"] == "llm"
                   and retried["llm_info"]["provider"] == "vertex"
                   and retried["llm_info"]["attempts"] == 3 and len(retry_calls) == 3))

    def bad_request(model: str, prompt: str, system: str, timeout_ms: int) -> str:
        raise FakeServiceError("invalid argument", 400)

    with patch.dict(os.environ, {"AGENT_LLM": "on", "LLM_PROVIDER": "vertex"}, clear=False), \
            patch.object(llm_client, "_env_value", env_for_fake):
        rejected = legacy_compose(state, generate_fn=lambda prompt, system: llm_client.generate(
            prompt, system, request_fn=bad_request, sleep_fn=lambda _seconds: None))
    checks.append(("C12 400 즉시 template", rejected["answer_source"] == "template"
                   and rejected["llm_info"]["attempts"] == 1))

    with patch.dict(os.environ, {"AGENT_LLM": "on", "LLM_PROVIDER": "vertex"}, clear=False), \
            patch.object(llm_client, "_env_value", lambda _name: None):
        no_vertex_key = legacy_compose(state)
    checks.append(("C13 Vertex 키 없음은 LLMUnavailable", no_vertex_key["answer_source"] == "template"
                   and no_vertex_key["llm_info"]["provider"] == "vertex"
                   and no_vertex_key["llm_info"]["error"] == "VERTEX_API_KEY 없음"))

    factory_calls, requests = [], []
    key = ["compose-key-1"]
    def fake_factory(provider, api_key):
        factory_calls.append((provider, api_key))
        def generate_content(**kwargs):
            requests.append(kwargs)
            return SimpleNamespace(text=good_llm("", ""))
        return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

    with patch.dict(os.environ, {"AGENT_LLM": "on", "LLM_PROVIDER": "vertex"}), \
            patch.object(llm_client, "_CLIENTS", {}), \
            patch.object(llm_client, "_env_value", side_effect=lambda name: key[0] if name == "VERTEX_API_KEY" else None), \
            patch.object(llm_client, "_create_client", side_effect=fake_factory):
        first, second = legacy_compose(state), legacy_compose(state)
        checks.append(("C14 compose 클라이언트 재사용", len(factory_calls) == 1 and len(requests) == 2
                       and first["answer_source"] == second["answer_source"] == "llm"))
        key[0] = "compose-key-2"
        changed = legacy_compose(state)
        checks.append(("C15 키 변경 시 새 클라이언트", len(factory_calls) == 2
                       and factory_calls[-1] == ("vertex", key[0]) and changed["answer_source"] == "llm"))
        with patch.dict(os.environ, {"LLM_PROVIDER": "studio"}), \
                patch.object(llm_client, "_env_value", return_value=key[0]):
            switched = legacy_compose(state)
        checks.append(("C16 provider도 캐시 구분", len(factory_calls) == 3
                       and factory_calls[-1] == ("studio", key[0]) and switched["answer_source"] == "llm"))

    now, requests = [0.0], []
    def fake_sleep(seconds):
        now[0] += seconds
    def slow_factory(provider, api_key):
        fake_sleep(20.1)
        return fake_factory(provider, api_key)
    with patch.dict(os.environ, {"AGENT_LLM": "on", "LLM_PROVIDER": "vertex"}), \
            patch.object(llm_client, "_CLIENTS", {}), \
            patch.object(llm_client, "_env_value", return_value="slow-key"), \
            patch.object(llm_client, "_create_client", side_effect=slow_factory):
        slow = legacy_compose(state, generate_fn=lambda prompt, system: llm_client.generate(
            prompt, system, clock_fn=lambda: now[0]))
    checks.append(("C17 생성 시간 초과는 요청 없이 template", slow["answer_source"] == "template"
                   and slow["llm_info"]["attempts"] == 0 and not requests))

    graph = build_graph()
    config = {"configurable": {"thread_id": "compose-g1"}}
    graph.invoke(new_state("철근콘크리트 벽체 260㎥ 32m 펌프차로 타설 비용"), config)
    final = graph.invoke(Command(resume="기타 토목공사 6개월 종합건설업 이 견적만 15cm 타입2 현장 2유형 붐 진동기 사용 재셋팅 없음 레미콘 관급"), config)
    checks.append(("C8 그래프 전체: PARTIAL 유지", final["status"] == "PARTIAL"))
    checks.append(("C9 그래프 전체: answer 필드 추가", bool(final.get("answer"))
                   and final.get("answer_source") == "fixed"))

    out_of_scope = graph.invoke(new_state("오늘 현장 날씨 어때?"), {"configurable": {"thread_id": "compose-g2"}})
    checks.append(("C10 그래프 전체: OUT_OF_SCOPE도 answer 추가", out_of_scope["status"] == "OUT_OF_SCOPE"
                   and bool(out_of_scope.get("answer"))))

    default_sources = {name: "기본값" for name in ("work_category", "duration", "contractor_type", "project_scale")}
    default_facts = build_facts({**state, "input_sources": default_sources})
    chosen_facts = build_facts({**state, "input_sources": {**default_sources, "duration": "선택"}})
    default_text = build_template(default_facts)
    chosen_text = build_template(chosen_facts)
    checks.append(("C-new1 답변은 조건 요약 없이, facts에 기본 조건 유지",
                   "(기준:" not in default_text and "(기준:" not in chosen_text
                   and default_facts["condition_summary"] == "토목 · 1~6개월 · 종합건설업 · 단독 공사"
                   and default_facts["condition_default"] is True
                   and chosen_facts["condition_summary"] == default_facts["condition_summary"]
                   and chosen_facts["condition_default"] is False))

    def omit_unpriced_llm(prompt: str, system: str) -> str:
        return ("전체 물량 기준 부가세 포함 도급액은 "
                + facts["statement"]["totals"]["전체 물량 기준 도급액(부가세 포함)"] + "입니다.")

    omitted = legacy_compose(state, generate_fn=omit_unpriced_llm)
    checks.append(("C-new2 미산정 누락이면 template", omitted["answer_source"] == "template"
                   and omitted["llm_info"]["error"] == "미산정 누락"))

    calls = []
    def counted_generate(*args):
        calls.append(args)
        return "공사비 계산 질문으로 문의해 주세요."
    for status in ("PARTIAL", "OK"):
        fixed = compose({**state, "status": status}, generate_fn=counted_generate)
        checks.append((f"C-fixed {status} LLM 호출 0회",
                       not calls and fixed["answer_source"] == "fixed"
                       and fixed["llm_info"] == {"skipped": "estimate_fixed_text"}
                       and fixed["answer"] == build_template(build_facts({**state, "status": status}))))
    scope = compose(out_of_scope_state(), generate_fn=counted_generate)
    checks.append(("C-fixed OUT_OF_SCOPE LLM 호출 유지", len(calls) == 1 and scope["answer_source"] == "llm"))
    checks.append(("C-fixed 미산정 사유 구분",
                   "건설기계대여대금 지급보증 수수료는 이번 계산에서 빠졌습니다." in template))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
