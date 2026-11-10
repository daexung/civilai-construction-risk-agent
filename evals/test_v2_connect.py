"""R3 연결 오프라인 시험: ROUTER_V2 스위치, 턴당 1회 판단, 되묻기 카드·버튼 답, 실패 안내."""
import pytest

from backend.agent.estimate import dialogue as d
from backend.agent.v2 import router as v2router


def ok(route, kind=None, clarify=None):
    reqs = [{"kind": kind}] if kind else []
    return {"status": "ok", "output": {"route": route, "requests": reqs, "clarify": clarify},
            "dispatch": [], "errors": [], "calls_used": 1}


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ROUTER_V2", "on")
    calls, seen = [], []

    def fake_route(message, previous=None, **kw):
        calls.append(message)
        return env.result

    def fake_inner(state, request, generate=None, clock=None):
        seen.append(d._route(request["message"], None))
        env.messages.append(request["message"])
        return {**(state or d.new_dialogue()), "turn": {"answer": "기존 흐름", "trace": []}}

    monkeypatch.setattr(v2router, "route_turn", fake_route)
    monkeypatch.setattr(d, "_run_turn", fake_inner)
    env.calls, env.seen, env.messages = calls, seen, []
    return env


def test_switch_off_uses_rule(env, monkeypatch):
    monkeypatch.delenv("ROUTER_V2")
    d.run_turn(None, {"message": "견적 좀요"})
    assert env.calls == []


def test_v2_label_replaces_rule_for_this_turn(env):
    env.result = ok("work", "qa")
    out = d.run_turn(None, {"message": "콘크리트 50㎥ 얼마"})  # 규칙이면 estimate
    assert env.calls == ["콘크리트 50㎥ 얼마"] and env.seen == ["qa"]
    assert out["turn"]["trace"][0]["tool"] == "router_v2"
    assert d._route("콘크리트 50㎥ 얼마") == "estimate"  # 턴이 끝나면 규칙으로 돌아간다


def test_failed_asks_retry_without_rule(env):
    env.result = {"status": "failed", "output": None, "errors": ["504"], "calls_used": 1}
    out = d.run_turn(None, {"message": "견적 좀요"})
    assert out["turn"]["answer"] == "잠시 후 다시 시도해 주세요." and env.seen == []


def test_clarify_card_then_button_reroutes(env):
    env.result = ok("clarify", clarify={"ask": "무엇이 궁금하세요?", "options": ["품", "공사비"]})
    out = d.run_turn(None, {"message": "방수 200㎡ 어떻게 생각해?"})
    card = out["pending"][0]
    assert card["kind"] == "choice" and card["choices"] == ["품", "공사비"] and env.seen == []
    env.result = ok("work", "estimate")
    d.run_turn(out, {"answers": {d.CLARIFY_FIELD: "공사비"}, "refs": {d.CLARIFY_FIELD: card["ref"]}})
    assert env.calls[-1] == "방수 200㎡ 어떻게 생각해? (원하는 것: 공사비)"  # 판단에는 고른 값까지
    assert env.seen == ["estimate"] and env.messages[-1] == "방수 200㎡ 어떻게 생각해?"  # 흐름에는 원래 질문만


def test_stale_clarify_button_rejected(env):
    env.result = ok("clarify", clarify={"ask": "무엇?", "options": ["품"]})
    out = d.run_turn(None, {"message": "방수"})
    res = d.run_turn(out, {"answers": {d.CLARIFY_FIELD: "품"}, "refs": {d.CLARIFY_FIELD: "old"}})
    assert "오래" in res["turn"]["answer"] and len(env.calls) == 1


def test_clarify_without_options_is_text_only(env):
    env.result = ok("clarify", clarify={"ask": "어떤 공사인가요?", "options": []})
    out = d.run_turn(None, {"message": "이거 얼마예요?"})
    assert out["pending"] == [] and out["turn"]["answer"] == "어떤 공사인가요?"
