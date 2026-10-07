"""AGENT_MODE=tools 회원 대화를 로컬 PostgreSQL(로컬 Supabase 127.0.0.1:54322)로 검사한다.

운영 DB·유료 LLM을 쓰지 않는다. 회원은 로컬 auth.users 픽스처이고 토큰 검증(chat_storage.identity)만 흉내 낸다.
- M1 저장 후 새 연결·새 그래프로 다시 읽어 조건·질문·최신 견적·Excel 복원
- M2 A회원의 대화를 B회원이 조회·답변·내보내기 할 수 없음
- M3 같은 request_id: 동시 요청 실행·차감 1회, 대화가 다르면 따로, 비회원과 회원은 따로
- M4 저장 실패(체크포인트 쓰기 오류): 대화 기록·체크포인트 모두 그대로, 같은 ID 재시도는 차감 없이 저장

사용: CHAT_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python evals/check_dialogue_member_db.py
"""

from __future__ import annotations

import io
import os
import sys
import threading
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ.update(AGENT_OFFLINE="1", AGENT_LLM="on", AGENT_MODE="tools")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from langgraph.checkpoint.postgres import PostgresSaver  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

import backend.api.main as api_main  # noqa: E402
from backend.agent.estimate import dialogue, tools  # noqa: E402
from backend.agent.tools.llm import client  # noqa: E402
from backend.api import chat_storage, dialogue_service, usage_limits  # noqa: E402
from evals.check_dialogue import HITS, PUMP, SECRET, ScriptedLLM  # noqa: E402


