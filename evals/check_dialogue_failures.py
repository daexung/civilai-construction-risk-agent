"""AGENT_MODE=tools 실패 복구·응답 검증을 검사한다(외부 호출 없음, 비회원).

- 도구 오류: 같은 턴에 먼저 바꾼 조건까지 저장하지 않고 직전 상태 유지, 같은 request_id 재시도는 차감 없이 재실행.
- LLM 오류·잘못된 JSON: 상태를 바꾸기 전이면 규칙 정책, 도구 실행 뒤면 결과를 살리고 마침.
- 설명만 실패: 도구 결과는 저장하고 템플릿 응답.
- 시간 초과: 실제 SDK 호출에 넘기는 timeout이 남은 턴 시간 이하이고, 턴이 제한 안에 끝난다.
- 저장 실패: 응답은 ERROR, 상태는 직전 그대로, 같은 request_id 재시도는 차감 없이 한 번 더 실행.
- 응답 검증: 인원·장비 뒤바꿈, 총액을 단가로, 원·만원 혼동, 다른 항목의 같은 숫자를 거부.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.update(AGENT_OFFLINE="1", AGENT_LLM="on", AGENT_MODE="tools")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import backend.api.main as api_main  # noqa: E402
from backend.agent.tools.calc.format import approx
from backend.agent.estimate import dialogue, reply_check, tools  # noqa: E402
from backend.agent.tools.llm import client  # noqa: E402
from evals.check_dialogue import HITS, PUMP, SECRET, ScriptedLLM  # noqa: E402

FACTS = [{"id": "line0", "item": "콘크리트공", "value": "0.0308", "unit": "인/㎥", "kind": "per_unit"},
         {"id": "line4", "item": "콘크리트펌프차", "value": "0.0615", "unit": "hr/㎥", "kind": "per_unit"},
         {"id": "contract_amount", "item": "도급액", "value": "3858622", "unit": "원", "kind": "total"},
         {"id": "labor", "item": "노무비", "value": "1234567", "unit": "원", "kind": "total"},
         {"id": "quantity", "item": "물량", "value": "300", "unit": "㎥", "kind": "total", "item_optional": True},
         {"id": "ready_mix_price", "item": "레미콘 단가", "value": "90000", "unit": "원", "kind": "per_unit",
          "item_optional": True}]


WORK_DAYS = [{"id": "work_days", "item": "작업일수", "value": "30/13", "unit": "일", "kind": "total", "rounded": "2.31"}]


def reply_cases() -> list[tuple[str, bool]]:
    verify = lambda text: reply_check.verify(text, FACTS, [])  # noqa: E731
    return [
        ("R1 올바른 대응은 통과", verify("콘크리트공 0.0308인/㎥이고 도급액 3,858,622원입니다.") is None),
        ("R2 인원 값을 장비 항목으로(뒤바꿈) 거부",
         verify("콘크리트펌프차 0.0308인/㎥") is not None),
        ("R3 장비 값을 인원 항목으로 거부", verify("콘크리트공 0.0615hr/㎥") is not None),
        ("R4 두 항목을 나열해 가까운 항목이 다르면 거부",
         verify("콘크리트펌프차와 콘크리트공 0.0615hr/㎥") is not None),
        ("R5 같은 단위의 값 바꿔치기(인↔hr) 거부", verify("콘크리트공 0.0308hr/㎥") is not None),
        ("R6 총액을 단가로 설명 거부", verify("도급액 단가 3,858,622원") is not None),
        ("R7 총액을 ㎥당으로 설명 거부", verify("1㎥당 도급액 3,858,622원") is not None),
        ("R8 원을 만원으로 혼동 거부", verify("도급액 3,858,622만원") is not None),
        ("R9 만원 환산 값(386만원)도 거부", verify("도급액 386만원") is not None),
        ("R10 결과에 있는 숫자라도 다른 항목이면 거부",
         verify("노무비 3,858,622원") is not None),
        ("R11 단위당 값을 총액으로 설명 거부", verify("콘크리트공 총 0.0308인/㎥") is not None),
        ("R12 근거 없는 숫자 거부", verify("도급액 3,858,622원, 약 12일") is not None),
        ("R13 띄어쓰기만 다른 구절은 통과", verify("콘크리트공은 0.0308 인/㎥입니다.") is None),
        ("R14 만원 환산이 맞으면 통과(9만원=90000원)", verify("레미콘 단가 9만원으로 계산했어요.") is None),
        ("R15 물량은 항목명 없이도 통과, 다른 항목명이 붙으면 거부",
         verify("300㎥로 바꿨어요.") is None
         and verify("노무비 300㎥") is not None),
        ("R16 근거 원문의 숫자는 근거 턴에서만 허용",
         reply_check.verify("높이 할증은 10%까지예요.", FACTS, [], quoted=["… 10%까지 가산한다"]) is None
         and verify("높이 할증은 10%까지예요.") is not None),
        # 실제 LLM 평가(3회차)에서 맞는 문장인데 대응표 글자가 달라 거부됐던 문장
        ("R17 실제 문장: '콘크리트공의 품셈은 0.0308인/㎥입니다.' 통과", verify("콘크리트공의 품셈은 0.0308인/㎥입니다.") is None),
        ("R18 실제 문장: '레미콘 단가는 90000원입니다.' 통과, 같은 문장 9만 원 오기는 거부",
         verify("레미콘 단가는 90000원입니다.") is None and verify("레미콘 단가는 9000원입니다.") is not None),
        ("R19 거부된 값은 '지원하지 않아 기존 값 유지' 설명에서만 통과",
         reply_check.verify("25m는 지원하지 않아 기존 32m를 유지했어요.", FACTS, ["32m"], refused=["25m"]) is None),
        ("R20 거부된 값을 적용한 것처럼 설명하면 거부",
         reply_check.verify("25m로 계산했어요.", FACTS, ["32m"], refused=["25m"]) is not None
         and reply_check.verify("25m로 바꿨지만 기존 값은 유지했어요.", FACTS, ["32m"], refused=["25m"]) is not None),
        ("R21 거부 목록에 없으면 같은 설명이라도 거부(전역 허용 아님)",
         reply_check.verify("25m는 지원하지 않아 기존 32m를 유지했어요.", FACTS, ["32m"]) is not None),
        ("R22 작업일수 30/13은 기존 표시 규칙 2.(307692)로 보이고, 그 표기는 통과·반올림 표기는 거부",
         reply_check.display("30/13") == "2.(307692)" and reply_check.display("100") == "100"
         and reply_check.verify("작업일수 2.(307692)일입니다.", WORK_DAYS, []) is None
         and reply_check.verify("작업일수 2.307일입니다.", WORK_DAYS, []) is not None),
        ("R23 작업일수 '약 2.31일'(정해진 반올림)은 통과, 2.3·2.32·반올림 정보 없는 사실의 2.31은 거부",
         reply_check.verify("작업일수 약 2.31일입니다.", WORK_DAYS, []) is None
         and reply_check.verify("작업일수 약 2.3일입니다.", WORK_DAYS, []) is not None
         and reply_check.verify("작업일수 약 2.32일입니다.", WORK_DAYS, []) is not None
         and reply_check.verify("작업일수 약 2.31일입니다.", [{**WORK_DAYS[0], "rounded": None}], []) is not None),
        ("R24 표시 반올림: 30/13→약 2.31, 2.5→2.5, 2.345→약 2.35(사사오입), 값 변경 없음",
         approx("30/13") == "약 2.31" and approx("2.5") == "2.5" and approx("2.345") == "약 2.35"
         and approx("1000/3") == "약 333.33"),
    ]


def main() -> int:
    checks = reply_cases()
    llm = ScriptedLLM()
    consumed, runs = [], []
    original_turn = dialogue.run_turn

    def counted_turn(*args, **kwargs):
        runs.append(1)
        return original_turn(*args, **kwargs)

    with patch("backend.api.usage_limits.processing", return_value=nullcontext((None, "fixture", False))), \
            patch("backend.api.usage_limits.status", return_value={}), \
            patch("backend.api.usage_limits.consume", side_effect=lambda quota, *request: consumed.append(1) or {}), \
            patch.object(tools, "retrieve", return_value={"hits": HITS}), \
            patch.object(client, "generate", llm), patch.object(api_main, "warmup_client", return_value=True), \
            patch.object(dialogue, "run_turn", counted_turn), \
            TestClient(api_main.app, headers={"X-Guest-Session": SECRET}) as http:
        def post(body: dict) -> dict:
            result = http.post("/api/chat", json=body)
            assert result.status_code == 200, (result.status_code, result.text[:300])
            return result.json()

        def answer(previous: dict, values: dict) -> dict:
            return post({"thread_id": previous["thread_id"], "answers": values,
                         "refs": {q["name"]: q["ref"] for q in previous["questions"] if q["name"] in values}})

        def priced() -> tuple[str, dict]:
            llm.plan(("find_work", {}), ("set_conditions", {"quantity": {"value": "100", "unit": "㎥",
                                                                         "evidence": "100세제곱미터"}}), ("estimate_cost", {}))
            first = post({"message": "콘크리트 타설 100세제곱미터 비용"})
            llm.plan(("estimate_cost", {}))
            second = answer(first, {"work": "6-1-4"})
            llm.plan(("estimate_cost", {}))
            third = answer(second, PUMP)
            llm.plan(("estimate_cost", {}))
            return first["thread_id"], answer(third, {"concrete_supply": "관급"})

        def stored(thread: str) -> dict:
            return dialogue.load(dialogue.build_dialogue_graph(api_main.GRAPH.checkpointer), thread)

        def quantity(thread: str) -> str:
            return tools._item(stored(thread)["session"])["quantity"]["value"]

        thread, base = priced()
        totals = base["statement"]["totals"]

        # F1 도구 오류: 같은 턴에 먼저 반영한 물량까지 저장하지 않는다. 재시도는 차감 없이 다시 실행.
        body = {"thread_id": thread, "message": "200세제곱미터로 비용 다시", "request_id": "21111111-1111-4111-8111-111111111111"}
        llm.plan(("set_conditions", {"quantity": {"value": "200", "unit": "㎥", "evidence": "200세제곱미터"}}), ("estimate_cost", {}))
        consumed.clear(), runs.clear()
        with patch.object(tools, "estimate_cost", side_effect=RuntimeError("tool boom")):
            failed = post(body)
        kept = quantity(thread) == "100" and tools.current_estimate(stored(thread)["session"])["statement"]["totals"] == totals
        llm.plan(("set_conditions", {"quantity": {"value": "200", "unit": "㎥", "evidence": "200세제곱미터"}}), ("estimate_cost", {}))
        retried = post(body)
        checks.append(("F1 도구 오류: ERROR 응답, 직전 상태 유지, 같은 ID 재시도는 차감 없이 재실행",
                       failed["status"] == "ERROR" and "유지" in failed["message"] and kept
                       and retried["estimate_current"] and quantity(thread) == "200"
                       and len(consumed) == 1 and len(runs) == 2))

        # F2 LLM 오류(첫 호출): 상태를 바꾸기 전이므로 규칙 정책으로 같은 도구를 부른다
        llm.actions, llm.reply_raise = [{"__raise__": True}], True
        rule = post({"thread_id": thread, "message": "300세제곱미터로 바꿔줘"})
        llm.reply_raise = False
        checks.append(("F2 LLM 오류: 규칙 정책으로 재계산, 템플릿 응답",
                       rule["estimate_current"] and quantity(thread) == "300" and rule["answer_source"] == "template"
                       and rule["llm_info"]["llm_attempts"] == 1))  # 규칙 정책으로 넘어가면 설명 LLM은 부르지 않는다

        # F3 잘못된 JSON: 첫 호출이면 규칙 정책, 도구 실행 뒤면 그 결과로 마친다
        llm.actions = [{"__raw__": "행동 아님"}]
        raw_first = post({"thread_id": thread, "message": "250세제곱미터로 바꿔줘"})
        llm.plan(("explain_basis", {}))
        llm.actions.append({"__raw__": "{깨진 json"})
        raw_after = post({"thread_id": thread, "message": "근거 알려줘"})
        checks.append(("F3 잘못된 JSON: 첫 호출은 규칙 정책, 도구 뒤에는 결과 유지",
                       quantity(thread) == "250" and raw_first["estimate_current"]
                       and raw_after["estimate_current"] and stored(thread)["turn"]["tools"] == ["explain_basis"]))

        # F4 설명 생성만 실패: 도구 결과(물량 400 재계산)는 저장, 템플릿 응답
        llm.plan(("set_conditions", {"quantity": {"value": "400", "unit": "㎥", "evidence": "400세제곱미터"}}), ("estimate_cost", {}))
        llm.reply_raise = True
        reply_failed = post({"thread_id": thread, "message": "400세제곱미터로 바꿔줘"})
        llm.reply_raise = False
        checks.append(("F4 설명 실패: 도구 결과 저장 + 템플릿", quantity(thread) == "400" and reply_failed["estimate_current"]
                       and reply_failed["answer_source"] == "template" and bool(reply_failed["llm_info"]["rejected"])))

        # F6 저장 실패: ERROR, 상태는 직전 그대로. 같은 ID 재시도는 차감 없이 한 번 더 실행해 저장된다
        body = {"thread_id": thread, "message": "500세제곱미터로 바꿔줘", "request_id": "31111111-1111-4111-8111-111111111111"}
        consumed.clear(), runs.clear()
        saver = api_main.GRAPH.checkpointer
        llm.plan(("set_conditions", {"quantity": {"value": "500", "unit": "㎥", "evidence": "500세제곱미터"}}), ("estimate_cost", {}))
        with patch.object(saver, "put", side_effect=OSError("disk full")), \
                patch.object(saver, "put_writes", side_effect=OSError("disk full")):
            save_failed = post(body)
        unchanged = quantity(thread) == "400"
        llm.plan(("set_conditions", {"quantity": {"value": "500", "unit": "㎥", "evidence": "500세제곱미터"}}), ("estimate_cost", {}))
        saved = post(body)
        replay = post(body)
        checks.append(("F6 저장 실패: ERROR·상태 유지, 재시도는 차감 없이 1회 더 실행, 그 뒤엔 같은 응답",
                       save_failed["status"] == "ERROR" and unchanged and quantity(thread) == "500"
                       and saved["estimate_current"] and replay["answer_id"] == saved["answer_id"]
                       and len(consumed) == 1 and len(runs) == 2))

        # F8 실제 LLM 평가 7턴 재현: 단위를 빠뜨린 물량은 근거 구절로 단위를 정하고, 근거와 다른 값은 거부를 알린다
        llm.plan(("set_conditions", {"quantity": {"value": "600", "evidence": "600세제곱미터"}}), ("estimate_cost", {}))
        no_unit = post({"thread_id": thread, "message": "600세제곱미터로 바꿔줘"})
        llm.plan(("set_conditions", {"quantity": {"value": "700", "evidence": "650세제곱미터"}}), ("estimate_cost", {}))
        mismatch = post({"thread_id": thread, "message": "650세제곱미터로 바꿔줘"})
        checks.append(("F8 단위 누락 물량은 근거로 반영, 반영 못 한 값은 답변 첫머리에 안내",
                       no_unit["estimate_current"] and quantity(thread) == "600"
                       and mismatch["answer"].startswith("반영하지 못했어요 - 물량")))

        # F7 중복 판정은 대화별: 같은 request_id라도 다른 대화면 각각 실행·차감
        other, _ = priced()
        consumed.clear(), runs.clear()
        same_id = "41111111-1111-4111-8111-111111111111"
        llm.plan(("explain_basis", {}))
        post({"thread_id": thread, "message": "근거", "request_id": same_id})
        llm.plan(("explain_basis", {}))
        post({"thread_id": other, "message": "근거", "request_id": same_id})
        checks.append(("F7 같은 request_id라도 대화가 다르면 따로 실행·차감", len(runs) == 2 and len(consumed) == 2))

    # F5 시간 초과: 실제 client.generate 경로에서 SDK에 넘기는 timeout이 남은 턴 시간 이하, 턴은 제한 안에 끝난다
    seen = []

    class SlowModels:
        def generate_content(self, model, contents, config):
            seen.append(config.http_options.timeout)
            time.sleep(config.http_options.timeout / 1000)  # SDK가 그 시간에 끊는다고 보고 끝까지 기다린다
            raise TimeoutError("timed out")

    with patch("backend.api.usage_limits.processing", return_value=nullcontext((None, "fixture", False))), \
            patch("backend.api.usage_limits.status", return_value={}), \
            patch("backend.api.usage_limits.consume", return_value={}), \
            patch.object(tools, "retrieve", return_value={"hits": HITS}), \
            patch.object(api_main, "warmup_client", return_value=True), \
            patch.object(client, "_get_client", return_value=SimpleNamespace(models=SlowModels())), \
            patch.dict(os.environ, {"GEMINI_API_KEY": "offline-test-key", "LLM_PROVIDER": "studio",
                                    "LLM_MODEL": "offline-test-model"}), \
            patch.object(dialogue, "TURN_SECONDS", 3), \
            TestClient(api_main.app, headers={"X-Guest-Session": SECRET}) as http:
        started = time.monotonic()
        slow = http.post("/api/chat", json={"message": "콘크리트 타설 1세제곱미터 품셈 알려줘"}).json()
        elapsed = time.monotonic() - started
    checks.append(("F5 시간 제한: SDK timeout ≤ 남은 턴 시간(3초), 턴은 제한 안에 끝나고 규칙 정책으로 응답",
                   seen and all(0 < value <= 3000 for value in seen) and sum(seen) <= 3000 + 100
                   and elapsed < 3 + 2 and slow["status"] == "MISSING_INFO"
                   and [q["name"] for q in slow["questions"]] == ["work"]))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
