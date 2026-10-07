"""여러 공종 묶음 견적을 오프라인으로 검사한다(운영 DB·유료 API 호출 없음).

항목 분리, 항목별 질문, 간접비 1회 계산, 실패 항목이 섞인 부분 금액, 조건 변경 재계산,
내역서·원가계산서·Excel 금액 일치를 확인한다.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

os.environ["AGENT_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from openpyxl import load_workbook  # noqa: E402

from backend.agent.nodes.bundle import ALL_ITEMS, EACH, ONE, bundle, collect, plan_items, split_items  # noqa: E402
from backend.agent.nodes.route import route  # noqa: E402
from backend.api.main import _item_out, app  # noqa: E402
from backend.agent.tools.calc.cost_statement import calculate_cost_statement  # noqa: E402

CLIENT = TestClient(app, headers={"X-Guest-Session": "offline-bundle-session-" + "x" * 32})
READY_MIX = {"work": "6-1-1", "scattered_small_volume": False, "concrete_supply": "관급",
             "placement_method": "인력운반 타설"}
PUMP_BLOCKED = {"work": "6-1-4", "pump_size": "32m", "slump_band": "15㎝", "facility_type": "Type-Ⅱ",
                "site_type": "Type-Ⅱ", "placement": "붐", "vibrator_used": True, "reset_status": "있음",
                "concrete_supply": "관급"}


def _answer(question: dict, answers: dict, message: str):
    name, choices = question["name"], question.get("choices") or []
    if name == "work":
        return next(choice for choice in choices if answers["work"] in choice)
    if name == "structure":
        return next(choice for choice in choices if ("무근" in choice) == ("무근" in message))
    if name == "placement_method":
        return next((choice for choice in choices if "인력" in choice), choices[0])
    return answers.get(name, question.get("default") or (choices[0] if choices else None))


def run(message: str, per_item: dict[int, dict]) -> tuple[str, list[dict]]:
    """항목 번호별 답으로 질문이 끝날 때까지 답한다. (thread_id, 응답 목록)"""
    responses = [CLIENT.post("/api/chat", json={"message": message}).json()]
    for _ in range(10):
        current = responses[-1]
        if current["status"] != "MISSING_INFO":
            break
        number = int(re.match(r"(\d+)번 항목", current["message"]).group(1))
        answers = {question["name"]: _answer(question, per_item[number], current["message"])
                   for question in current["questions"]}
        responses.append(CLIENT.post("/api/chat", json={"thread_id": current["thread_id"], "answers": answers}).json())
    return responses[0]["thread_id"], responses


def _regressions() -> tuple[list[tuple[str, str]], int]:
    """기존 단일 질문 모음에서 여러 항목·확인 질문으로 바뀌는 질문과 실제 route(LLM 끔) 결과."""
    queries: set[str] = set()

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ("query", "question") and isinstance(child, str):
                    queries.add(child)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for name in ("router_testset.jsonl", "draft_questions.jsonl"):
        for line in (ROOT / "evals" / name).read_text(encoding="utf-8").splitlines():
            if line.strip():
                walk(json.loads(line))
    walk(json.loads((ROOT / "evals/golden_estimate.json").read_text(encoding="utf-8")))
    changed = [(query, route({"query": query})["route"]) for query in sorted(queries)
               if len(plan_items(query)[0]) > 1 or plan_items(query)[1]]
    return changed, len(queries)


def main() -> int:
    checks = []

    # 1) 분리 규칙
    checks.append(("S1 장비 규격은 같은 공종의 조건", split_items("콘크리트 100㎥, 펌프차 32m") == ["콘크리트 100m3 펌프차 32m"]))
    checks.append(("S2 서로 다른 공종 두 개", split_items("콘크리트 100㎥, 자동문 3개소") == ["콘크리트 100m3", "자동문 3개소"]))
    checks.append(("S3 물량 없는 추가 공종도 항목", split_items("콘크리트 100㎥, 도장도 같이 해줘")
                   == ["콘크리트 100m3", "도장도 같이 해줘"]))
    unclear_plan = plan_items("콘크리트 100㎥, 마감 깔끔하게")
    checks.append(("S4 애매하면 확인", unclear_plan[0] == [] and [q["name"] for q in unclear_plan[1]] == ["split_1"]))
    checks.append(("S5 공통 조건은 모든 공종, 특정 조건은 해당 공종에",
                   split_items("도로공사, 레미콘 100㎥ 그리고 거푸집 20㎡. 레미콘은 관급입니다.")
                   == ["도로공사 레미콘 100m3 레미콘은 관급입니다", "도로공사 거푸집 20m2"]))
    checks.append(("S6 치수·천 단위·기준값은 물량 아님",
                   len(split_items("옹벽 높이 3m, 레미콘 1,500㎥ 타설")) == 1
                   and len(split_items("운반거리가 25m일 때, 레미콘 100㎥ 타설")) == 1))
    changed, total = _regressions()
    for query, routed in changed:
        print(f"  바뀐 기존 질문(route={routed}): {query}")
    checks.append((f"S7 기존 단일 질문 {total}개 중 분리·확인으로 바뀐 것 없음", not changed))

    # 검토자 재현 사례
    checks.append(("R1 문장 어미('이고')가 붙어도 두 공종", split_items("콘크리트 100㎥, 자동문 3개소이고 견적 부탁해")
                   == ["콘크리트 100m3", "자동문 3개소이고 견적 부탁해"]))
    equipment = "레미콘 100㎥, 자동문 3개소, 펌프차 32m"
    asked = plan_items(equipment)[1]
    checks.append(("R2 맨 뒤 장비 조건은 전체 복사 대신 어느 공종인지 확인", plan_items(equipment)[0] == []
                   and [q["name"] for q in asked] == ["attach_2"] and ALL_ITEMS in asked[0]["choices"]))
    checks.append(("R2b 답한 공종에만 장비 조건", plan_items(equipment, {"attach_2": asked[0]["choices"][0]})[0]
                   == ["레미콘 100m3 펌프차 32m", "자동문 3개소"]
                   and plan_items(equipment, {"attach_2": ALL_ITEMS})[0] == ["레미콘 100m3 펌프차 32m", "자동문 3개소 펌프차 32m"]))
    checks.append(("R2c 조건에 공종 낱말이 있으면 그 공종에만", split_items("레미콘 100㎥, 자동문 3개소. 레미콘은 관급입니다.")
                   == ["레미콘 100m3 레미콘은 관급입니다", "자동문 3개소"]))
    named = "도장과 자동문 설치 견적 부탁해"
    named_plan = plan_items(named)
    checks.append(("R3 물량 없는 복수 공종은 나눌지 확인", named_plan[0] == []
                   and [q["name"] for q in named_plan[1]] == ["named"]
                   and plan_items(named, {"named": EACH})[0] == ["도장", "자동문 설치"]
                   and plan_items(named, {"named": ONE})[0] == []))
    checks.append(("R3b 규칙 질문·장비 조합은 묻지 않음",
                   plan_items("경유보일러 설치 시 수압시험과 시운전 품은 따로 계산해야 하나요?") == ([], [])
                   and plan_items("대형브레이커와 굴착기 조합으로 연암을 굴착할 때 작업능력은 얼마인가요?") == ([], [])))

    # 2) 자연어 묶음 견적 끝까지
    natural = "도로 옹벽 공사 견적 좀 부탁드려요. 철근구조물 레미콘 150㎥ 인력 타설이고, 무근구조물 레미콘 50㎥ 인력 타설이에요. 레미콘은 관급입니다."
    thread, flow = run(natural, {1: READY_MIX, 2: READY_MIX})
    done = flow[-1]
    items = done["items"]
    checks.append(("N1 자연어 2개 공종 계산", done["status"] in ("OK", "PARTIAL") and len(items) == 2
                   and [item["inputs"] for item in items] and all(item["reason"] == "" for item in items)
                   and done["statement"]["conditions"]["work_category"] == "도로"))
    lines = {line["name"]: line for line in done["statement"]["lines"]}
    checks.append(("N2 직접비 합산·간접비 1회", lines["직접노무비"]["amount"]
                   == sum(int(item["priced"]["reference_amounts"]["subtotals"]["노무비"]) for item in items)
                   and sum(line["name"] == "간접노무비" for line in done["statement"]["lines"]) == 1))
    checks.append(("N3 본문은 금액·범위만(공종별 직접비 목록 없음)", done["answer"].startswith("계산한 공종 2개를")
                   and "직접비" not in done["answer"] and "부분 금액" not in done["answer"]))

    # 3) 내역서·원가계산서·Excel 금액 일치
    bills = done["tables"]["bills"]
    bill_total = sum(int(bill["total"]) for bill in bills)
    export = CLIENT.get(f"/api/export/{thread}.xlsx")
    book = load_workbook(io.BytesIO(export.content))
    rows = [row for row in book["내역서"].iter_rows(min_row=6, values_only=True) if row[0]]
    excel_items = {row[0]: row for row in rows[:2]}
    total_row = next(row for row in rows if row[0] == "합계")
    checks.append(("E1 내역서 공종별 금액 = 항목 금액", [int(bill["total"]) for bill in bills]
                   == [int(item["priced"]["reference_amounts"]["total"]) for item in items]
                   and [row[11] for row in rows[:2]] == [int(bill["total"]) for bill in bills] and len(excel_items) <= 2))
    checks.append(("E2 내역서 합계 = 비목 합 = 원가계산서 직접비", total_row[11] == bill_total
                   and total_row[7] == lines["직접노무비"]["amount"] and total_row[9] == lines["직접경비"]["amount"]
                   and f"{bill_total:,}원" in done["statement"]["basis_notes"][0]))
    estimate = [row for row in book["견적서"].iter_rows(values_only=True)]
    contract = done["statement"]["totals"]["contract_amount"]
    checks.append(("E3 Excel 견적금액·호표·파일명", export.status_code == 200
                   and any(f"₩{contract:,}" in str(row[0]) for row in estimate)
                   and "%EC%99%B8%201%EA%B1%B4" in export.headers["content-disposition"]  # '외 1건'
                   and [str(row[0])[:4] for row in book["일위대가"].iter_rows(min_row=6, values_only=True)
                        if str(row[0] or "").startswith("제 ")] == ["제 1호", "제 2호"]))

    # 4) 조건 변경 재계산
    changed_response = CLIENT.post("/api/chat", json={"thread_id": thread, "conditions": {"contractor_type": "전문건설업"}}).json()
    checks.append(("C1 조건 변경 후 묶음 재계산", changed_response["statement"]["conditions"]["contractor_type"] == "전문건설업"
                   and len(changed_response["items"]) == 2
                   and changed_response["statement"]["totals"]["contract_amount"] != contract
                   and [bill["total"] for bill in changed_response["tables"]["bills"]] == [bill["total"] for bill in bills]))

    # 5) 성공 + 계산 보류 혼합
    mixed_thread, mixed_flow = run("철근구조물 레미콘 인력운반 타설 150㎥, 철근콘크리트 벽체 260㎥ 32m 붐 펌프차로 타설",
                                   {1: READY_MIX, 2: PUMP_BLOCKED})
    mixed = mixed_flow[-1]
    ok_item, failed_item = mixed["items"]
    mixed_lines = {line["name"]: line for line in mixed["statement"]["lines"]}
    checks.append(("M1 실패 항목 상태·사유 유지", mixed["status"] == "PARTIAL" and failed_item["status"] == "BLOCKED"
                   and failed_item["reason"] and failed_item["priced"] is None and ok_item["status"] in ("OK", "PARTIAL")))
    checks.append(("M2 계산된 공종만 금액에 포함·부분 금액 안내",
                   mixed_lines["직접노무비"]["amount"] == int(ok_item["priced"]["reference_amounts"]["subtotals"]["노무비"])
                   and any(entry["name"].startswith("2번 항목") for entry in mixed["statement"]["unpriced"])
                   and "부분 금액" in mixed["answer"] and len(mixed["tables"]["bills"]) == 1))
    mixed_export = CLIENT.get(f"/api/export/{mixed_thread}.xlsx")
    mixed_book = load_workbook(io.BytesIO(mixed_export.content))
    missing = [str(row[0]) for row in mixed_book["원가계산서"].iter_rows(values_only=True) if row[0]]
    checks.append(("M3 혼합 결과 Excel: 성공 공종 표 + 빠진 항목", mixed_export.status_code == 200
                   and any(name.startswith("2번 항목") for name in missing)
                   and [str(row[0])[:4] for row in mixed_book["일위대가"].iter_rows(min_row=6, values_only=True)
                        if str(row[0] or "").startswith("제 ")] == ["제 1호"]))

    # 6) 애매한 조각은 확인 질문, 물량 없는 추가 공종은 별도 항목
    unclear = CLIENT.post("/api/chat", json={"message": "철근구조물 레미콘 인력운반 타설 150㎥, 마감 깔끔하게"}).json()
    as_condition = CLIENT.post("/api/chat", json={"thread_id": unclear["thread_id"],
                                                   "answers": {"split_1": "앞 공종의 조건"}}).json()
    checks.append(("U1 확인 질문 후 조건이면 단일 흐름", [q["name"] for q in unclear["questions"]] == ["split_1"]
                   and as_condition["items"] == [] and not as_condition["message"].startswith("1번 항목")))
    unclear2 = CLIENT.post("/api/chat", json={"message": "철근구조물 레미콘 인력운반 타설 150㎥, 마감 깔끔하게"}).json()
    as_work = CLIENT.post("/api/chat", json={"thread_id": unclear2["thread_id"], "answers": {"split_1": "별도 공종"}}).json()
    checks.append(("U2 별도 공종이면 항목으로 계산 시작", as_work["message"].startswith("1번 항목")))
    _, added_flow = run("철근구조물 레미콘 인력운반 타설 150㎥, 도장도 같이 해줘", {1: READY_MIX, 2: {"work": ""}})
    added = next((r for r in added_flow if r["message"].startswith("2번 항목(도장도 같이 해줘)")), added_flow[-1])
    checks.append(("U3 '도장도 같이'는 별도 항목으로 확인", added["message"].startswith("2번 항목(도장도 같이 해줘)")
                   or any(item["query"] == "도장도 같이 해줘" for item in added.get("items", []))))

    # 검토자 사례의 실제 API 흐름
    attach = CLIENT.post("/api/chat", json={"message": equipment}).json()
    attached = CLIENT.post("/api/chat", json={"thread_id": attach["thread_id"],
                                               "answers": {"attach_2": "1번(레미콘 100m3)"}}).json()
    checks.append(("A1 장비 조건 확인 → 선택한 공종에만 붙여 계산 시작",
                   [q["name"] for q in attach["questions"]] == ["attach_2"]
                   and attached["message"].startswith("1번 항목(레미콘 100m3 펌프차 32m)")))
    ask_named = CLIENT.post("/api/chat", json={"message": named}).json()
    each = CLIENT.post("/api/chat", json={"thread_id": ask_named["thread_id"], "answers": {"named": EACH}}).json()
    ask_named2 = CLIENT.post("/api/chat", json={"message": named}).json()
    one = CLIENT.post("/api/chat", json={"thread_id": ask_named2["thread_id"], "answers": {"named": ONE}}).json()
    checks.append(("A2 복수 공종 확인 → 따로면 1번 항목(도장)부터, 하나면 기존 흐름",
                   [q["name"] for q in ask_named["questions"]] == ["named"]
                   and (each["message"].startswith("1번 항목(도장)") or any(i["query"] == "도장" for i in each["items"]))
                   and one["items"] == [] and not one["message"].startswith("1번 항목")))
    print("  A2 따로 견적 응답:", each["status"], each["message"][:60], [(i["query"], i["status"], i["reason"][:30]) for i in each["items"]])

    # 확인 질문: 명시적으로 고른 답만 저장하고 나머지는 다시 묻는다
    four = "레미콘 100㎥, 자동문 3개소, 펌프차 32m, 슬럼프 15cm"
    first_ask = CLIENT.post("/api/chat", json={"message": four}).json()
    partial = CLIENT.post("/api/chat", json={"thread_id": first_ask["thread_id"],
                                             "answers": {"attach_2": "1번(레미콘 100m3)"}}).json()
    invalid = CLIENT.post("/api/chat", json={"thread_id": first_ask["thread_id"], "answers": {"attach_3": "아무거나"}}).json()
    free = CLIENT.post("/api/chat", json={"thread_id": first_ask["thread_id"], "message": "잘 모르겠어요"}).json()
    final = CLIENT.post("/api/chat", json={"thread_id": first_ask["thread_id"],
                                           "answers": {"attach_3": "1번(레미콘 100m3)"}}).json()
    reasons = lambda response: {q["name"]: q.get("reason") for q in response["questions"]}
    checks.append(("Q1 두 확인 질문", [q["name"] for q in first_ask["questions"]] == ["attach_2", "attach_3"]))
    checks.append(("Q2 일부만 답하면 남은 질문만 다시(자동 적용 없음)", partial["status"] == "MISSING_INFO"
                   and reasons(partial) == {"attach_3": "아직 답하지 않은 질문이에요."} and partial["items"] == []))
    checks.append(("Q3 선택지에 없는 값·자유 입력은 재확인", reasons(invalid) == {"attach_3": "선택지에 없는 값이에요. 아래에서 골라 주세요."}
                   and reasons(free) == {"attach_3": "입력한 내용으로는 판단하지 못했어요. 아래에서 골라 주세요."}))
    checks.append(("Q4 모두 답한 뒤에만 분리(답한 공종에만 조건)",
                   final["message"].startswith("1번 항목(레미콘 100m3 펌프차 32m 슬럼프 15cm)")))
    checks.append(("Q5 plan_items는 알 수 없는 답을 쓰지 않음", [q["name"] for q in plan_items(four, {"attach_2": "x", "attach_3": "y"})[1]]
                   == ["attach_2", "attach_3"]))

    # 모호한 공종: 관련 없는 절로 확정하지 않는다(단일·복수 공종)
    vague = CLIENT.post("/api/chat", json={"message": "콘크리트 100㎥"}).json()
    vague_work = next((q for q in vague["questions"] if q["name"] == "work"), {"choices": []})
    checks.append(("V1 '콘크리트 100㎥'은 관련 후보로 되묻기", vague["status"] == "MISSING_INFO" and vague_work["choices"]
                   and all("콘크리트" in choice or "레미콘" in choice or "타설" in choice for choice in vague_work["choices"])
                   and "구멍뚫기" not in vague["message"]))
    picked_choice = next((choice for choice in vague_work["choices"] if "6-1-1" in choice), None)
    if not picked_choice:
        print("  V1c 생략: 이 검색 색인에서는 6-1-1이 후보에 없음(전체 색인에서 검사)")
    else:
        picked = CLIENT.post("/api/chat", json={"thread_id": vague["thread_id"], "answers": {"work": picked_choice}}).json()
        checks.append(("V1c 공종을 고르면 질문에 쓴 물량은 다시 묻지 않음", "volume" not in [q["name"] for q in picked["questions"]]
                       and any(item["name"] == "volume" and item["value"] == "100" for item in picked["inputs"])))
    vague_bundle = CLIENT.post("/api/chat", json={"message": "콘크리트 100㎥, 자동문 3개소"}).json()
    checks.append(("V2 복수 공종에서도 1번 항목을 되묻기", vague_bundle["status"] == "MISSING_INFO"
                   and vague_bundle["message"].startswith("1번 항목(콘크리트 100m3)")
                   and any(q["name"] == "work" for q in vague_bundle["questions"])))
    lost = CLIENT.post("/api/chat", json={"message": "아까 거 다시 계산해줘 100㎥"}).json()
    # 검색 결과에 절이 아예 없으면 기존 '작업 절을 찾지 못했습니다' 경로가 먼저 처리한다(6장 검사 색인).
    checks.append(("V3 관련 후보가 없으면 찾지 못했다고 안내", lost["evidence"] == [] and (
                   (lost["status"] == "EVIDENCE_ONLY" and lost["message"].startswith("질문에 맞는 품셈 공종을 찾지 못했어요"))
                   or lost["message"].startswith("작업 절을 찾지 못했습니다"))))
    rule = CLIENT.post("/api/chat", json={"message": "높이가 8m이고 비계를 사용할 때 감산은 어떻게 하나요?"}).json()
    checks.append(("V4 품셈 규칙 질문은 기존 판정 유지", not rule["message"].startswith("질문에 맞는 품셈 공종을 찾지 못했어요")))

    # 첫 항목이 fill 전에 끝나도(명세 없음) 응답이 만들어진다
    early = collect({"items": [{"query": "자동문 3개소"}, {"query": "b"}], "item_index": 0, "query": "자동문 3개소",
                     "status": "EVIDENCE_ONLY", "reason": "계산 명세가 없습니다"})
    snapshot = early["items"][0]
    checks.append(("F1 fill 전 실패 항목도 응답 가능", snapshot["inputs"] == {} and snapshot["selection"] == {}
                   and _item_out(snapshot)["status"] == "EVIDENCE_ONLY"))

    # 7) 기존 동작
    too_many = CLIENT.post("/api/chat", json={"message": "레미콘 10㎥, 거푸집 20㎡, 철근 3톤, 비계 40㎡ 견적"}).json()
    checks.append(("L1 4개 이상은 안내", too_many["status"] == "BLOCKED" and "3개" in too_many["message"]))
    single = CLIENT.post("/api/chat", json={"message": "철근구조물 레미콘 인력운반 타설 150㎥"}).json()
    checks.append(("L2 단일 공종은 그대로", single["items"] == [] and single["status"] == "MISSING_INFO"
                   and not single["message"].startswith("1번 항목")))
    conditions = {"work_category": "도로", "duration": "1~6개월", "contractor_type": "종합건설업",
                  "project_scale": "이 견적만"}
    priced = {"reference_amounts": {"subtotals": {"재료비": "0", "노무비": "15000000", "경비": "0"},
                                    "total": "15000000"}, "rate_version": {}, "unpriced": [], "excluded": []}
    alone = calculate_cost_statement(priced, conditions, "2026-10-06")
    together = bundle({"items": [{"query": "a", "priced": priced}, {"query": "b", "priced": priced}],
                       "inputs": conditions, "basis_date": "2026-10-06"})
    safety = lambda statement: next(line["status"] for line in statement["lines"] if line["name"] == "산업안전보건관리비")
    checks.append(("L3 묶은 규모로 적용 기준 판정(1,500만×2)", safety(alone) == "제외"
                   and safety(together["statement"]) == "산정"))

    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
    passed = sum(bool(ok) for _, ok in checks)
    print(f"통과 {passed} / 전체 {len(checks)}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    with patch('backend.api.usage_limits.processing', return_value=nullcontext((None, 'fixture', False))), \
            patch('backend.api.usage_limits.consume', return_value={}), \
            patch('backend.api.usage_limits.status', return_value={}):
        raise SystemExit(main())
