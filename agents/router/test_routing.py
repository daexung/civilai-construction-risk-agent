"""
§13 라우팅 표 기반 라우팅 정확도 테스트.

실행:
  # 모킹 단위 테스트 (LLM 불필요)
  python test_routing.py --unit

  # 실제 LLM 통합 테스트 (AWS Bedrock 필요)
  python test_routing.py --integration

  # 전체 (기본)
  python test_routing.py
"""
import sys
import os
import argparse
import json
import unittest
from unittest.mock import patch

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..', '..'))
for p in [_HERE, os.path.join(_HERE, 'nodes'), _ROOT]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ── §13 라우팅 기대표 ────────────────────────────────────────────────

ROUTING_TABLE = [
    {
        "id": "R-01",
        "query": "옥상 우레탄 방수 200㎡ 추가, 자재비+인건비 정리",
        "expected_intent": "REPORT",
        "expected_domains_superset": {"material", "labor_cost"},
        "forbidden_domains": set(),
        "note": "material + labor_cost REPORT",
    },
    {
        "id": "R-02",
        "query": "서울 마포구 이번 주 콘크리트 타설 우천 리스크+추가비용",
        "expected_intent": "REPORT",
        "expected_domains_superset": {"weather"},
        "forbidden_domains": {"labor_cost", "material", "equipment"},
        "expected_missing_for_cost_nonempty": True,
        "note": "Partial REPORT: weather 분석 가능, 타설 물량 없어 비용 미실행. "
                "missing_for_cost 비어있지 않아야 하고 비용 agent는 domains에 없어야 함.",
    },
    {
        "id": "R-03",
        "query": "오늘 날씨 기준 작업 가능할까?",
        "expected_intent": "REPORT",
        "expected_domains_superset": {"weather"},
        "forbidden_domains": {"labor_cost", "material", "equipment"},
        "note": "날씨 단독 — 비용 agent 금지",
    },
    {
        "id": "R-04",
        "query": "철골 세우기 품셈 기준 알려줘",
        "expected_intent": "LOOKUP",
        "expected_domains_superset": set(),
        "forbidden_domains": set(),
        "expected_lookup_domain": "standard_spec",
        "note": "표준품셈 LOOKUP",
    },
    {
        "id": "R-05",
        "query": "보통인부 노임단가 알려줘",
        "expected_intent": "LOOKUP",
        "expected_domains_superset": set(),
        "forbidden_domains": set(),
        "expected_lookup_domain": "labor",
        "note": "노임단가 DB LOOKUP",
    },
    {
        "id": "R-06",
        "query": "철근 자재비 알려줘",
        "expected_intent": "LOOKUP",
        "expected_domains_superset": set(),
        "forbidden_domains": set(),
        "expected_lookup_domain": "material",
        "note": "자재비 DB LOOKUP",
    },
    {
        "id": "R-07",
        "query": "콘크리트공사 품셈 기준 설명해줘",
        "expected_intent": "LOOKUP",
        "expected_domains_superset": set(),
        "forbidden_domains": set(),
        "expected_lookup_domain": "standard_spec",
        "note": "표준품셈 LOOKUP",
    },
    {
        "id": "R-08",
        "query": "장비 대기비는 어떤 경우 청구?",
        "expected_intents": {"LOOKUP", "CHAT"},
        "expected_domains_superset": set(),
        "forbidden_domains": set(),
        "note": "LOOKUP 또는 CHAT 모두 허용",
    },
    {
        "id": "R-09",
        "query": "표준품셈이 뭐야?",
        "expected_intent": "CHAT",
        "expected_domains_superset": set(),
        "forbidden_domains": set(),
        "note": "개념 설명 CHAT",
    },
    {
        "id": "R-10",
        "query": "어벤져스 줄거리 요약해줘",
        "expected_intent": "OUT_OF_DOMAIN",
        "expected_domains_superset": set(),
        "forbidden_domains": set(),
        "note": "도메인 밖 → redirect",
    },
    {
        "id": "R-11",
        "query": "서울 문래동에서 이번 주 콘크리트 타설 공정이 예정되어 있습니다. 비로 인해 작업이 1일 지연될 경우, 펌프카 장비 대기비와 공정지연 추가비용을 산정해 주세요.",
        "expected_intent": "REPORT",
        "expected_domains_superset": {"equipment"},
        "forbidden_domains": set(),
        "note": "장비 대기비 REPORT — equipment 필수, missing_for_cost 없어야 함",
    },
]


