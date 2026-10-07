"""복수 공종 부모 상태와 공종별 독립 계산(단계 B)을 구조화된 입력으로 검사한다.

오프라인 단어 검색·LLM 꺼짐. 운영 DB·유료 API를 쓰지 않는다. 운영 경로(build_graph)는 건드리지 않는다.
단일 항목 결과는 main 9a2af9f 기준 파일(evals/fixtures/baseline_main_9a2af9f.json)과 비교한다.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

os.environ["AGENT_OFFLINE"] = "1"
os.environ["AGENT_LLM"] = "off"
os.environ.pop("INDEX_CONFIG", None)  # 기준 파일과 같은 기본 색인
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

import backend.agent.estimate.flow as flow  # noqa: E402
from backend.agent.estimate.state import PlanError, choose_work, new_session, set_quantity, set_request_text  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402

BASIS = "2026-10-06"
BASELINE = json.loads((ROOT / "evals/fixtures/baseline_main_9a2af9f.json").read_text(encoding="utf-8"))
COMMON = {"work_category", "duration", "contractor_type", "project_scale"}
REBAR = "철근구조물 레미콘 인력운반 타설 150㎥"
PLAIN = "무근구조물 레미콘 인력운반 타설 50㎥"


def answer(session, picks: dict, only=None) -> dict:
    """현재 질문에 picks로 답한다. picks[필드] 또는 work 후보 일부 문자열."""
    answers = []
    for question in session["pending_questions"].values():
        if only and question["item_id"] not in only:
            continue
        field = question["field"]
        if field == "work":
            wanted = picks.get((question["item_id"], "work"), picks.get("work"))
            value = next((c for c in question["allowed_values"] if wanted and wanted in c), None)
        else:
            value = picks.get((question["item_id"], field), picks.get(field))
        if value is not None:
            answers.append({"question_id": question["question_id"], "version": question["version"], "value": value})
    return {"answers": answers}


def step(session, reply):
    return flow.run_items(flow.apply_answers(session, reply))


def values(item) -> dict:
    return {name: entry["value"] for name, entry in item["conditions"].items()}


def _norm_priced(priced: dict) -> dict:
    return {"status": priced.get("status"), "partial": priced.get("partial"), "unit_prices": priced.get("unit_prices"),
            "subtotals": priced.get("subtotals"), "total": priced.get("total"),
            "reference_amounts": priced.get("reference_amounts"),
            "lines": [{k: line.get(k) for k in ("name", "unit_price", "amount", "rate_code")} for line in priced.get("lines", [])],
            "unpriced": [u.get("name") for u in priced.get("unpriced", [])],
            "excluded": [u.get("name") for u in priced.get("excluded", [])],
            "rate_version": (priced.get("rate_version") or {}).get("id")}


def parity(scenario_id: str, request: str) -> tuple[bool, str]:
    """main에서 같은 답을 보낸 단일 공종을 항목 하나로 계산해 기준 결과와 비교한다."""
    steps = BASELINE["results"][scenario_id]
    sent = {}
    for item in steps:
        sent.update((item.get("op") or {}).get("answers") or {})
    final = [item["response"] for item in steps if "response" in item][-1]
    session = flow.run_items(new_session({"basis_date": BASIS, "items": [{"request_text": request}]}))
    for _ in range(8):
        if not session["pending_questions"]:
            break
        reply = {"answers": []}
        for question in session["pending_questions"].values():
            choices = question["allowed_values"] if isinstance(question["allowed_values"], list) else []
            value = sent.get(question["field"])
            if value is None:
                value = choices[0] if choices else "10"
            reply["answers"].append({"question_id": question["question_id"], "version": question["version"], "value": value})
        session = step(session, reply)
    item = session["items"]["i1"]
    main_inputs = {i["name"]: i["value"] for i in final["inputs"] if i["name"] not in COMMON}
    ours = values(item)
    if final["status"] in ("OK", "PARTIAL"):
        unit_lines = [{k: line.get(k) for k in ("kind", "name", "unit", "applied", "exact")}
                      for line in (item["computed_result"] or {}).get("unit_lines", [])]
        same = (item["status"] == "PRICED" and _norm_priced(item["priced_result"]) == final["priced"]
                and unit_lines == final["result"]["unit_lines"] and ours == main_inputs)
        return same, f"main {final['status']} 1단위 합계 {final['priced']['total']} / 현재 {item['status']} " \
                     f"{(item['priced_result'] or {}).get('total')}; 물량 기준 {(item['priced_result'] or {}).get('reference_amounts', {}).get('total')}"
    same = item["status"] == final["status"] and item["reason"] == final["message"] and ours == main_inputs
    return same, f"main {final['status']} / 현재 {item['status']}"


def main() -> int:
    checks: list[tuple[str, bool, str]] = []
    calls = {"retrieve": 0}
    original_retrieve = flow.retrieve

    def counting_retrieve(state):
        calls["retrieve"] += 1
        return original_retrieve(state)
    flow.retrieve = counting_retrieve

    # 1) 두 공종 조건의 독립 저장 + 공종 우선 질문
    two = flow.run_items(new_session({"basis_date": BASIS, "common_conditions": {"duration": "7~12개월"}, "items": [
        {"request_text": REBAR, "quantity": {"value": "150", "unit": "㎥"}},
        {"request_text": PLAIN, "quantity": {"value": "50", "unit": "㎥"}}]}))
    first_questions = sorted(two["pending_questions"])
    checks.append(("W1 공종 미확정이면 공종만 묻고 조건을 저장하지 않음",
                   first_questions == ["i1:work", "i2:work"]
                   and all(item["conditions"] == {} and not item["selected_spec_id"] for item in two["items"].values()), str(first_questions)))
    two = step(two, answer(two, {"work": "6-1-1"}))
    i1, i2 = two["items"]["i1"], two["items"]["i2"]
    checks.append(("I1 두 공종 조건이 각자 저장됨", values(i1).get("structure") == "철근구조물" and values(i1).get("volume") == "150"
                   and values(i2).get("structure") == "무근구조물" and values(i2).get("volume") == "50",
                   f"i1={values(i1)} / i2={values(i2)}"))
    checks.append(("I2 공통 조건은 세션에만", not (COMMON & set(i1["conditions"])) and not (COMMON & set(i2["conditions"]))
                   and two["common_conditions"] == {"duration": {"value": "7~12개월", "source": "plan", "explicit": True}},
                   f"common={two['common_conditions']}"))
    before_i2 = {qid: q["version"] for qid, q in two["pending_questions"].items() if qid.startswith("i2:")}
    partial = step(two, answer(two, {"scattered_small_volume": False, "concrete_supply": "관급"}, only={"i1"}))
    after_i2 = {qid: q["version"] for qid, q in partial["pending_questions"].items() if qid.startswith("i2:")}
    checks.append(("P1 일부 응답: i1만 계산되고 i2 질문은 그대로(같은 id·version)",
                   partial["items"]["i1"]["status"] == "PRICED" and before_i2 == after_i2 and after_i2, f"i2 질문 {after_i2}"))
    mixed = flow.apply_answers(partial, {"answers": [
        {"question_id": "i2:concrete_supply", "version": after_i2["i2:concrete_supply"], "value": "아무거나"},
        {"question_id": "i2:scattered_small_volume", "version": after_i2["i2:scattered_small_volume"], "value": False},
        {"question_id": "i1:concrete_supply", "version": "oldversion", "value": "사급"}]})
    mixed = flow.run_items(mixed)
    kinds = sorted(notice["kind"] for notice in mixed["notices"])
    reask = mixed["pending_questions"].get("i2:concrete_supply") or {}
    checks.append(("A1 한 요청의 여러 답: 유효한 답 반영, 잘못된 답 재질문, 오래된 답 안내",
                   kinds == ["invalid", "stale"] and values(mixed["items"]["i2"]).get("scattered_small_volume") is False
                   and reask.get("reason") == flow.INVALID and values(mixed["items"]["i1"]).get("concrete_supply") == "관급",
                   f"notices={kinds} 재질문 이유={reask.get('reason')}"))
    done = step(mixed, answer(mixed, {"concrete_supply": "관급"}))
    checks.append(("A2 모두 답하면 두 공종 계산 완료", all(item["status"] == "PRICED" for item in done["items"].values())
                   and not done["pending_questions"], str({k: v["status"] for k, v in done["items"].items()})))
    late = flow.answer_after_completion(done, {"answers": [{"question_id": "i2:concrete_supply", "version": "x", "value": "사급"}]})
    checks.append(("A3 완료된 견적의 오래된 답: 상태 유지 + 안내", late["items"] == done["items"] and not late["pending_questions"]
                   and late["notices"] and late["notices"][0]["kind"] == "stale", late["notices"][0]["message"] if late["notices"] else ""))

    # 2) 같은 필드(volume) 질문 두 개에 다른 답
    noqty = flow.run_items(new_session({"basis_date": BASIS, "items": [
        {"request_text": "철근구조물 레미콘 인력운반 타설"}, {"request_text": "무근구조물 레미콘 인력운반 타설"}]}))
    noqty = step(noqty, answer(noqty, {"work": "6-1-1"}))
    volume_questions = sorted(qid for qid in noqty["pending_questions"] if qid.endswith(":volume"))
    noqty = step(noqty, answer(noqty, {("i1", "volume"): "150", ("i2", "volume"): "50",
                                       "scattered_small_volume": False, "concrete_supply": "관급"}))
    refs = {k: (v["priced_result"] or {}).get("reference_amounts", {}).get("volume") for k, v in noqty["items"].items()}
    checks.append(("Q1 같은 volume 질문에 다른 답이 섞이지 않음", volume_questions == ["i1:volume", "i2:volume"]
                   and refs == {"i1": "150", "i2": "50"}, f"질문={volume_questions} 계산 물량={refs}"))

    # 3) 단위 검증: 100㎥를 개소 필드에 넣지 않음
    door = flow.run_items(new_session({"basis_date": BASIS, "items": [
        {"request_text": "자동문 설치", "quantity": {"value": "100", "unit": "㎥"}}]}))
    door = step(door, answer(door, {"work": "10-1-7"}))
    item = door["items"]["i1"]
    quantity_field = flow._quantity_field(load_specs()[item["selected_spec_id"]])
    question = door["pending_questions"].get(f"i1:{quantity_field['name']}") or {}
    checks.append(("U1 단위가 다른 물량은 넣지 않고 다시 묻기", item["status"] == "NEEDS_INPUT"
                   and quantity_field["name"] not in item["conditions"] and "맞지 않아요" in (question.get("reason") or ""),
                   f"{quantity_field['name']}({quantity_field.get('unit')}) 이유={question.get('reason')}"))
    door = step(door, answer(door, {quantity_field["name"]: "3"}))
    checks.append(("U2 이 공종 단위로 답하면 계산", door["items"]["i1"]["status"] == "PRICED"
                   and values(door["items"]["i1"]).get(quantity_field["name"]) == "3", door["items"]["i1"]["status"]))

    # 4) 캐시 무효화
    cached = copy.deepcopy(done)
    count = calls["retrieve"]
    i2_result = cached["items"]["i2"]["priced_result"]
    set_quantity(cached["items"]["i1"], "200", "㎥", "answer")
    cached = flow.run_items(cached)
    checks.append(("C1 물량 변경: 검색 재실행 없이 해당 공종만 재계산", calls["retrieve"] == count
                   and cached["items"]["i1"]["priced_result"]["reference_amounts"]["volume"] == "200"
                   and cached["items"]["i2"]["priced_result"] == i2_result, f"검색 호출 {calls['retrieve'] - count}회"))
    set_request_text(cached["items"]["i2"], "합판거푸집 설치 해체 300㎡")
    cached = flow.run_items(cached)
    new_item = cached["items"]["i2"]
    new_spec = load_specs()[new_item["selected_spec_id"]]
    new_quantity = flow._quantity_field(new_spec)
    checks.append(("C2 요청 문장 변경: 검색·선택·조건·결과를 다시 만듦(이전 물량 50㎥·레미콘 조건 없이 새 요청 기준)",
                   calls["retrieve"] == count + 1 and new_item["priced_result"] is None
                   and not {"structure", "placement_method", "scattered_small_volume", "concrete_supply"} & set(new_item["conditions"])
                   and new_item["conditions"].get(new_quantity["name"]) == {"value": "300", "source": "request", "explicit": True}
                   and new_quantity.get("unit") == "㎡" and cached["items"]["i1"]["status"] == "PRICED",
                   f"{new_spec['section_no']} {new_quantity['name']}({new_quantity.get('unit')})=300, 조건={values(new_item)}"))
    switch = copy.deepcopy(done)
    target = switch["items"]["i1"]
    target["explicit"]["scattered_small_volume"] = {"value": False, "source": "answer"}
    pump = next(c for c in load_specs().values() if c["section_no"] == "6-1-4")
    old_version = done["pending_questions"].get("i1:concrete_supply", {}).get("version") or "none"
    choose_work(target, {"decision": "chosen", "confirmed": True, "section_no": "6-1-4", "section": "공통 6-1-4"}, pump)
    switch = flow.run_items(switch)
    dropped = [entry["field"] for entry in switch["items"]["i1"].get("dropped_conditions", [])]
    checks.append(("C3 공종 변경: 새 명세에 없는 조건은 버리고 기록, 결과 무효화",
                   "scattered_small_volume" in dropped and switch["items"]["i1"]["priced_result"] is None
                   and switch["items"]["i1"]["status"] == "NEEDS_INPUT", f"버린 조건={dropped}"))
    stale = step(switch, {"answers": [{"question_id": "i1:concrete_supply", "version": old_version, "value": "관급"}]})
    checks.append(("S1 공종이 바뀐 뒤의 오래된 답: 적용하지 않고 현재 질문 안내", stale["notices"]
                   and stale["notices"][0]["kind"] == "stale" and stale["notices"][0]["current_questions"]
                   and stale["items"]["i1"]["status"] == "NEEDS_INPUT", str(stale["notices"][:1])))

    # 5) 공종 상태
    unsupported = flow.run_items(new_session({"basis_date": BASIS, "items": [{"request_text": REBAR}]}))
    no_spec = next((c for c in unsupported["items"]["i1"]["candidates"] if not c["has_spec"]), None)
    if no_spec:
        unsupported = step(unsupported, {"answers": [{"question_id": "i1:work",
                                                      "version": unsupported["pending_questions"]["i1:work"]["version"],
                                                      "value": no_spec["section"]}]})
    checks.append(("T1 명세 없는 공종 선택은 UNSUPPORTED와 사유", bool(no_spec) and unsupported["items"]["i1"]["status"] == "UNSUPPORTED"
                   and "명세" in unsupported["items"]["i1"]["reason"], unsupported["items"]["i1"]["reason"]))
    lost = flow.run_items(new_session({"basis_date": BASIS, "items": [{"request_text": "아까 거 다시 계산해줘 100㎥"}]}))
    checks.append(("T2 관련 후보가 없으면 NOT_FOUND와 사유", lost["items"]["i1"]["status"] == "NOT_FOUND"
                   and lost["items"]["i1"]["reason"], lost["items"]["i1"]["reason"][:40]))
    try:
        new_session({"items": [{"request_text": f"공종 {n} 10㎥"} for n in range(4)]})
        over = "통과됨"
    except PlanError as exc:
        over = str(exc)
    checks.append(("T3 4개 이상은 버리지 않고 범위 조정 요청", "3개 공종까지" in over and "공종 3" in over, over[:60]))

    # 6) 부모 그래프 중단·재개(공종별 대화 없음)
    saver = MemorySaver()
    graph = flow.build_estimate_graph(saver)
    config = {"configurable": {"thread_id": "estimate-1"}}
    state = graph.invoke({"plan": {"basis_date": BASIS, "items": [{"request_text": REBAR}, {"request_text": PLAIN}]}}, config)
    rounds = 0
    while graph.get_state(config).next and rounds < 6:
        session = graph.get_state(config).values["estimate"]
        state = graph.invoke(Command(resume=answer(session, {"work": "6-1-1", "scattered_small_volume": False,
                                                             "concrete_supply": "관급"})), config)
        rounds += 1
    threads = {item.config["configurable"]["thread_id"] for item in saver.list(None)}
    checks.append(("G1 부모 ask에서만 중단·재개, 대화 하나", not graph.get_state(config).next and threads == {"estimate-1"}
                   and all(item["status"] == "PRICED" for item in state["estimate"]["items"].values()),
                   f"재개 {rounds}회, thread={threads}"))

    # 8) 요청 전체 교체: 물량도 새 요청 기준
    def finish(session, picks):
        for _ in range(4):
            if not session["pending_questions"]:
                break
            session = step(session, answer(session, picks))
        return session
    picks = {"work": "6-1-1", "scattered_small_volume": False, "concrete_supply": "관급"}
    fresh50 = finish(flow.run_items(new_session({"basis_date": BASIS, "items": [
        {"request_text": "철근구조물 레미콘 인력운반 타설 50㎥"}]})), picks)
    expected50 = fresh50["items"]["i1"]["priced_result"]["reference_amounts"]
    replaced = copy.deepcopy(done)
    old_total = replaced["items"]["i1"]["priced_result"]["reference_amounts"]["total"]
    set_request_text(replaced["items"]["i1"], "철근구조물 레미콘 인력운반 타설 50㎥")
    replaced = finish(flow.run_items(replaced), picks)
    got = (replaced["items"]["i1"]["priced_result"] or {}).get("reference_amounts") or {}
    dropped_qty = [d for d in replaced["items"]["i1"].get("dropped_conditions", []) if d["field"] == "quantity"]
    checks.append(("R1 요청 교체(계획 물량 150 → 새 요청 50㎥): 계산 물량·금액이 새 요청과 같음",
                   got.get("volume") == "50" and got == expected50 and got.get("total") != old_total
                   and bool(dropped_qty) and dropped_qty[0]["value"] == "150",
                   f"교체 후 물량 {got.get('volume')} 금액 {got.get('total')} (단독 50㎥ {expected50['total']}, 이전 {old_total})"))
    answered_qty = copy.deepcopy(noqty)   # i1 물량은 사용자 답 150
    set_request_text(answered_qty["items"]["i1"], "철근구조물 레미콘 인력운반 타설 80㎥")
    answered_qty = finish(flow.run_items(answered_qty), picks)
    no_number = copy.deepcopy(noqty)
    set_request_text(no_number["items"]["i1"], "철근구조물 레미콘 인력운반 타설")
    no_number = flow.run_items(no_number)
    no_number = step(no_number, answer(no_number, picks))
    volume80 = answered_qty["items"]["i1"]["priced_result"]["reference_amounts"]["volume"]
    asked_again = sorted(q for q in no_number["pending_questions"] if q.startswith("i1:"))
    checks.append(("R2 이전 물량 답(150)과 새 요청이 다르면 새 요청 값, 물량 없는 요청이면 다시 묻기",
                   volume80 == "80" and "i1:volume" in asked_again and no_number["items"]["i1"]["quantity"] is None
                   and no_number["items"]["i2"]["status"] == "PRICED",
                   f"80㎥ 교체 물량={volume80}, 물량 없는 교체 질문={asked_again}"))
    planned = copy.deepcopy(done)
    set_request_text(planned["items"]["i1"], "철근구조물 레미콘 인력운반 타설", {"value": "70", "unit": "㎥"})
    planned = finish(flow.run_items(planned), picks)
    checks.append(("R3 새 계획 물량(70㎥)과 함께 교체, 다른 공종 결과 유지",
                   planned["items"]["i1"]["priced_result"]["reference_amounts"]["volume"] == "70"
                   and planned["items"]["i2"]["priced_result"] == done["items"]["i2"]["priced_result"],
                   planned["items"]["i1"]["priced_result"]["reference_amounts"]["total"]))

    # 9) 공종 ID 검증
    rejected = []
    for bad in ([{"item_id": "same", "request_text": REBAR}, {"item_id": "same", "request_text": PLAIN}],
                [{"item_id": 123, "request_text": REBAR}], [{"item_id": "a b", "request_text": REBAR}],
                [{"item_id": "common", "request_text": REBAR}], [{"item_id": "", "request_text": REBAR}]):
        try:
            new_session({"items": bad})
            rejected.append("")
        except PlanError as exc:
            rejected.append(str(exc))
    ordered = new_session({"items": [{"item_id": "b", "request_text": REBAR}, {"item_id": "a", "request_text": PLAIN}]})
    checks.append(("D1 중복·형식 오류 ID는 거부, 정상 ID는 순서 유지", all(rejected) and "중복" in rejected[0]
                   and ordered["item_order"] == ["b", "a"] and list(ordered["items"]) == ["b", "a"],
                   f"{rejected[0]} / 순서 {ordered['item_order']}"))

    # 10) 할증 확인(apply_adj_*) 질문 → 답 → 재계산 (실제 명세 6-1-5, 기존 API 검사 A37 E2와 같은 조건)
    epoxy = {"type": "신구-콘크리트 접착제바르기", "ceiling_applied": True, "scaffold_used": True,
             "floor_level": "지하층 및 1∼3층", "floor_level_19_plus": 19, "thickness_adjusted": False, "thickness": "1"}
    adj = flow.run_items(new_session({"basis_date": "2026-10-01", "items": [
        {"request_text": REBAR}, {"request_text": "에폭시 콘크리트 접착제 바르기 100㎡ 비용", "conditions": epoxy}]}))
    adj = step(adj, answer(adj, {("i1", "work"): "6-1-1", ("i2", "work"): "6-1-5"}))
    adj = step(adj, answer(adj, {"scattered_small_volume": False, "concrete_supply": "관급"}, only={"i1"}))
    adj_question = adj["pending_questions"].get("i2:apply_adj_2") or {}
    reply_with = lambda value: {"answers": [{"question_id": "i2:apply_adj_2", "version": adj_question.get("version"), "value": value}]}
    invalid_adj = flow.run_items(flow.apply_answers(adj, reply_with("모름")))
    yes = step(adj, reply_with("예"))
    no = step(adj, reply_with("아니오"))
    checks.append(("J1 할증 질문은 해당 공종(i2)에만, 선택지 예/아니오", adj_question.get("allowed_values") == ["예", "아니오"]
                   and not [q for q in adj["pending_questions"] if q.startswith("i1:")] and adj["items"]["i1"]["status"] == "PRICED",
                   f"질문={sorted(adj['pending_questions'])}"))
    checks.append(("J2 할증 답 '예' → 재계산(1단위 합계 39,396원, 기존 API 검사와 같음)",
                   yes["items"]["i2"]["status"] == "PRICED" and yes["items"]["i2"]["priced_result"]["total"] == "39396"
                   and not yes["pending_questions"] and yes["items"]["i1"]["priced_result"] == adj["items"]["i1"]["priced_result"],
                   f"i2 {yes['items']['i2']['status']} {(yes['items']['i2']['priced_result'] or {}).get('total')}"))
    no_memos = (no["items"]["i2"]["computed_result"] or {}).get("adjustment_memos", [])
    yes_memos = (yes["items"]["i2"]["computed_result"] or {}).get("adjustment_memos", [])
    # 1~3층은 비계 할증률이 0%라 금액은 같다. 답이 계산에 들어갔는지는 '미적용' 메모로 확인한다.
    checks.append(("J3 할증 답 '아니오'가 계산에 반영(미적용 메모), 잘못된 값은 재질문",
                   no["items"]["i2"]["status"] == "PRICED" and not no["pending_questions"]
                   and any("미적용" in memo for memo in no_memos) and not any("미적용" in memo for memo in yes_memos)
                   and invalid_adj["pending_questions"].get("i2:apply_adj_2", {}).get("reason") == flow.INVALID,
                   f"아니오 → {no['items']['i2']['priced_result']['total']}원, 메모 {no_memos[:1]}"))

    # 11) 모의 계산: 부모 질문·답 연결, 질문 없는 입력 대기는 완료가 아님
    real_compute = flow.compute

    def mock_adjust(state):
        if "apply_adj_9" not in state["inputs"]:
            return {"status": "MISSING_INFO", "reason": "할증 적용 여부를 확인해 주세요",
                    "questions": [{"name": "apply_adj_9", "ask": "모의 할증을 적용할까요?", "choices": ["예", "아니오"]}]}
        return real_compute(state)
    flow.compute = mock_adjust
    mocked = finish(flow.run_items(new_session({"basis_date": BASIS, "items": [{"request_text": REBAR}]})),
                    {**picks, "apply_adj_9": "예"})
    flow.compute = lambda state: {"status": "MISSING_INFO", "reason": "질문 없음", "questions": []}
    broken = finish(flow.run_items(new_session({"basis_date": BASIS, "items": [{"request_text": REBAR}]})), picks)
    flow.compute = real_compute
    checks.append(("K1 모의 할증 질문: 부모 질문 i1:apply_adj_9 → 답 → 계산",
                   mocked["items"]["i1"]["status"] == "PRICED"
                   and mocked["items"]["i1"]["conditions"].get("apply_adj_9", {}).get("value") == "예"
                   and mocked["items"]["i1"]["priced_result"]["reference_amounts"] == done["items"]["i1"]["priced_result"]["reference_amounts"],
                   mocked["items"]["i1"]["status"]))
    checks.append(("K2 질문 없는 입력 대기는 완료(PRICED)로 넘기지 않음", broken["items"]["i1"]["status"] == "ERROR"
                   and broken["items"]["i1"]["priced_result"] is None
                   and any(d.get("error") == "needs_input_without_question" for d in broken["diagnostics"]),
                   broken["items"]["i1"]["reason"]))

    # 7) 항목 하나일 때 main 기준과 같은 결과
    for scenario_id, request in [("single-readymix-rebar", REBAR), ("single-readymix-plain", PLAIN),
                                 ("single-pump", "철근콘크리트 벽체 260㎥ 32m 펌프차로 타설 비용"),
                                 ("single-pump-private-mix", "철근콘크리트 벽체 260㎥ 32m 펌프차로 타설 비용"),
                                 ("single-pump-blocked", "철근콘크리트 벽체 260㎥ 32m 펌프차로 타설 비용"),
                                 ("single-autodoor", "자동문 3개소 설치하면 공사비 얼마 나와?"),
                                 ("single-doorlock", "도어록 50개소 설치 노무비가 얼마야"),
                                 ("single-shutter", "셔터 설치 5개소 비용 계산 부탁"),
                                 ("single-floorhinge", "플로어힌지 20개 설치 공사비 산출해줘"),
                                 ("single-rebar-coupler", "철근 기계적 이음 30개소 원가계산서 뽑아줘"),
                                 ("single-paint", "수성페인트 붓칠 500㎡ 견적 좀 뽑아줘"),
                                 ("single-epoxy", "에폭시 접착제 바르기 비용 얼마야?"),
                                 ("single-plywood-form", "합판거푸집 1,200㎡ 설치 해체 인건비 계산해줘")]:
        same, detail = parity(scenario_id, request)
        checks.append((f"M {scenario_id} main과 같은 공종·입력·계산", same, detail))

    flow.retrieve = original_retrieve
    for name, ok, detail in checks:
        print(("PASS " if ok else "FAIL ") + name + (f"  — {detail}" if detail else ""))
    passed = sum(bool(ok) for _, ok, _ in checks)
    print(f"통과 {passed} / 전체 {len(checks)}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
