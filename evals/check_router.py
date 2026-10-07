"""외부 호출 없이 라우터 분류, 재시도, 상담 그래프 경로를 검사한다."""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.graph import build_graph  # noqa: E402
from backend.agent.nodes.route import ROUTE_SCHEMA, route  # noqa: E402
from backend.agent.nodes.retrieve import retrieve  # noqa: E402
from backend.agent.state import new_state  # noqa: E402
from backend.agent.tools.llm import client  # noqa: E402


def _response(label: str, confidence: float = 0.9, search_query: str = "standard cost question") -> str:
    return json.dumps({"route": label, "confidence": confidence,
                       "reason": "classified by question intent", "search_query": search_query})

class FakeServiceError(Exception):
    def __init__(self, code: int):
        super().__init__(f"service status {code}")
        self.code = code


def main() -> int:
    checks = []
    checks.append(("router schema includes search_query", "search_query" in ROUTE_SCHEMA["properties"]))
    class SearchStub:
        api_calls = 0
        fallback_reason = None
        used = "hybrid"
        def __init__(self): self.queries = []
        def search(self, query, k=10):
            self.queries.append(query)
            chunk = {"chunk_id": query, "kind": "text", "section_no": "6-1-4", "division": "common",
                     "section": "concrete", "source": {"page": 186, "table_id": "p186-x16"},
                     "structure": {}, "text": query}
            return [(1.0, chunk)]
    original = "\uC9C4\uB3D9\uAE30 \uC548 \uC4F0\uBA74 \uC778\uC6D0\uC774 \uC904\uC5B4?"
    expanded = "\uCF58\uD06C\uB9AC\uD2B8 \uD0C0\uC124 \uC9C4\uB3D9\uAE30 \uBBF8\uC0AC\uC6A9 \uC778\uC6D0 \uD3B8\uC131 \uAC10"
    search_stub = SearchStub()
    with patch("backend.agent.nodes.retrieve.get_search", return_value=(search_stub, "hybrid", None)):
        merged_state = new_state(original)
        merged_state.update(route_source="llm", search_query=expanded)
        merged = retrieve(merged_state)
    checks.append(("LLM search_query searches both and reports them",
                   search_stub.queries == [original, expanded]
                   and merged["search_info"]["queries"] == search_stub.queries and len(merged["hits"]) == 2))
    search_stub = SearchStub()
    with patch("backend.agent.nodes.retrieve.get_search", return_value=(search_stub, "bm25(offline)", None)):
        fallback_state = new_state(original)
        fallback_state.update(route_source="rule", search_query=expanded)
        fallback = retrieve(fallback_state)
    checks.append(("rule fallback searches original once", search_stub.queries == [original]
                   and fallback["search_info"]["queries"] == search_stub.queries))
    state = new_state("콘크리트공 품이 얼마야?")
    with patch.dict(os.environ, {"AGENT_LLM": "on"}):
        valid = route(state, generate_fn=lambda *_args, **_kwargs: _response("qa"))
        checks.append(("valid JSON and qa", valid["route"] == "qa" and valid["route_source"] == "llm"))
        invalid = route(new_state("공사비 알려줘"), generate_fn=lambda *_args, **_kwargs: "bad json")
        checks.append(("invalid JSON falls back", invalid["route"] == "estimate" and invalid["route_source"] == "rule"))
        def timed_out(*_args, **_kwargs):
            raise TimeoutError("timed out")
        timed = route(new_state("공사비 알려줘"), generate_fn=timed_out)
        checks.append(("timeout falls back", timed["route_source"] == "rule"))
        low = route(state, generate_fn=lambda *_args, **_kwargs: _response("estimate", 0.5))
        checks.append(("low confidence chooses qa", low["route"] == "qa" and low["route_source"] == "llm_low_confidence"))
        captured = []
        context_state = new_state("레미콘 사급으로 바꿔줘")
        context_state["previous_context"] = {"previous_route": "estimate", "work": "공통 6-1-4 콘크리트 펌프차 타설",
                                             "result": "도급액 10,032,436원"}
        def capture(prompt, _system, **_kwargs):
            captured.append(prompt)
            return _response("estimate")
        route(context_state, generate_fn=capture)
        checks.append(("previous summary in prompt", "견적 / 공통 6-1-4 콘크리트 펌프차 타설 / 도급액 10,032,436원" in captured[0]))

        with patch.object(client, "_env_value", return_value="fake-key"), \
                patch.dict(os.environ, {"LLM_PROVIDER": "studio"}):
            calls = []
            def once(_model, _prompt, _system, _timeout):
                calls.append(1)
                if len(calls) == 1:
                    raise FakeServiceError(503)
                return _response("qa")
            result = route(state, generate_fn=lambda prompt, system, **options: client.generate(
                prompt, system, request_fn=once, sleep_fn=lambda _delay: None, **options))
            checks.append(("transient once then llm", len(calls) == 2 and result["route_source"] == "llm"))

            calls.clear()
            def disconnected(_model, _prompt, _system, _timeout):
                calls.append(1)
                if len(calls) == 1:
                    raise ConnectionError("connection lost")
                return _response("qa")
            result = route(state, generate_fn=lambda prompt, system, **options: client.generate(
                prompt, system, request_fn=disconnected, sleep_fn=lambda _delay: None, **options))
            checks.append(("network disconnect then llm", len(calls) == 2 and result["route_source"] == "llm"))

            calls.clear()
            def bad(_model, _prompt, _system, _timeout):
                calls.append(1)
                raise FakeServiceError(400)
            result = route(new_state("공사비 알려줘"), generate_fn=lambda prompt, system, **options: client.generate(
                prompt, system, request_fn=bad, sleep_fn=lambda _delay: None, **options))
            checks.append(("400 no retry rule", len(calls) == 1 and result["route_source"] == "rule"))

            calls.clear()
            def twice(_model, _prompt, _system, _timeout):
                calls.append(1)
                raise FakeServiceError(503)
            result = route(new_state("공사비 알려줘"), generate_fn=lambda prompt, system, **options: client.generate(
                prompt, system, request_fn=twice, sleep_fn=lambda _delay: None, **options))
            checks.append(("two 503s rule", len(calls) == 2 and result["route_source"] == "rule"))

        factory_calls, requests = [], []
        key = ["router-key-1"]
        def fake_factory(provider, api_key):
            factory_calls.append((provider, api_key))
            def generate_content(**kwargs):
                requests.append(kwargs)
                return SimpleNamespace(text=_response("qa"))
            return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))

        with patch.dict(os.environ, {"LLM_PROVIDER": "studio"}), \
                patch.object(client, "_CLIENTS", {}), \
                patch.object(client, "_env_value", side_effect=lambda name: key[0] if name == "GEMINI_API_KEY" else None), \
                patch.object(client, "_create_client", side_effect=fake_factory):
            warmed = client.warmup_client()
            checks.append(("warmup creates without request", warmed and len(factory_calls) == 1 and not requests))
            first, second = route(state), route(state)
            checks.append(("cached client routes twice", len(factory_calls) == 1 and len(requests) == 2
                           and first["route_source"] == second["route_source"] == "llm"))
            key[0] = "router-key-2"
            changed = route(state)
            checks.append(("changed key creates client", len(factory_calls) == 2
                           and factory_calls[-1] == ("studio", key[0]) and changed["route_source"] == "llm"))
            with ThreadPoolExecutor(max_workers=4) as pool:
                shared = list(pool.map(lambda _: client._get_client("vertex", "concurrent-key"), range(8)))
            checks.append(("concurrent first calls create once", len(factory_calls) == 3
                           and all(item is shared[0] for item in shared)))

        with patch.dict(os.environ, {"LLM_PROVIDER": "studio"}), \
                patch.object(client, "_CLIENTS", {}), \
                patch.object(client, "_env_value", return_value="fake-secret"), \
                patch.object(client, "_create_client", side_effect=RuntimeError("fake-secret failed")):
            try:
                client.warmup_client()
            except client.LLMUnavailable as exc:
                checks.append(("failed warmup is sanitized and not cached",
                               "fake-secret" not in str(exc) and not client._CLIENTS))
            else:
                checks.append(("failed warmup is sanitized and not cached", False))

        with patch.object(client, "provider_name", side_effect=ValueError("invalid config")):
            try:
                client.warmup_client()
            except client.LLMUnavailable:
                checks.append(("invalid warmup config becomes unavailable", True))
            else:
                checks.append(("invalid warmup config becomes unavailable", False))

        now, requests = [0.0], []
        def fake_sleep(seconds):
            now[0] += seconds
        def slow_factory(provider, api_key):
            fake_sleep(3.1)
            return fake_factory(provider, api_key)
        with patch.dict(os.environ, {"LLM_PROVIDER": "studio"}), \
                patch.object(client, "_CLIENTS", {}), \
                patch.object(client, "_env_value", return_value="slow-key"), \
                patch.object(client, "_create_client", side_effect=slow_factory):
            slow = route(state, generate_fn=lambda prompt, system, **options: client.generate(
                prompt, system, clock_fn=lambda: now[0], **options))
        checks.append(("client creation over budget skips request and uses rule",
                       slow["route_source"] == "rule" and not requests))

        now, requests = [0.0], []
        def setup_factory(provider, api_key):
            fake_sleep(1.0)
            return fake_factory(provider, api_key)
        with patch.dict(os.environ, {"LLM_PROVIDER": "studio"}), \
                patch.object(client, "_CLIENTS", {}), \
                patch.object(client, "_env_value", return_value="setup-key"), \
                patch.object(client, "_create_client", side_effect=setup_factory):
            remaining = route(state, generate_fn=lambda prompt, system, **options: client.generate(
                prompt, system, clock_fn=lambda: now[0], **options))
        checks.append(("request receives remaining total budget", remaining["route_source"] == "llm"
                       and requests[0]["config"].http_options.timeout == 2000))

        with patch("backend.agent.graph.retrieve", return_value={"hits": [], "search_info": {}}), \
                patch("backend.agent.graph.select", side_effect=AssertionError("select called")), \
                patch("backend.agent.graph.compose", return_value={"answer": "근거 안내"}), \
                patch.object(client, "generate", return_value=_response("qa")):
            graph = build_graph()
            graph_state = graph.invoke(new_state("품은 몇 인이야?"), {"configurable": {"thread_id": "router-qa"}})
        checks.append(("qa answered without select", graph_state["status"] == "ANSWERED"
                       and graph_state["qa"]["not_found"]))

    with patch.dict(os.environ, {"AGENT_LLM": "off"}):
        with patch.object(client, "generate", side_effect=AssertionError("LLM called")):
            off = route(new_state("공사비 알려줘"))
        checks.append(("AGENT_LLM off uses rule", off["route"] == "estimate" and off["route_source"] == "rule"))
        # 규칙 대체도 router.md 기준: 물량만으로 견적이 아니고, 직전 견적의 재계산은 견적이다.
        # 46문항 밖 회귀 사례: 계산 대상, '다시'의 설명/재계산 구분, 업무 내 불명확 질문.
        cases = [("콘크리트 100㎥", None, "qa"),
                 ("레미콘 100㎥ 타설", None, "qa"),
                 ("방금 견적에서 할증 기준 다시 설명해줘", "estimate", "qa"),
                 ("콘크리트 타설 1㎥ 필요 인원 계산해줘", None, "qa"),
                 ("콘크리트 타설 1세제곱미터 품셈 알려줘", None, "qa"),
                 ("펌프차 붐 길이는 어떤 기준으로 골라?", "estimate", "qa"),
                 ("콘크리트 타설 1㎥ 비용 계산해줘", None, "estimate"),
                 ("옹벽 150㎥ 타설 공사비 계산해줘", None, "estimate"),
                 ("물량 300㎥로 바꿔서 다시 계산해줘", "estimate", "estimate"),
                 ("공사 기간 12개월로 해줘", "estimate", "estimate"),
                 ("레미콘 단가 9만원으로 다시 계산해줘", "estimate", "estimate"),
                 ("인력타설로 바꿔서 다시 해줘", "estimate", "estimate"),
                 ("오늘 현장 날씨 어때?", None, "out_of_scope")]
        for question, previous_route, label in cases:
            case_state = new_state(question)
            if previous_route:
                case_state["previous_context"] = {"previous_route": previous_route}
            checks.append((f"rule {label}: {question}", route(case_state)["route"] == label))
        testset = [json.loads(line) for line in
                   (ROOT / "evals/router_testset.jsonl").read_text(encoding="utf-8").splitlines() if line]
        rule_correct = sum(route({**new_state(case["q"]), "previous_context": case.get("context") or {}})["route"]
                           == case["label"] for case in testset)
        checks.append(("rule testset accuracy >= 90%", rule_correct / len(testset) >= 0.9))
        with patch.object(client, "_create_client", side_effect=AssertionError("client created")):
            checks.append(("AGENT_LLM off skips warmup", client.warmup_client() is False))

    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"통과 {sum(ok for _, ok in checks)} / 전체 {len(checks)}")
    return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
