"""v2 라우터 오프라인 시험: 가짜 generate로 스키마·사실 확인·고치기·보내기를 본다."""
import json

import pytest

from backend.agent.tools.llm.client import LLMUnavailable
from backend.agent.v2 import router as r

PENDING = {"kind": "needs_input", "work": "건축 블록쌓기",
           "pending_questions": [{"question_id": "q2", "ask": "보강 철근?", "allowed_values": ["있음", "없음"]}],
           "last_answer_summary": "블록 120㎡ 견적 중"}


def fake(*outputs):
    """차례로 출력을 돌려주는 가짜 generate. 호출 기록을 남긴다."""
    calls = []

    def gen(prompt, system, **kw):
        calls.append(prompt)
        item = outputs[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else item
    gen.calls = calls
    return gen


def req(**kw):
    base = {"id": "r1", "kind": "estimate", "estimate_mode": "new",
            "target": {"user_text": "타일", "evidence": "타일", "search_terms": ["타일붙이기"]},
            "quantity": None, "conditions": [], "asks": "공사비", "wants": "calculate", "card_answer": None}
    base.update(kw)
    return base


def work(*reqs):
    return {"route": "work", "requests": list(reqs), "clarify": None, "out_of_scope_kind": "none", "confidence": 0.9}


def test_examples_follow_rules():
    """지어낸 few-shot 예시가 코드 규칙을 모두 지킨다."""
    for raw in (r.PROMPT_DIR / "examples.jsonl").read_text(encoding="utf-8").splitlines():
        if raw.strip():
            ex = json.loads(raw)
            out = r.RouterOutput.model_validate(ex["output"])
            assert r.validate(out, r.RouterInput.model_validate(ex["input"])) == [], ex["note"]


def test_wants_is_required_enum():
    bad = work(req(wants="money"))
    res = r.route_turn("타일 공사비", generate=fake(bad, bad))
    assert res["status"] == "output_error" and any("wants" in e for e in res["errors"])


def test_system_prompt_includes_examples():
    s = r.load_system_prompt()
    assert "## 예시" in s and "욕실 벽 타일" in s


def test_ok_estimate():
    gen = fake(work(req(quantity={"value": "80", "unit": "㎡", "evidence": "80㎡"})))
    res = r.route_turn("타일 80㎡ 공사비", generate=gen)
    assert res["status"] == "ok" and res["calls_used"] == 1
    assert res["dispatch"] == [{"node": "estimate_agent", "request_id": "r1"}]


def test_mixed_dispatch():
    gen = fake(work(req(), req(id="r2", kind="qa", estimate_mode="none")))
    res = r.route_turn("타일 견적이랑 할증", generate=gen)
    assert [d["node"] for d in res["dispatch"]] == ["estimate_agent", "qa_agent"]


def test_repair_then_ok():
    bad = work(req(target={"user_text": "타일", "evidence": "벽돌", "search_terms": []}))
    gen = fake(bad, work(req()))
    res = r.route_turn("타일 공사비", generate=gen)
    assert res["status"] == "ok" and res["calls_used"] == 2
    assert "벽돌" in gen.calls[1] and "직전 출력" in gen.calls[1]


def test_repair_fails_twice():
    bad = work(req(quantity={"value": "90", "unit": "㎡", "evidence": "타일"}))
    res = r.route_turn("타일 80㎡ 공사비", generate=fake(bad, bad))
    assert res["status"] == "output_error" and res["calls_used"] == 2
    assert any("90" in e for e in res["errors"])


def test_broken_json_is_output_error():
    res = r.route_turn("타일", generate=fake("not json", "{}"))
    assert res["status"] == "output_error" and res["calls_used"] == 2


def test_llm_unavailable_is_failed():
    res = r.route_turn("타일", generate=fake(LLMUnavailable("off")))
    assert res["status"] == "failed" and res["calls_used"] == 1


def test_card_answer_checks_allowed_values():
    ans = req(estimate_mode="card_answer", target=None,
              card_answer={"question_id": "q2", "value": "모름", "evidence": "없어요"})
    out = r.RouterOutput.model_validate(work(ans))
    errs = r.validate(out, r.RouterInput(message="없어요", previous=PENDING))
    assert any("허용 값" in e for e in errs)


def test_change_needs_active_estimate():
    out = r.RouterOutput.model_validate(work(req(estimate_mode="change", target=None)))
    errs = r.validate(out, r.RouterInput(message="150으로 바꿔줘"))
    assert any("진행 중 견적" in e for e in errs)


def test_route_field_consistency():
    out = r.RouterOutput.model_validate(
        {"route": "out_of_scope", "requests": [], "clarify": None, "out_of_scope_kind": "none", "confidence": 0.9})
    assert r.validate(out, r.RouterInput(message="영화")) != []


def test_button_bypasses_ai():
    gen = fake()
    res = r.route_turn("", PENDING, button={"question_id": "q2", "value": "없음"}, generate=gen)
    assert res["status"] == "ok" and res["calls_used"] == 0 and gen.calls == []
    assert res["dispatch"][0]["node"] == "estimate_agent"


def test_button_bad_value():
    res = r.route_turn("", PENDING, button={"question_id": "q2", "value": "몰라"}, generate=fake())
    assert res["status"] == "output_error"


def test_whitespace_ignored_in_evidence():
    out = r.RouterOutput.model_validate(work(req(target={"user_text": "벽 타일", "evidence": "벽타일", "search_terms": []})))
    assert r.validate(out, r.RouterInput(message="벽 타일 견적")) == []