# ── 단위 테스트: classify_question을 mock하고 라우터 로직만 검증 ────────

class TestRoutingLogicUnit(unittest.TestCase):
    """mock classify_question → router_node Command 검증."""

    def _run_classify_with_llm_plan(self, query: str, plan: dict) -> dict:
        """Mock the Bedrock client so classify_question post-processing actually runs."""
        from router import classify_question

        class _Body:
            def read(self):
                return json.dumps(
                    {"content": [{"text": json.dumps(plan, ensure_ascii=False)}]},
                    ensure_ascii=False,
                ).encode("utf-8")

        with patch("router._bedrock.invoke_model", return_value={"body": _Body()}):
            return classify_question(query)

    def _run_router(self, mock_plan: dict) -> dict:
        """classify_question을 mock해서 router_node를 호출하고 Command를 반환."""
        from langchain_core.messages import HumanMessage
        from nodes.router_node import router_node

        state = {
            "messages": [HumanMessage(content="테스트 질문")],
            "project_id": "PJT-TEST",
        }

        with patch("nodes.router_node.classify_question", return_value=mock_plan):
            cmd = router_node(state)
        return cmd

    def _assert_goto_not_cost_agent(self, cmd, case_id: str):
        goto = cmd.goto
        if isinstance(goto, list):
            for item in goto:
                agent = getattr(item, 'node', str(item))
                self.assertNotIn(
                    agent, {"equipment", "material", "labor_cost"},
                    f"{case_id}: 비용 agent가 GOTO에 포함돼 있음: {agent}",
                )

    def test_out_of_domain(self):
        from langgraph.graph import END
        cmd = self._run_router({
            "intent": "OUT_OF_DOMAIN",
            "domains": [],
            "lookup_domain": "unknown",
            "reason": "영화 질문",
        })
        self.assertEqual(cmd.goto, END, "OUT_OF_DOMAIN은 END로 가야 함")
        self.assertIn("final_response", cmd.update)

    def test_chat(self):
        cmd = self._run_router({
            "intent": "CHAT",
            "domains": [],
            "lookup_domain": "unknown",
            "reason": "개념 설명",
        })
        self.assertEqual(cmd.goto, "synthesize")
        self.assertEqual(cmd.update.get("answer_type"), "CHAT")

    def test_lookup_standard_spec(self):
        with patch("nodes.router_node._search_standard_spec_for_rag", return_value={"status": "success"}):
            cmd = self._run_router({
                "intent": "LOOKUP",
                "domains": [],
                "lookup_domain": "standard_spec",
                "reason": "품셈 조회",
            })
        self.assertEqual(cmd.goto, "synthesize")
        self.assertEqual(cmd.update.get("answer_type"), "RAG_QA")
        self.assertIn("rag_result", cmd.update)

    def test_lookup_labor(self):
        with patch("nodes.router_node._lookup_labor_price", return_value={"status": "success"}):
            cmd = self._run_router({
                "intent": "LOOKUP",
                "domains": [],
                "lookup_domain": "labor",
                "reason": "노임단가 조회",
            })
        self.assertEqual(cmd.goto, "synthesize")
        self.assertEqual(cmd.update.get("answer_type"), "RAG_QA")

    def test_lookup_material(self):
        with patch("nodes.router_node._lookup_material_price", return_value={"status": "success"}):
            cmd = self._run_router({
                "intent": "LOOKUP",
                "domains": [],
                "lookup_domain": "material",
                "reason": "자재비 조회",
            })
        self.assertEqual(cmd.goto, "synthesize")
        self.assertEqual(cmd.update.get("answer_type"), "RAG_QA")

    def test_clarify(self):
        cmd = self._run_router({
            "intent": "CLARIFY",
            "domains": [],
            "lookup_domain": "unknown",
            "reason": "입력 부족",
        })
        self.assertEqual(cmd.goto, "synthesize")
        self.assertEqual(cmd.update.get("answer_type"), "MISSING_INFO")

    def test_report_weather_only(self):
        """R-03: 날씨 단독 → extractor로 가고 target_agents는 빈 배열."""
        cmd = self._run_router({
            "intent": "REPORT",
            "domains": ["weather"],
            "lookup_domain": "unknown",
            "reason": "날씨 확인",
        })
        # router_node는 이제 모든 REPORT를 extractor로 보낸다 (extractor가 최종 라우팅 담당)
        self.assertEqual(cmd.goto, "extractor", "REPORT는 extractor 노드로 가야 함")
        self.assertEqual(cmd.update.get("target_agents"), [], "target_agents는 빈 배열이어야 함")
        self.assertEqual(cmd.update.get("needs_weather"), True)

    def test_report_weather_with_costs(self):
        """R-02: weather + cost domains → extractor로, target_agents에 비용 도메인 설정."""
        cmd = self._run_router({
            "intent": "REPORT",
            "domains": ["weather", "labor_cost", "equipment"],
            "lookup_domain": "unknown",
            "reason": "날씨+비용",
        })
        self.assertEqual(cmd.goto, "extractor", "REPORT는 extractor 노드로 가야 함")
        self.assertIn("labor_cost", cmd.update.get("target_agents", []))
        self.assertIn("equipment", cmd.update.get("target_agents", []))
        self.assertNotIn("weather", cmd.update.get("target_agents", []))

    def test_report_cost_only(self):
        """R-01: 비용 도메인만 → extractor로, target_agents에 비용 도메인 설정."""
        cmd = self._run_router({
            "intent": "REPORT",
            "domains": ["material", "labor_cost"],
            "lookup_domain": "unknown",
            "reason": "자재+인건비",
        })
        self.assertEqual(cmd.goto, "extractor", "REPORT는 extractor 노드로 가야 함")
        self.assertIn("material", cmd.update.get("target_agents", []))
        self.assertIn("labor_cost", cmd.update.get("target_agents", []))
        self.assertEqual(cmd.update.get("needs_weather"), False)

    def test_report_empty_domains_to_clarify(self):
        """REPORT인데 domains 비어 있으면 CLARIFY로 대체."""
        cmd = self._run_router({
            "intent": "REPORT",
            "domains": [],
            "lookup_domain": "unknown",
            "reason": "도메인 불분명",
        })
        self.assertEqual(cmd.goto, "synthesize")
        self.assertEqual(cmd.update.get("answer_type"), "MISSING_INFO")

    def test_no_default_fill_on_report(self):
        """핵심: REPORT + domains=[] 일 때 비용 agent가 자동으로 채워지지 않아야 함."""
        cmd = self._run_router({
            "intent": "REPORT",
            "domains": [],
            "lookup_domain": "unknown",
            "reason": "domains 비어있음",
        })
        target_agents = cmd.update.get("target_agents", [])
        self.assertEqual(target_agents, [], f"default-fill 금지 위반: target_agents={target_agents}")

    def test_no_default_fill_weather_no_cost(self):
        """핵심: weather 단독일 때 target_agents에 equipment/labor_cost가 자동 추가되면 안 됨."""
        cmd = self._run_router({
            "intent": "REPORT",
            "domains": ["weather"],
            "lookup_domain": "unknown",
            "reason": "날씨 단독",
        })
        target_agents = cmd.update.get("target_agents", [])
        for forbidden in ("equipment", "labor_cost", "material"):
            self.assertNotIn(
                forbidden, target_agents,
                f"default-fill 금지 위반: target_agents에 {forbidden}가 추가됨",
            )

    def test_classify_postprocess_does_not_add_weather(self):
        """LLM 후처리: 날씨 키워드가 있어도 weather를 자동 주입하지 않는다."""
        result = self._run_classify_with_llm_plan(
            "비 예보 있는데 작업 가능?",
            {
                "intent": "REPORT",
                "domains": ["labor_cost"],
                "lookup_domain": "unknown",
                "missing_for_cost": [],
                "reason": "LLM returned cost only",
            },
        )
        self.assertEqual(result["intent"], "REPORT")
        self.assertNotIn("weather", result.get("domains", []))
        self.assertEqual(result.get("domains"), ["labor_cost"])

    def test_classify_postprocess_removes_explicitly_excluded_weather(self):
        """LLM 후처리: 사용자가 날씨를 빼라고 하면 weather를 제거한다."""
        result = self._run_classify_with_llm_plan(
            "날씨 빼고 인건비만",
            {
                "intent": "REPORT",
                "domains": ["weather", "labor_cost"],
                "lookup_domain": "unknown",
                "missing_for_cost": [],
                "reason": "LLM returned weather and labor",
            },
        )
        self.assertEqual(result["intent"], "REPORT")
        self.assertNotIn("weather", result.get("domains", []))
        self.assertEqual(result.get("domains"), ["labor_cost"])

    def test_quantity_material_lookup_is_corrected_to_report(self):
        """수량이 있는 자재 비용 질문은 LOOKUP이 아니라 material REPORT로 보정한다."""
        result = self._run_classify_with_llm_plan(
            "H 파일 철근 2ton 비용 자재 알려줘",
            {
                "intent": "LOOKUP",
                "domains": [],
                "lookup_domain": "material",
                "missing_for_cost": [],
                "reason": "LLM returned material lookup",
            },
        )
        self.assertEqual(result["intent"], "REPORT")
        self.assertEqual(result.get("domains"), ["material"])
        self.assertEqual(result.get("lookup_domain"), "unknown")
        self.assertEqual(result.get("missing_for_cost"), [])

    def test_material_lookup_prefers_spaced_h_file(self):
        """LOOKUP 자재명 추출 시 'H 파일'은 철근보다 H파일을 우선한다."""
        from nodes.router_node import _extract_material_name

        self.assertEqual(_extract_material_name("H 파일 철근 단가 알려줘"), "H파일")

    def test_aggregator_weather_summary_from_response_json(self):
        from nodes.aggregator_node import aggregator_node

        weather_response = json.dumps({
            "site": {"site_name": "마포 현장"},
            "work": {"work_type": "CONCRETE_POURING"},
            "summary": {
                "max_pop_pct": 70,
                "total_pcp_mm": 12.5,
                "min_tmp_c": 4.0,
                "max_wsd_mps": 8.1,
                "has_precipitation": True,
            },
            "forecast": {
                "source": "KMA",
                "base_datetime": "2026-06-21T09:00:00+09:00",
            },
            "risk_result": {"risk_level": "HIGH"},
            "warnings": ["No forecasts for one requested slot"],
        }, ensure_ascii=False)

        result = aggregator_node({"weather_response": weather_response})["aggregated_result"]
        self.assertEqual(result["weather_summary"]["site_name"], "마포 현장")
        self.assertEqual(result["weather_summary"]["work_type"], "CONCRETE_POURING")
        self.assertEqual(result["weather_summary"]["max_pop_pct"], 70)
        self.assertEqual(result["weather_summary"]["total_pcp_mm"], 12.5)
        self.assertEqual(result["weather_summary"]["min_tmp_c"], 4.0)
        self.assertEqual(result["weather_summary"]["max_wsd_mps"], 8.1)
        self.assertIs(result["weather_summary"]["has_precipitation"], True)
        self.assertEqual(result["weather_summary"]["forecast_source"], "KMA")
        self.assertEqual(result["weather_summary"]["base_datetime"], "2026-06-21T09:00:00+09:00")
        self.assertIn("No forecasts", result["weather_summary"]["no_forecast_warning"])

    def test_aggregator_weather_summary_from_result_dict(self):
        from nodes.aggregator_node import aggregator_node

        result = aggregator_node({
            "weather_result": {
                "site": {"site_name": "dict 현장"},
                "work": {"work_type": "WATERPROOFING"},
                "summary": {"has_precipitation": False},
                "forecast": {"source": "KMA"},
            }
        })["aggregated_result"]

        self.assertEqual(result["weather_summary"]["site_name"], "dict 현장")
        self.assertEqual(result["weather_summary"]["work_type"], "WATERPROOFING")
        self.assertIs(result["weather_summary"]["has_precipitation"], False)
        self.assertEqual(result["weather_summary"]["forecast_source"], "KMA")

    def test_aggregator_weather_summary_omitted_on_bad_or_missing_json(self):
        from nodes.aggregator_node import aggregator_node

        bad_result = aggregator_node({"weather_response": "{not json"})["aggregated_result"]
        missing_result = aggregator_node({})["aggregated_result"]

        self.assertNotIn("weather_summary", bad_result)
        self.assertNotIn("weather_summary", missing_result)