def main() -> int:
    if "127.0.0.1:54322" not in os.environ.get("CHAT_DATABASE_URL", ""):
        raise SystemExit("Set CHAT_DATABASE_URL to local Supabase port 54322 only")
    chat_storage.setup()
    a, b = str(uuid4()), str(uuid4())
    tokens = {"Bearer member-a": a, "Bearer member-b": b}

    def identity(token):
        if token is None:
            return None
        if token in tokens:
            return tokens[token]
        raise HTTPException(401, "invalid")

    with chat_storage.connection() as conn:
        # 이전 실행이 남긴 테스트 클라이언트(비회원) 사용량만 비운다. 로컬 DB 전용.
        conn.execute("DELETE FROM agent_state.daily_chat_usage WHERE subject=%s", (usage_limits.subject(None, "testclient"),))
        for user_id in (a, b):
            conn.execute("INSERT INTO auth.users(id,aud,role,email) VALUES (%s,'authenticated','authenticated',%s)",
                         (user_id, f"dialogue-{user_id}@example.invalid"))
    checks, llm, consumed, runs = [], ScriptedLLM(), [], []
    real_consume, real_turn = usage_limits.consume, dialogue.run_turn

    def consume(quota, *request):
        consumed.append(1)
        return real_consume(quota, *request)

    def turn(*args, **kwargs):
        runs.append(1)
        return real_turn(*args, **kwargs)

    try:
        with patch.object(chat_storage, "identity", side_effect=identity), \
                patch.object(usage_limits, "consume", side_effect=consume), \
                patch.object(tools, "retrieve", return_value={"hits": HITS}), \
                patch.object(client, "generate", llm), patch.object(api_main, "warmup_client", return_value=True), \
                patch.object(dialogue, "run_turn", turn), TestClient(api_main.app, raise_server_exceptions=False) as http:
            conversation = str(uuid4())
            as_a = {"Authorization": "Bearer member-a"}

            def post(body: dict, headers=as_a, expect=200) -> dict:
                result = http.post("/api/chat", headers=headers,
                                   json={"conversation_id": conversation, "request_id": str(uuid4()), **body})
                assert result.status_code == expect, (result.status_code, result.text[:300])
                return result.json()

            def answer(previous: dict, values: dict, headers=as_a, expect=200) -> dict:
                return post({"thread_id": conversation, "answers": values,
                             "refs": {q["name"]: q["ref"] for q in previous["questions"] if q["name"] in values}},
                            headers, expect)

            def reload() -> dict:
                with chat_storage.connection() as conn:
                    return dialogue.load(dialogue.build_dialogue_graph(PostgresSaver(conn)), conversation)

            # M1 저장 → 새 연결·새 그래프로 복원
            llm.plan(("find_work", {}), ("set_conditions", {"quantity": {"value": "100", "unit": "㎥",
                                                                         "evidence": "100세제곱미터"}}), ("estimate_cost", {}))
            t1 = post({"message": "콘크리트 타설 100세제곱미터 비용"})
            llm.plan(("estimate_cost", {}))
            t2 = answer(t1, {"work": "6-1-4"})
            llm.plan(("estimate_cost", {}))
            t3 = answer(t2, PUMP)
            pending = reload()
            llm.plan(("estimate_cost", {}))
            t4 = answer(t3, {"concrete_supply": "관급"})
            state = reload()
            with chat_storage.connection() as conn:
                restored = dialogue_service.restore(dialogue.build_dialogue_graph(PostgresSaver(conn)), conversation)
            book = load_workbook(io.BytesIO(http.get(f"/api/export/{conversation}.xlsx", headers=as_a).content), data_only=True)
            amount = t4["statement"]["totals"]["contract_amount"]
            transcript = http.get(f"/api/conversations/{conversation}", headers=as_a).json()["messages"]
            checks.append(("M1 새 연결·새 그래프로 조건·질문·최신 견적·Excel·대화 기록 복원",
                           [q["field"] for q in pending["pending"]] == ["concrete_supply"]
                           and tools._item(state["session"])["conditions"].get("pump_size") == "32m"
                           and tools.current_estimate(state["session"]) is not None
                           and restored["statement"]["totals"] == t4["statement"]["totals"]
                           and amount in [c.value for s in book for r in s.iter_rows() for c in r]
                           and len(transcript) == 8))

            # M2 다른 회원은 조회·답변·내보내기 불가
            as_b = {"Authorization": "Bearer member-b"}
            read = http.get(f"/api/conversations/{conversation}", headers=as_b).status_code
            export = http.get(f"/api/export/{conversation}.xlsx", headers=as_b).status_code
            reply = http.post("/api/chat", headers=as_b, json={"conversation_id": conversation, "thread_id": conversation,
                                                               "request_id": str(uuid4()), "message": "300세제곱미터로 바꿔줘"})
            checks.append(("M2 B회원은 A회원 대화 조회·답변·내보내기 불가(상태 그대로)",
                           read == 404 and export == 404 and reply.status_code == 404
                           and tools._item(reload()["session"])["quantity"]["value"] == "100"))

            # M3 같은 request_id: 동시 2회 + 재전송 → 실행 1·차감 1, 다른 대화·비회원은 따로
            request_id = str(uuid4())
            body = {"conversation_id": conversation, "thread_id": conversation, "request_id": request_id, "message": "근거 보여줘"}
            consumed.clear(), runs.clear()
            llm.plan(("explain_basis", {}))
            results = []
            workers = [threading.Thread(target=lambda: results.append(http.post("/api/chat", headers=as_a, json=body)))
                       for _ in range(2)]
            [worker.start() for worker in workers]
            [worker.join() for worker in workers]
            again = http.post("/api/chat", headers=as_a, json=body)
            same = len({r.json()["answer_id"] for r in [*results, again] if r.status_code == 200}) == 1
            once = len(runs) == 1 and len(consumed) == 1
            other = str(uuid4())
            llm.plan(("find_work", {}))
            http.post("/api/chat", headers=as_a, json={"conversation_id": other, "request_id": request_id, "message": "콘크리트 타설 품셈"})
            llm.plan(("find_work", {}))
            http.post("/api/chat", headers={"X-Guest-Session": SECRET}, json={"request_id": request_id, "message": "콘크리트 타설 품셈"})
            checks.append(("M3 같은 request_id 동시·재전송은 실행·차감 1회, 다른 대화·비회원은 따로",
                           [r.status_code for r in [*results, again]] == [200, 200, 200] and same and once
                           and len(runs) == 3 and len(consumed) == 3))

            # M4 저장 실패: 체크포인트 쓰기 오류면 대화 기록·상태 모두 그대로, 재시도는 차감 없이 저장
            request_id = str(uuid4())
            body = {"conversation_id": conversation, "thread_id": conversation, "request_id": request_id,
                    "message": "200세제곱미터로 바꿔줘"}
            consumed.clear(), runs.clear()
            before = len(http.get(f"/api/conversations/{conversation}", headers=as_a).json()["messages"])
            llm.plan(("set_conditions", {"quantity": {"value": "200", "unit": "㎥", "evidence": "200세제곱미터"}}), ("estimate_cost", {}))
            with patch.object(PostgresSaver, "put", side_effect=psycopg.OperationalError("simulated write failure")):
                failed = http.post("/api/chat", headers=as_a, json=body)
            unchanged = (tools._item(reload()["session"])["quantity"]["value"] == "100"
                         and len(http.get(f"/api/conversations/{conversation}", headers=as_a).json()["messages"]) == before)
            llm.plan(("set_conditions", {"quantity": {"value": "200", "unit": "㎥", "evidence": "200세제곱미터"}}), ("estimate_cost", {}))
            retried = http.post("/api/chat", headers=as_a, json=body)
            checks.append(("M4 저장 실패: 기록·상태 그대로, 같은 ID 재시도는 차감 없이 저장",
                           failed.status_code >= 500 and unchanged and retried.status_code == 200
                           and tools._item(reload()["session"])["quantity"]["value"] == "200"
                           and len(consumed) == 1 and len(runs) == 2))
            # M5 비회원 대화를 회원으로 가져오면 대화 상태(dlg: thread)도 옮겨져 최신 견적·Excel이 이어진다
            guest_headers = {"X-Guest-Session": SECRET}
            llm.plan(("find_work", {}), ("set_conditions", {"quantity": {"value": "100", "unit": "㎥",
                                                                         "evidence": "100세제곱미터"}}), ("estimate_cost", {}))
            g1 = http.post("/api/chat", headers=guest_headers, json={"message": "콘크리트 타설 100세제곱미터 비용"}).json()
            guest_thread = g1["thread_id"]
            for values in ({"work": "6-1-4"}, PUMP, {"concrete_supply": "관급"}):
                llm.plan(("estimate_cost", {}))
                g1 = http.post("/api/chat", headers=guest_headers, json={
                    "thread_id": guest_thread, "answers": values,
                    "refs": {q["name"]: q["ref"] for q in g1["questions"] if q["name"] in values}}).json()
            imported = str(uuid4())
            moved = http.post("/api/conversations/import-guest", headers={**as_a, **guest_headers},
                              json={"thread_id": guest_thread, "conversation_id": imported})
            with chat_storage.connection() as conn:
                member_state = dialogue.load(dialogue.build_dialogue_graph(PostgresSaver(conn)), imported)
            member_book = http.get(f"/api/export/{imported}.xlsx", headers=as_a)
            checks.append(("M5 비회원 → 회원 가져오기: 대화 상태·최신 견적·Excel 이어짐, 비회원 상태는 삭제",
                           moved.status_code == 200 and member_state is not None
                           and tools.current_estimate(member_state["session"]) is not None
                           and member_book.status_code == 200
                           and dialogue.load(dialogue.build_dialogue_graph(api_main.GRAPH.checkpointer), guest_thread) is None))
            # M6 차감 중복 방지는 DB 기록으로: 재시작(메모리 기록 삭제)·다른 인스턴스(별도 연결 동시 차감)에서도 1회
            def used() -> int:
                with chat_storage.connection() as conn:
                    row = conn.execute("SELECT used FROM agent_state.daily_chat_usage WHERE usage_day=%s AND subject=%s",
                                       (usage_limits.now().date(), usage_limits.subject(a, None))).fetchone()
                    return row["used"] if row else 0

            request_id = str(uuid4())
            body = {"conversation_id": conversation, "thread_id": conversation, "request_id": request_id,
                    "message": "300세제곱미터로 바꿔줘"}
            start = used()
            llm.plan(("set_conditions", {"quantity": {"value": "300", "unit": "㎥", "evidence": "300세제곱미터"}}), ("estimate_cost", {}))
            with patch.object(PostgresSaver, "put", side_effect=psycopg.OperationalError("simulated write failure")):
                first = http.post("/api/chat", headers=as_a, json=body)
            api_main._REQUESTS.clear()  # 서버 재시작 또는 다른 인스턴스: 메모리 기록이 없다
            llm.plan(("set_conditions", {"quantity": {"value": "300", "unit": "㎥", "evidence": "300세제곱미터"}}), ("estimate_cost", {}))
            second = http.post("/api/chat", headers=as_a, json=body)
            after_restart = used() - start
            key = usage_limits.request_key("member", a, conversation, str(uuid4()))
            before = used()
            barrier = threading.Barrier(2)

            def instance():
                with chat_storage.connection() as conn:  # 인스턴스마다 다른 DB 연결, 주체별 잠금도 거치지 않는다
                    barrier.wait()
                    usage_limits.consume((conn, usage_limits.subject(a, None), True), key)

            instances = [threading.Thread(target=instance) for _ in range(2)]
            [worker.start() for worker in instances]
            [worker.join() for worker in instances]
            checks.append(("M6 재시작 뒤 같은 ID 재시도와 두 인스턴스의 동시 차감 모두 1회(DB 기록)",
                           first.status_code >= 500 and second.status_code == 200 and after_restart == 1
                           and used() - before == 1))
    finally:
        with chat_storage.connection() as conn:
            for user_id in (a, b):
                conn.execute("DELETE FROM public.conversations WHERE user_id=%s", (user_id,))
                conn.execute("DELETE FROM auth.users WHERE id=%s", (user_id,))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
