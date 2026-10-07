"""AGENT_MODE=tools 비회원 대화를 API부터 Excel까지 검사한다(고정 후보 + 대본 LLM, 외부 호출 없음).

- 고정 후보: 검색 결과를 운영에서 나온 후보(6-1-4, 6-1-1, 1-6-2)로 고정한다. 실제 검색 대화는 check_dialogue_search.py.
- 대본 LLM: 행동(JSON)은 정해 둔 순서로, 응답 문장은 서버가 준 facts로 만든다. 값·근거 검증은 서버 그대로 거친다.
- "세제곱미터"는 대본도 사용자 문장 그대로의 근거를 보내므로, 서버 단위 파서가 읽지 못하면 실패한다.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
from contextlib import nullcontext
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

os.environ.update(AGENT_OFFLINE="1", AGENT_LLM="on", AGENT_MODE="tools")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

import backend.api.main as api_main  # noqa: E402
from backend.agent.estimate import dialogue, reply_check, tools  # noqa: E402
from backend.agent.nodes.compute import CALCULATORS  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.agent.tools.llm import client  # noqa: E402
from backend.api import dialogue_service  # noqa: E402

HITS = [{"rank": rank, "section_no": no, "division": division, "section": f"{no} {title}", "page": page,
         "table_id": None, "text": title, "chunk_id": f"fixed-{rank}"}
        for rank, (no, division, title, page) in enumerate([("6-1-4", "공통", "콘크리트 펌프차 타설", 186),
                                                             ("6-1-1", "공통", "레디믹스트콘크리트 타설", 185),
                                                             ("1-6-2", "토목", "표층 인력포설", 120)], 1)]
PUMP = {"pump_size": "32m", "structure": "철근", "slump_band": "15㎝", "facility_type": "Type-Ⅱ",
        "site_type": "Type-Ⅱ", "placement": "붐", "vibrator_used": True, "reset_status": "없음"}
SECRET = "offline-dialogue-session-" + "x" * 32


class ScriptedLLM:
    """행동은 queue 순서대로, 응답 문장은 facts로 만든다. calls에 호출 기록을 남긴다."""

    def __init__(self):
        self.actions: list[dict] = []
        self.calls: list[str] = []
        self.reply_override = None
        self.reply_raise = False

    def __call__(self, prompt, system, response_schema=None, **kwargs):
        data = json.loads(prompt)
        if response_schema is dialogue.REPLY_SCHEMA:
            self.calls.append("reply")
            if self.reply_raise:
                raise client.LLMUnavailable("scripted reply failure", attempts=1)
            if self.reply_override:
                return json.dumps(self.reply_override(data), ensure_ascii=False)
            facts = {fact["id"]: fact for fact in data["facts"]}
            fact = facts.get("contract_amount") or facts.get("line0")
            if not fact:
                return json.dumps({"text": "아래 질문을 확인해 주세요."}, ensure_ascii=False)
            phrase = f"{fact['item']} {reply_check.display(fact['value'])}{fact['unit']}"
            return json.dumps({"text": f"{phrase}입니다."},
                              ensure_ascii=False)
        self.calls.append("agent")
        action = self.actions.pop(0) if self.actions else {"action": "reply", "reason": "끝"}
        if "__raise__" in action:
            raise client.LLMUnavailable("scripted agent failure", attempts=1)
        if "__raw__" in action:
            return action["__raw__"]
        return json.dumps(action, ensure_ascii=False)

    def plan(self, *tools_and_args):
        self.actions = [{"action": "call_tool", "tool": name, "args": args, "reason": "대본"} for name, args in tools_and_args]


def main() -> int:
    checks = []
    llm = ScriptedLLM()
    consumed = []
    with patch("backend.api.usage_limits.processing", return_value=nullcontext((None, "fixture", False))), \
            patch("backend.api.usage_limits.consume", side_effect=lambda quota, *request: consumed.append(1) or {}), \
            patch.object(tools, "retrieve", return_value={"hits": HITS}), \
            patch.object(client, "generate", llm), patch.object(api_main, "warmup_client", return_value=True), \
            TestClient(api_main.app, headers={"X-Guest-Session": SECRET}) as http:
        def post(body: dict, expect: int = 200) -> dict:
            result = http.post("/api/chat", json=body)
            assert result.status_code == expect, (result.status_code, result.text[:500])
            return result.json()

        def answer(previous: dict, values: dict, refs: dict | None = None) -> dict:
            refs = refs or {q["name"]: q["ref"] for q in previous["questions"] if q["name"] in values}
            return post({"thread_id": previous["thread_id"], "answers": values, "refs": refs})

        def stored(thread_id: str) -> dict:
            return dialogue.load(dialogue.build_dialogue_graph(api_main.GRAPH.checkpointer), thread_id)

        # 1. 품셈 질문: 물량은 사용자 문장 그대로의 근거("1세제곱미터"), 공종만 묻는다
        llm.plan(("find_work", {}), ("set_conditions", {"quantity": {"value": "1", "unit": "㎥", "evidence": "1세제곱미터"}}),
                 ("compute_labor", {}))
        t1 = post({"message": "콘크리트 타설 1세제곱미터 품셈 알려줘"})
        thread = t1["thread_id"]
        item = lambda: tools._item(stored(thread)["session"])  # noqa: E731
        checks.append(("D1 공종만 질문, 물량 1(세제곱미터 근거를 서버가 읽음)",
                       [q["name"] for q in t1["questions"]] == ["work"] and item()["quantity"]["value"] == "1"
                       and all(q.get("ref") for q in t1["questions"])))

        # 2. 공종 → 품 조건만(가격 조건·물량 없음) → 품과 근거
        llm.plan(("compute_labor", {}))
        t2 = answer(t1, {"work": "6-1-4"})
        checks.append(("D2 품 조건만 질문(관급/사급·물량 없음)", set(q["name"] for q in t2["questions"]) == set(PUMP)))
        llm.plan(("compute_labor", {}))
        t2b = answer(t2, PUMP)
        direct = CALCULATORS["adjusted_daily_crew"](next(s for s in load_specs().values() if s["section_no"] == "6-1-4"),
                                                    {**PUMP, "volume": "1"}, labor_only=True)
        checks.append(("D2 1㎥ 품 결과(계산기와 같음)·원가 없음·LLM 설명 검증 통과",
                       t2b["status"] == "COMPUTED" and item()["computed_result"]["unit_lines"] == direct["unit_lines"]
                       and t2b["statement"] is None and not t2b["estimate_current"]
                       and t2b["answer_source"] == "llm" and "콘크리트공" in t2b["answer"]))

        # 3. 같은 조건으로 100세제곱미터 비용: 가격 조건만 묻는다
        llm.plan(("set_conditions", {"quantity": {"value": "100", "unit": "㎥", "evidence": "100세제곱미터"}}),
                 ("estimate_cost", {}))
        t3 = post({"thread_id": thread, "message": "같은 조건으로 100세제곱미터 비용 계산해줘"})
        export_pending = http.get(f"/api/export/{thread}.xlsx").status_code
        checks.append(("D3 가격 조건만 질문, 품 조건 유지, 물량 100, Excel은 아직 404",
                       [q["name"] for q in t3["questions"]] == ["concrete_supply"]
                       and item()["quantity"]["value"] == "100"
                       and all(item()["conditions"].get(name) is not None for name in PUMP) and export_pending == 404))

        # 23. 대기 질문 보존: 관급/사급 질문 대기 중 조회(단위당 인원·근거·원문 검색)는 질문과 ref를 그대로 둔다.
        #     아래 D4가 t3 카드(원래 ref)로 답해 정상 반영되는지까지 본다.
        card = [(q["name"], q["ref"]) for q in t3["questions"]]
        kept_cards = []
        llm.plan(("compute_labor", {}))
        kept_cards.append(post({"thread_id": thread, "message": "콘크리트공은 1세제곱미터당 몇 명이야?"}))
        llm.plan(("explain_basis", {}))
        kept_cards.append(post({"thread_id": thread, "message": "할증 기준은 어디서 나와?"}))
        llm.plan(("search_standard", {"query": "펌프차 타설 할증"}))
        kept_cards.append(post({"thread_id": thread, "message": "펌프차 타설 할증 원문 찾아줘"}))
        with patch.dict(os.environ, {"AGENT_LLM": "off"}):  # 규칙 경로도 같다
            kept_cards.append(post({"thread_id": thread, "message": "콘크리트공은 1세제곱미터당 몇 명이야?"}))
            kept_cards.append(post({"thread_id": thread, "message": "할증 기준은 어디서 나와?"}))
        checks.append(("D23 대기 질문 중 조회(단위당 인원·근거·원문 검색, LLM·규칙)는 질문·ref 유지, 물량 그대로",
                       all([(q["name"], q["ref"]) for q in reply["questions"]] == card and reply["status"] == "MISSING_INFO"
                           for reply in kept_cards)
                       and [(q["field"], q["ref"]) for q in stored(thread)["pending"]] == card
                       and item()["quantity"]["value"] == "100"))

        # 4. 가격 조건 → 원가계산서(도구만으로 계산한 합계와 같음)
        llm.plan(("estimate_cost", {}))
        t4 = answer(t3, {"concrete_supply": "관급"})
        reference = tools.new_estimate("콘크리트 타설", None)
        tools.find_work(reference, hits=HITS)
        tools.set_conditions(reference, "", work="6-1-4", source="answer")
        tools.set_conditions(reference, "", values={k: {"value": v} for k, v in {**PUMP, "concrete_supply": "관급"}.items()},
                             source="answer")
        reference["basis_date"] = t4["basis_date"]
        tools.set_conditions(reference, "100㎥", quantity={"value": "100", "unit": "㎥", "evidence": "100㎥"})
        expected = tools.estimate_cost(reference)["data"]["statement"]["totals"]
        work_days_100 = Fraction(item()["computed_result"]["work_days"])
        checks.append(("D4 원가계산서 최신·합계가 서버 도구 계산과 같음(조회 뒤 원래 카드 ref로 답해도 반영)",
                       t4["status"] in ("OK", "PARTIAL") and t4["estimate_current"]
                       and "반영하지 않았어요" not in (t4["answer"] or "")
                       and t4["statement"]["totals"] == expected))

        # 6. 근거 질문: 조건·견적 유지
        llm.plan(("explain_basis", {}))
        t6 = post({"thread_id": thread, "message": "할증 기준은 어디서 나와?"})
        checks.append(("D6 근거 질문 뒤에도 조건·견적 유지(최신)",
                       t6["estimate_current"] and t6["statement"]["totals"] == t4["statement"]["totals"]
                       and item()["quantity"]["value"] == "100"))

        # 5. 물량 변경 → 재계산 → Excel(최신 합계와 같음)
        llm.plan(("set_conditions", {"quantity": {"value": "300", "unit": "㎥", "evidence": "300세제곱미터"}}),
                 ("estimate_cost", {}))
        t5 = post({"thread_id": thread, "message": "300세제곱미터로 바꿔줘"})
        workbook = load_workbook(io.BytesIO(http.get(f"/api/export/{thread}.xlsx").content), data_only=True)
        amount = t5["statement"]["totals"]["contract_amount"]
        cells = [cell.value for sheet in workbook for row in sheet.iter_rows() for cell in row]
        checks.append(("D5 물량 300 재계산, 금액 변경, Excel에 최신 도급액",
                       t5["estimate_current"] and amount != t4["statement"]["totals"]["contract_amount"]
                       and Fraction(item()["computed_result"]["work_days"]) == 3 * work_days_100
                       and amount in cells))

        # 7. 새로고침: 저장소(체크포인터)에서 새 그래프로 읽어 마지막 응답·최신 견적 복원
        fresh_graph = dialogue.build_dialogue_graph(api_main.GRAPH.checkpointer)
        restored = dialogue_service.restore(fresh_graph, thread)
        same = {k: v for k, v in restored.items() if k not in ("answer_id", "timing", "usage", "guest_session")} == \
               {k: v for k, v in t5.items() if k not in ("answer_id", "timing", "usage", "guest_session")}
        reloaded = dialogue.load(fresh_graph, thread)
        after_reload = load_workbook(io.BytesIO(http.get(f"/api/export/{thread}.xlsx").content), data_only=True)
        checks.append(("D7 저장소에서 새로 읽은 상태로 대화·최신 견적 복원, 이어서 Excel도 같은 금액",
                       same and restored["estimate_current"] and tools.current_estimate(reloaded["session"]) is not None
                       and amount in [c.value for s in after_reload for r in s.iter_rows() for c in r]))

        # 16. 조회 질문은 상태를 바꾸지 않는다(300㎥ 견적). '1세제곱미터당'은 단위당 기준이지 물량 변경이 아니다
        def snapshot() -> tuple:
            current = item()
            book = load_workbook(io.BytesIO(http.get(f"/api/export/{thread}.xlsx").content), data_only=True)
            return (current["quantity"]["value"], dict(current["conditions"]),
                    tools.current_estimate(stored(thread)["session"]) is not None,
                    amount in [c.value for s in book for r in s.iter_rows() for c in r])

        kept = ("300", dict(item()["conditions"]), True, True)
        lookup = "콘크리트공은 1세제곱미터당 몇 명이야?"
        with patch.dict(os.environ, {"AGENT_LLM": "off"}):
            rule_lookup = post({"thread_id": thread, "message": lookup})
        checks.append(("D16a 규칙 경로: 단위당 인원 질문은 물량·조건·최신 견적·Excel 금액 유지",
                       snapshot() == kept and stored(thread)["turn"]["tools"] == ["compute_labor"]
                       and "콘크리트공" in rule_lookup["answer"]))
        llm.actions = [{"__raise__": True}]
        failed_lookup = post({"thread_id": thread, "message": lookup})
        checks.append(("D16b LLM 첫 호출 실패 → 규칙 경로: 같은 결과",
                       snapshot() == kept and stored(thread)["turn"]["tools"] == ["compute_labor"]
                       and failed_lookup["answer"] == rule_lookup["answer"]))
        llm.plan(("set_conditions", {"quantity": {"value": "1", "unit": "㎥", "evidence": "1세제곱미터"}}), ("estimate_cost", {}))
        post({"thread_id": thread, "message": lookup})
        checks.append(("D16c LLM이 조회 질문에 set_conditions를 불러도 서버가 바꾸지 않음", snapshot() == kept))
        with patch.dict(os.environ, {"AGENT_LLM": "off"}):
            changed = post({"thread_id": thread, "message": "1세제곱미터로 바꿔줘"})
        checks.append(("D16d '1세제곱미터로 바꿔줘'는 물량 변경·재계산",
                       item()["quantity"]["value"] == "1" and changed["estimate_current"]
                       and changed["statement"]["totals"]["contract_amount"] != amount))
        llm.actions = [{"action": "call_tool", "tool": "set_conditions", "reason": "대본",
                        "args": {"quantity": {"value": "300", "unit": "㎥", "evidence": "300세제곱미터"}}},
                       {"__raise__": True}]
        post({"thread_id": thread, "message": "300세제곱미터로 바꿔줘"})
        checks.append(("D16e 도구 실행 뒤 LLM 실패: 적용한 결과를 규칙 경로로 다시 바꾸지 않음",
                       item()["quantity"]["value"] == "300" and stored(thread)["turn"]["tools"] == ["set_conditions"]))
        llm.plan(("estimate_cost", {}))
        post({"thread_id": thread, "message": "다시 계산해줘"})
        checks.append(("D16f 재계산 뒤 300㎥ 견적·Excel 금액 원래대로", snapshot() == kept))

        # 17. 거부 안내: 거부된 값(25m)은 '적용하지 않음'으로 설명할 때만 숫자 검증 통과
        llm.reply_override = lambda data: {"text": "25m는 지원하지 않아 기존 32m를 유지했어요."}
        llm.plan(("set_conditions", {"values": {"pump_size": {"value": "25m", "evidence": "25m"}}}))
        refused_ok = post({"thread_id": thread, "message": "펌프차 붐을 25m로 바꿔줘"})
        llm.reply_override = lambda data: {"text": "25m로 계산했어요."}
        llm.plan(("set_conditions", {"values": {"pump_size": {"value": "25m", "evidence": "25m"}}}))
        refused_bad = post({"thread_id": thread, "message": "펌프차 붐을 25m로 바꿔줘"})
        llm.reply_override = None
        checks.append(("D17 '25m는 지원하지 않아 32m 유지'는 통과, '25m로 계산'은 거부, 32m·견적 유지",
                       refused_ok["answer_source"] == "llm" and "32m를 유지" in refused_ok["answer"]
                       and refused_bad["answer_source"] == "template" and "25" in refused_bad["llm_info"]["rejected"]
                       and snapshot() == kept))

        # 18. 작업일수 표시: 정확값(30/13) 유지, 화면·답변은 '약 2.31'. 검증은 정확값과 그 반올림 결과만 허용
        def days_reply(text: str) -> dict:
            llm.reply_override = lambda data: {"text": text}
            llm.plan(("estimate_cost", {}))
            try:
                return post({"thread_id": thread, "message": "다시 계산해줘"})
            finally:
                llm.reply_override = None
        good_days = days_reply("작업일수 약 2.31일이에요.")
        bad_days = [days_reply(text)["answer_source"] for text in ("작업일수 약 2.32일이에요.", "작업일수 2.3일이에요.")]
        days_book = load_workbook(io.BytesIO(http.get(f"/api/export/{thread}.xlsx").content), data_only=True)
        days_cells = [c.value for s in days_book for r in s.iter_rows() for c in r]
        checks.append(("D18 작업일수 정확값 30/13 유지·화면 '약 2.31'·답변 2.31만 허용(2.32·2.3 거부)·Excel 계산값 그대로",
                       good_days["result"]["work_days"]["value"] == "30/13"
                       and good_days["result"]["work_days"]["display"] == "약 2.31"
                       and item()["computed_result"]["work_days"] == "30/13"
                       and good_days["answer_source"] == "llm" and bad_days == ["template", "template"]
                       and any(isinstance(v, float) and abs(v - 30 / 13) < 1e-12 for v in days_cells)
                       and snapshot() == kept))

        # 20. 실제 LLM 평가에서 본 순서: 같은 물량을 계산 뒤 한 번 더 보내도 최신 견적을 버리지 않는다
        same = {"quantity": {"value": "300", "unit": "㎥", "evidence": "300세제곱미터"}}
        llm.plan(("set_conditions", same), ("estimate_cost", {}), ("set_conditions", {**same, "values": None}))
        repeated = post({"thread_id": thread, "message": "300세제곱미터로 바꿔줘"})
        checks.append(("D20 같은 물량 재설정(계산 뒤 반복 호출)은 최신 견적·Excel 금액 유지",
                       repeated["estimate_current"] and stored(thread)["turn"]["tools"][-1] == "set_conditions"
                       and repeated["statement"]["totals"]["contract_amount"] == amount and snapshot() == kept))

        # 21. 실제 LLM 평가에서 거부됐던 맞는 문장: 기준 문서명·공종 번호는 서버 문자열이라 허용
        llm.reply_override = lambda data: {"text": "콘크리트공 0.0308인/㎥입니다. 일당 시공량 130㎥/일 기준입니다. 자세한 내용은 "
                                                   "2026 건설공사 표준품셈 공통부문 6-1-4 콘크리트 펌프차 타설을 참고하시기 바랍니다."}
        llm.plan(("compute_labor", {}))
        cited = post({"thread_id": thread, "message": lookup})
        llm.reply_override = None
        checks.append(("D21 기준 문서명(2026 건설공사 표준품셈)·공종 번호가 든 실제 문장은 통과, 견적 유지",
                       cited["answer_source"] == "llm" and snapshot() == kept))

        # 22. 실제 LLM 평가에서 거부됐던 맞는 문장: 인용의 표 소제목('2. 인력편성')·개정 연도가 든 절 제목은 허용
        llm.reply_override = lambda data: {"text": "콘크리트공 0.0308 인/㎥이 소요됩니다. 근거는 2026 건설공사 표준품셈 공통부문 "
                                                   "6-1-4 콘크리트 펌프차 타설의 2. 인력편성 표입니다."}
        llm.plan(("compute_labor", {}))
        table_named = post({"thread_id": thread, "message": lookup})
        llm.reply_override = lambda data: {"text": "할증 기준은 6-1-4 콘크리트 펌프차 타설('08, '09, '17, '22, '24, ‘25년 보완)에서 "
                                                   "확인할 수 있습니다."}
        llm.plan(("explain_basis", {}))
        section_named = post({"thread_id": thread, "message": "할증 기준은 어디서 나와?"})
        llm.reply_override = lambda data: {"text": "콘크리트공 4인이 필요합니다."}  # 인용 값(4)은 여전히 근거 없는 숫자
        llm.plan(("compute_labor", {}))
        cited_value = post({"thread_id": thread, "message": lookup})
        llm.reply_override = None
        checks.append(("D22 인용 소제목·절 제목(개정 연도)은 통과, 인용 속 값(4인)은 거부, 견적 유지",
                       table_named["answer_source"] == "llm" and section_named["answer_source"] == "llm"
                       and cited_value["answer_source"] == "template" and snapshot() == kept))

        # 19. 대기 질문의 문장 답은 조회 질문으로 막지 않는다('?'가 붙어도)
        def pending_flow(rule: bool, pump_text: str, volume_text: str) -> tuple:
            env = {"AGENT_LLM": "off"} if rule else {}
            with patch.dict(os.environ, env):
                llm.plan(("find_work", {}), ("compute_labor", {}))
                first = post({"message": "콘크리트 펌프차 타설 품 알려줘"})
                llm.plan(("compute_labor", {}))
                asked = answer(first, {"work": "6-1-4"})
                pending_thread = first["thread_id"]
                names = {q["name"] for q in asked["questions"]}
                llm.plan(("set_conditions", {"values": {"pump_size": {"value": "32m", "evidence": "32m"}}}), ("compute_labor", {}))
                post({"thread_id": pending_thread, "message": pump_text})
                llm.plan(("set_conditions", {"quantity": {"value": "100", "unit": "㎥", "evidence": "100세제곱미터"}}),
                         ("compute_labor", {}))
                post({"thread_id": pending_thread, "message": volume_text})
            current = tools._item(stored(pending_thread)["session"])
            return names, current["conditions"].get("pump_size"), (current.get("quantity") or {}).get("value")

        rule_plain = pending_flow(True, "32m야", "100세제곱미터야")
        rule_asked = pending_flow(True, "붐은 32m야?", "물량은 100세제곱미터야?")
        llm_asked = pending_flow(False, "붐은 32m야?", "물량은 100세제곱미터야?")
        checks.append(("D19 붐 길이·물량을 물은 뒤 '32m야'·'100세제곱미터야'(물음표 포함, 규칙·LLM)는 반영",
                       all("pump_size" in names and pump == "32m" and volume == "100"
                           for names, pump, volume in (rule_plain, rule_asked, llm_asked))))

        # 8. 오래된 답: 같은 필드·같은 질문이라도 예전 revision의 답은 적용하지 않는다
        llm.plan(("find_work", {}), ("set_conditions", {"work": "6-1-4"}), ("set_conditions", {
            "quantity": {"value": "10", "unit": "㎥", "evidence": "10세제곱미터"},
            "values": {name: {"value": value, "evidence": text} for name, (value, text) in {
                "pump_size": ("32m", "32m"), "structure": ("철근", "철근콘크리트"), "slump_band": ("15㎝", "15cm"),
                "placement": ("붐", "붐타설"), "vibrator_used": (True, "진동기 사용"), "reset_status": ("없음", "재셋팅 없음"),
            }.items()}}), ("estimate_cost", {}))
        s1 = post({"message": "철근콘크리트 펌프차 32m 붐타설 슬럼프 15cm 진동기 사용 재셋팅 없음 10세제곱미터 비용"})
        llm.plan(("estimate_cost", {}))
        s1b = answer(s1, {"facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ"})
        old_ref = {q["name"]: q["ref"] for q in s1b["questions"]}
        llm.plan(("set_conditions", {"quantity": {"value": "20", "unit": "㎥", "evidence": "20세제곱미터"}}), ("estimate_cost", {}))
        s2 = post({"thread_id": s1["thread_id"], "message": "같은 조건으로 20세제곱미터 비용"})
        new_ref = {q["name"]: q["ref"] for q in s2["questions"]}
        llm.plan(("estimate_cost", {}))
        stale = answer(s2, {"concrete_supply": "관급"}, refs=old_ref)
        llm.plan(("estimate_cost", {}))
        # 거부한 턴도 같은 질문을 새 revision으로 다시 낸다. 현재 질문은 바로 직전 응답의 ref다.
        fresh = answer(stale, {"concrete_supply": "관급"})
        checks.append(("D8 같은 필드라도 예전 질문(revision)의 답은 미적용, 현재 질문 답은 적용",
                       [q["name"] for q in s1b["questions"]] == ["concrete_supply"] == [q["name"] for q in s2["questions"]]
                       and old_ref != new_ref and stale["status"] == "MISSING_INFO" and "반영하지 않았어요" in stale["answer"]
                       and stale["questions"][0]["ref"] not in (old_ref["concrete_supply"], new_ref["concrete_supply"])
                       and fresh["estimate_current"]))

        # 24. 공종이 실제로 바뀌면 대기 질문을 다시 정하고, 예전 카드 ref의 답은 거부한다
        llm.plan(("find_work", {}), ("set_conditions", {"work": "6-1-4"}), ("set_conditions", {
            "quantity": {"value": "10", "unit": "㎥", "evidence": "10세제곱미터"}}), ("estimate_cost", {}))
        w1 = post({"message": "펌프차 콘크리트 타설 10세제곱미터 비용"})
        llm.plan(("estimate_cost", {}))
        w2 = answer(w1, {name: value for name, value in PUMP.items() if name in {q["name"] for q in w1["questions"]}})
        w2_ref = {q["name"]: q["ref"] for q in w2["questions"]}
        llm.plan(("set_conditions", {"work": "6-1-1"}), ("estimate_cost", {}))
        switched = post({"thread_id": w1["thread_id"], "message": "레디믹스트콘크리트 타설로 바꿔줘"})
        llm.plan(("estimate_cost", {}))
        old_card = answer(switched, {"concrete_supply": "관급"}, refs={"concrete_supply": w2_ref.get("concrete_supply")})
        checks.append(("D24 공종이 바뀐 뒤 예전 카드(ref)의 답은 거부",
                       "concrete_supply" in w2_ref and tools._item(stored(w1["thread_id"])["session"])["selection"]["section_no"] == "6-1-1"
                       and "반영하지 않았어요" in old_card["answer"]
                       and tools._item(stored(w1["thread_id"])["session"])["conditions"].get("concrete_supply") != "관급"))

        # 9. LLM이 근거 검증을 우회하지 못함: 근거와 다른 값, source 주입은 무시된다
        before = item()["quantity"]["value"]
        llm.plan(("set_conditions", {"quantity": {"value": "999", "unit": "㎥", "evidence": "500세제곱미터"},
                                     "source": "answer"}), ("set_conditions", {"values": {"concrete_supply": {"value": "사급"}},
                                                                                "source": "answer"}))
        bypass = post({"thread_id": thread, "message": "500세제곱미터면 어때?"})
        checks.append(("D9 근거와 다른 물량·근거 없는 값은 거부(LLM이 source 지정 불가)",
                       item()["quantity"]["value"] == before and item()["conditions"].get("concrete_supply") == "관급"
                       and bypass["estimate_current"]))

        # 10. 응답 문장 검증: 근거 없는 금액·단위 불일치면 LLM 문장을 버리고 템플릿
        llm.reply_override = lambda data: {"text": "도급액 1,000원입니다."}
        llm.plan(("estimate_cost", {}))
        wrong = post({"thread_id": thread, "message": "다시 계산해줘"})
        llm.reply_override = lambda data: {"text": "노무비가 많이 들어요 12,345원"}
        llm.plan(("estimate_cost", {}))
        unclaimed = post({"thread_id": thread, "message": "다시 계산해줘"})
        llm.reply_override = None
        checks.append(("D10 사실과 다른 숫자·근거 없는 숫자 문장은 템플릿으로 대체",
                       wrong["answer_source"] == "template" and "값 불일치" in wrong["llm_info"]["rejected"]
                       and unclaimed["answer_source"] == "template" and unclaimed["llm_info"]["rejected"]
                       and reply_check.display(str(t5["statement"]["totals"]["contract_amount"])) in wrong["answer"]))

        # 11. 예산: 도구 4회·LLM 시도 6회 상한
        llm.plan(*[("explain_basis", {})] * 10)
        capped = post({"thread_id": thread, "message": "근거를 계속 보여줘"})
        info = capped["llm_info"]
        checks.append(("D11 턴 예산(도구 ≤4, LLM 시도 ≤6) 안에서 끝남",
                       info["tool_calls"] <= 4 and info["llm_attempts"] <= 6 and capped["estimate_current"]))
        llm.actions = []

        # 12. 중복 요청: 같은 request_id는 한 번만 실행·차감, 다른 내용이면 409
        runs = []
        original_turn = dialogue.run_turn

        def slow_turn(*args, **kwargs):
            runs.append(1)
            time.sleep(0.3)
            return original_turn(*args, **kwargs)

        body = {"thread_id": thread, "message": "근거 보여줘", "request_id": "11111111-1111-4111-8111-111111111111"}
        consumed.clear()
        with patch.object(dialogue, "run_turn", slow_turn):
            llm.plan(("explain_basis", {}))
            results = []
            workers = [threading.Thread(target=lambda: results.append(http.post("/api/chat", json=body))) for _ in range(2)]
            [worker.start() for worker in workers]
            [worker.join() for worker in workers]
            again = http.post("/api/chat", json=body)
            conflict = http.post("/api/chat", json={**body, "message": "다른 내용"})
        answers = {result.json()["answer_id"] for result in [*results, again]}
        checks.append(("D12 동시·재전송 중복 요청은 실행 1회·차감 1회·같은 응답, 다른 내용은 409",
                       [r.status_code for r in results] == [200, 200] and again.status_code == 200
                       and len(answers) == 1 and len(runs) == 1 and len(consumed) == 1 and conflict.status_code == 409))

        # 15. 실제 LLM 형식: 조건을 [{field, value, evidence}] 목록으로, 참/거짓은 문자열로 보낸다
        llm.plan(("set_conditions", {"values": [{"field": "concrete_supply", "value": "사급", "evidence": "사급으로"},
                                                {"field": "vibrator_used", "value": "true", "evidence": "진동기 사용"}]}),
                 ("estimate_cost", {}))
        listed = post({"thread_id": thread, "message": "레미콘 사급으로, 진동기 사용"})
        checks.append(("D15 목록 형식 조건·문자열 참/거짓을 근거 대조 후 반영", item()["conditions"].get("concrete_supply") == "사급"
                       and item()["conditions"].get("vibrator_used") is True
                       and [q["name"] for q in listed["questions"]] == ["ready_mix_price"]))

        # 14. 비회원 대화 삭제는 새 흐름 상태(dlg: thread)도 지운다
        deleted = http.delete(f"/api/guest/conversations/{thread}").status_code
        checks.append(("D14 비회원 대화 삭제 시 대화 상태도 삭제", deleted == 204 and stored(thread) is None
                       and http.get(f"/api/export/{thread}.xlsx").status_code == 404))

    # 13. 설정 off: 기존 흐름
    os.environ["AGENT_MODE"] = ""
    with patch("backend.api.usage_limits.processing", return_value=nullcontext((None, "fixture", False))), \
            patch("backend.api.usage_limits.consume", return_value={}), \
            patch.object(client, "generate", side_effect=AssertionError("LLM called")), \
            patch.dict(os.environ, {"AGENT_LLM": "off"}), \
            TestClient(api_main.app, headers={"X-Guest-Session": SECRET}) as http:
        legacy = http.post("/api/chat", json={"message": "철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"}).json()
    checks.append(("D13 AGENT_MODE 꺼짐이면 기존 그래프 응답(ref 없음)",
                   legacy["status"] == "MISSING_INFO" and "estimate_current" not in legacy
                   and all("ref" not in q for q in legacy["questions"])))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