# ── 통합 테스트: 실제 classify_question(LLM) 호출 ─────────────────────

class TestRoutingIntegration(unittest.TestCase):
    """실제 LLM을 호출해서 §13 라우팅 표 전 케이스를 검증."""

    @classmethod
    def setUpClass(cls):
        from router import classify_question
        cls.classify = staticmethod(classify_question)

    def _check_case(self, case: dict):
        result = self.__class__.classify(case["query"])
        intent = result["intent"]
        domains = set(result.get("domains") or [])
        lookup_domain = result.get("lookup_domain", "unknown")

        case_id = case["id"]
        note = case["note"]

        # intent 검증
        if "expected_intents" in case:
            self.assertIn(
                intent, case["expected_intents"],
                f"{case_id} [{note}]: intent={intent!r}, 허용={case['expected_intents']}",
            )
        elif "expected_intent" in case:
            self.assertEqual(
                intent, case["expected_intent"],
                f"{case_id} [{note}]: intent={intent!r}, 기대={case['expected_intent']!r}",
            )

        # 필수 도메인 포함 여부
        for d in case.get("expected_domains_superset", set()):
            self.assertIn(
                d, domains,
                f"{case_id} [{note}]: 필수 domain={d!r}가 누락. domains={domains}",
            )

        # 금지 도메인 미포함 여부
        for d in case.get("forbidden_domains", set()):
            self.assertNotIn(
                d, domains,
                f"{case_id} [{note}]: 금지 domain={d!r}가 포함됨. domains={domains}",
            )

        # lookup_domain 검증
        if "expected_lookup_domain" in case:
            self.assertEqual(
                lookup_domain, case["expected_lookup_domain"],
                f"{case_id} [{note}]: lookup_domain={lookup_domain!r}, "
                f"기대={case['expected_lookup_domain']!r}",
            )

        # missing_for_cost 비어있지 않아야 하는 케이스
        if case.get("expected_missing_for_cost_nonempty"):
            missing = result.get("missing_for_cost") or []
            self.assertTrue(
                len(missing) > 0,
                f"{case_id} [{note}]: missing_for_cost가 비어있음 (비어있지 않아야 함)",
            )

        print(
            f"  ✅ {case_id} [{note[:50]}]: intent={intent}, "
            f"domains={sorted(domains)}, missing_for_cost={result.get('missing_for_cost', [])}"
        )
        return result

    def test_r01_material_labor_report(self):
        self._check_case(ROUTING_TABLE[0])

    def test_r02_partial_report_weather_only(self):
        self._check_case(ROUTING_TABLE[1])

    def test_r03_weather_only_no_cost_agents(self):
        self._check_case(ROUTING_TABLE[2])

    def test_r04_lookup_standard_spec(self):
        self._check_case(ROUTING_TABLE[3])

    def test_r05_lookup_labor_price(self):
        self._check_case(ROUTING_TABLE[4])

    def test_r06_lookup_material_price(self):
        self._check_case(ROUTING_TABLE[5])

    def test_r07_lookup_concrete_spec(self):
        self._check_case(ROUTING_TABLE[6])

    def test_r08_equipment_standby_chat_or_lookup(self):
        self._check_case(ROUTING_TABLE[7])

    def test_r09_chat_concept(self):
        self._check_case(ROUTING_TABLE[8])

    def test_r10_out_of_domain(self):
        self._check_case(ROUTING_TABLE[9])

    def test_r11_equipment_standby_report(self):
        self._check_case(ROUTING_TABLE[10])


# ── 단위 테스트: router_node 안전망 보정 로직 검증 ─────────────────────────

class TestRouterNodeSafetyNet(unittest.TestCase):
    """_postprocess_equipment_and_duration 보정 로직 단위 검증."""

    def _run_router_with_query(self, query: str, mock_plan: dict) -> object:
        from langchain_core.messages import HumanMessage
        from nodes.router_node import router_node

        state = {
            "messages": [HumanMessage(content=query)],
            "project_id": "PJT-TEST",
        }
        with patch("nodes.router_node.classify_question", return_value=mock_plan):
            return router_node(state)

    def test_equipment_keyword_forces_equipment_domain(self):
        """장비 키워드가 있으면 LLM이 equipment를 빼도 다시 추가한다."""
        cmd = self._run_router_with_query(
            "펌프카 장비 대기비 1일 지연",
            {
                "intent": "REPORT",
                "domains": ["weather"],
                "lookup_domain": "unknown",
                "missing_for_cost": ["duration"],
                "reason": "LLM이 duration 없다고 판단해 비용 도메인 제외",
            },
        )
        self.assertIn("equipment", cmd.update.get("target_agents", []),
                      "equipment 키워드 → target_agents에 equipment 포함")

    def test_explicit_delay_day_removes_duration_missing(self):
        """'1일 지연' 표현이 있으면 duration missing이 제거된다."""
        cmd = self._run_router_with_query(
            "펌프카 1일 지연 대기비 산정",
            {
                "intent": "REPORT",
                "domains": ["weather"],
                "lookup_domain": "unknown",
                "missing_for_cost": ["duration"],
                "reason": "duration 없다고 판단",
            },
        )
        missing = cmd.update.get("missing_for_cost", [])
        self.assertNotIn("duration", missing,
                         "명시적 지연일 → missing_for_cost에서 duration 제거")

    def test_r11_full_query_safety_net(self):
        """R-11 실제 질문: LLM이 domains=['weather'], missing=['duration'] 반환해도 equipment 포함."""
        query = (
            "서울 문래동에서 이번 주 콘크리트 타설 공정이 예정되어 있습니다. "
            "비로 인해 작업이 1일 지연될 경우, 펌프카 장비 대기비와 공정지연 추가비용을 산정해 주세요. "
            "펌프카는 25m³, 콘크리트는 200m³입니다."
        )
        cmd = self._run_router_with_query(
            query,
            {
                "intent": "REPORT",
                "domains": ["weather"],
                "lookup_domain": "unknown",
                "missing_for_cost": ["duration"],
                "reason": "실제 로그와 동일한 LLM 응답",
            },
        )
        target_agents = cmd.update.get("target_agents", [])
        missing = cmd.update.get("missing_for_cost", [])
        self.assertIn("equipment", target_agents,
                      f"target_agents에 equipment 없음: {target_agents}")
        self.assertNotIn("duration", missing,
                         f"missing_for_cost에 duration 잔존: {missing}")

    def test_weather_only_query_no_equipment_added(self):
        """장비 키워드 없는 날씨 전용 질문은 equipment가 추가되지 않는다."""
        cmd = self._run_router_with_query(
            "서울 문래동 이번 주 작업 가능해?",
            {
                "intent": "REPORT",
                "domains": ["weather"],
                "lookup_domain": "unknown",
                "missing_for_cost": [],
                "reason": "날씨 단독",
            },
        )
        target_agents = cmd.update.get("target_agents", [])
        self.assertNotIn("equipment", target_agents,
                         f"날씨 전용 질문에 equipment 추가됨: {target_agents}")

    def test_existing_weather_no_cost_unaffected(self):
        """기존 weather-only 동작: equipment/labor_cost 자동 추가 금지 유지."""
        cmd = self._run_router_with_query(
            "오늘 날씨 기준 작업 가능할까?",
            {
                "intent": "REPORT",
                "domains": ["weather"],
                "lookup_domain": "unknown",
                "missing_for_cost": [],
                "reason": "날씨 단독",
            },
        )
        target_agents = cmd.update.get("target_agents", [])
        for forbidden in ("equipment", "labor_cost", "material"):
            self.assertNotIn(forbidden, target_agents,
                             f"날씨 전용 → {forbidden} 추가 금지 위반")


# ── 실행 진입점 ──────────────────────────────────────────────────────

def run_unit_tests():
    print("\n" + "="*60)
    print("단위 테스트 (mock classify_question)")
    print("="*60)
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestRoutingLogicUnit))
    suite.addTests(loader.loadTestsFromTestCase(TestRouterNodeSafetyNet))
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


def run_integration_tests():
    print("\n" + "="*60)
    print("통합 테스트 (실제 LLM)")
    print("="*60)
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestRoutingIntegration)
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", action="store_true", help="단위 테스트만 실행")
    parser.add_argument("--integration", action="store_true", help="통합 테스트만 실행")
    args = parser.parse_args()

    results = []
    if args.unit:
        results.append(run_unit_tests())
    elif args.integration:
        results.append(run_integration_tests())
    else:
        results.append(run_unit_tests())
        results.append(run_integration_tests())

    total_failures = sum(len(r.failures) + len(r.errors) for r in results)
    sys.exit(0 if total_failures == 0 else 1)
