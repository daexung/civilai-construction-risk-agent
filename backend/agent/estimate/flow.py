"""공종별 계산(run_item)과 부모 견적 흐름(build_estimate_graph).

공종 계산은 기존 단일 공종 노드(retrieve·select·fill·gate·compute·price)를 코드 수정 없이 감싼다.
- 공종이 확정되기 전에는 fill을 실행하지 않는다. 미확정 후보 명세로 조건·기본값을 만들거나 저장하지 않고
  공종 질문만 만든다.
- 공종이 확정되면 원래 요청에서 그 명세의 조건을 읽고, 사용자가 준 값(explicit)을 그 위에 덮는다.
- 공종별로 원가계산서(statement)는 만들지 않는다. 합산은 다음 단계(C)에서 부모가 한다.
- 질문은 부모 그래프의 ask에서만 중단한다. 공종 계산은 질문을 데이터로 돌려준다.

운영 경로(backend/agent/graph.py의 build_graph)는 이 파일을 쓰지 않는다.
"""

from __future__ import annotations

import copy
from fractions import Fraction
from typing import TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from backend.agent.estimate.aggregate import aggregate
from backend.agent.estimate.state import (COMMON_FIELDS, SETTLED, EstimateItem, EstimateSession, choose_work,
                                          new_session, question_version, set_explicit, set_quantity, unit_key)
from backend.agent.nodes.compute import compute
from backend.agent.nodes.fill import _common_fields, _format_rational, _valid_for_field, extract_inputs, fill
from backend.agent.nodes.gate import gate
from backend.agent.nodes.price import price
from backend.agent.nodes.retrieve import retrieve
from backend.agent.nodes.select import select
from backend.agent.rules.specs import load_specs, specs_by_section

STALE = "이전 질문에 대한 답이에요. 지금 확인이 필요한 질문을 다시 확인해 주세요."
INVALID = "선택지에 없는 값이에요. 아래에서 골라 주세요."


# ---- 공종 계산 ----

def _spec_for(candidate: dict) -> dict | None:
    entries = specs_by_section().get((candidate.get("division", "공통"), candidate["section_no"]))
    return entries[0] if entries else None


def _quantity_field(spec: dict) -> dict | None:
    name = spec["quantity_model"]["params"].get("quantity_input")
    return next((field for field in spec["inputs"] if field["name"] == name), None)


def _common_inputs(session: EstimateSession, spec: dict | None) -> dict:
    """세션 공통 조건 + 기본값. 공사 종류 기본값은 기존 fill처럼 명세 부문을 따른다."""
    values = {name: entry["value"] for name, entry in session["common_conditions"].items()}
    for field in _common_fields():
        if field["name"] not in values:
            if field["name"] == "work_category" and spec:
                values["work_category"] = "주택 외 건축" if spec["division"] in ("건축", "기계설비") else "기타 토목공사"
            else:
                values[field["name"]] = field["default"]
    return values


def _work_question(item: EstimateItem) -> dict:
    choices = [candidate["section"] for candidate in item["candidates"]]
    return {"question_id": f"{item['item_id']}:work", "version": question_version(item["item_id"], "work", choices),
            "scope": "item", "item_id": item["item_id"], "field": "work", "kind": "work", "allowed_values": choices,
            "required": True, "ask": "어느 공종으로 계산할까요?", "reason": item["question_reasons"].get("work")}


def _field_question(item: EstimateItem, raw: dict) -> dict:
    choices = raw.get("choices")
    return {"question_id": f"{item['item_id']}:{raw['name']}",
            "version": question_version(item["item_id"], raw["name"], item["selected_spec_id"], choices),
            "scope": "item", "item_id": item["item_id"], "field": raw["name"],
            "kind": "choice" if isinstance(choices, list) else "value", "allowed_values": choices,
            "required": not raw.get("optional", False), "ask": raw["ask"],
            "reason": item["question_reasons"].get(raw["name"]) or raw.get("reason"),
            **({"labels": raw["labels"]} if raw.get("labels") else {}),
            **({"hint": raw["hint"]} if raw.get("hint") else {})}


def _build_conditions(item: EstimateItem, spec: dict) -> tuple[dict, str | None]:
    """확정 명세 기준 조건: 원래 요청에서 읽은 값 ← 사용자 값(explicit). 물량은 단위가 맞을 때만 넣는다."""
    stated, _ = extract_inputs(item["request_text"], spec)
    fields = {field["name"] for field in spec["inputs"]}
    conditions = {name: {"value": value, "source": "request", "explicit": True}
                  for name, value in stated.items() if name in fields}
    quantity_field = _quantity_field(spec)
    mismatch = None
    if quantity_field:
        conditions.pop(quantity_field["name"], None)  # 물량은 아래 단위 검증을 거친 값만 쓴다
        quantity = item.get("quantity")
        if quantity is None and quantity_field["name"] in stated:
            quantity = {"value": stated[quantity_field["name"]], "unit": quantity_field.get("unit"), "source": "request"}
        if quantity:
            if unit_key(quantity["unit"]) and unit_key(quantity["unit"]) == unit_key(quantity_field.get("unit")):
                conditions[quantity_field["name"]] = {"value": quantity["value"], "source": quantity["source"], "explicit": True}
            else:
                mismatch = (f"요청 물량 {quantity['value']}{quantity['unit']}는 이 공종의 물량 단위"
                            f"({quantity_field.get('unit') or '알 수 없음'})와 맞지 않아요. 이 단위로 물량을 알려 주세요.")
    definitions = {field["name"]: field for field in spec["inputs"]}
    for name, entry in item["explicit"].items():
        if quantity_field and name == quantity_field["name"]:
            continue
        if name.startswith("apply_adj_") or (name in fields and _valid_for_field(entry["value"], definitions[name])):
            conditions[name] = {"value": entry["value"], "source": entry["source"], "explicit": True}
        elif name in fields:  # 형식이 틀린 사용자 값은 계산에 쓰지 않고 다시 묻는다
            conditions.pop(name, None)
            item["question_reasons"].setdefault(name, "받은 값이 이 공종의 선택지와 맞지 않아요. 다시 골라 주세요.")
    return conditions, mismatch


def run_item(item: EstimateItem, session: EstimateSession) -> EstimateItem:
    """공종 하나를 진행할 수 있는 데까지 진행한다. 자기 상태만 바꿔서 돌려준다."""
    item = copy.deepcopy(item)
    item["questions"] = []
    if item["status"] in SETTLED and item.get("result_revision") == item["input_revision"]:
        return item
    if item["hits"] is None:
        item["hits"] = retrieve({"query": item["request_text"]})["hits"]
    if item["selection"] is None:
        decided = select({"hits": item["hits"], "query": item["request_text"]})
        item["candidates"] = decided["candidates"]
        decision = decided["selection"]["decision"]
        if decision == "chosen":
            top = item["candidates"][0]
            choose_work(item, {"decision": "chosen", "confirmed": True, "section_no": top["section_no"],
                               "section": top["section"]}, load_specs()[decided["spec_id"]])
        elif decision == "provisional" and item["candidates"]:
            item["selection"] = {"decision": "provisional", "confirmed": False}
        elif decision == "no_spec":
            item["selection"] = decided["selection"]
            item.update(status="UNSUPPORTED", reason=decided["selection"]["reason"], result_revision=item["input_revision"])
            return item
        else:
            item["selection"] = decided["selection"]
            item.update(status="NOT_FOUND", reason=decided.get("reason") or decided["selection"]["reason"],
                        result_revision=item["input_revision"])
            return item
    if not item["selection"].get("confirmed"):
        # 공종 미확정: 후보 명세로 조건을 만들지 않고 공종만 묻는다.
        item.update(status="NEEDS_WORK", reason="공종을 확인해야 해요.", questions=[_work_question(item)], conditions={})
        return item
    spec = load_specs().get(item["selected_spec_id"])
    if spec is None:
        item.update(status="UNSUPPORTED", reason=f"{item['selection'].get('section_no')} 절의 계산 명세가 없습니다",
                    result_revision=item["input_revision"])
        return item
    conditions, mismatch = _build_conditions(item, spec)
    item["conditions"] = conditions
    values = {**_common_inputs(session, spec), **{name: entry["value"] for name, entry in conditions.items()}}
    work_state = {"query": item["request_text"], "spec_id": spec["id"], "selection": item["selection"],
                  "candidates": item["candidates"], "inputs": dict(values), "input_sources": {}, "reply": "",
                  "basis_date": session.get("basis_date")}
    asked = fill(work_state).get("questions", [])
    quantity_field = _quantity_field(spec)
    # 사용자가 유효하게 답한 조건은 원문 해석이 모호해도 다시 묻지 않는다(형식이 틀린 답은 다시 묻는다).
    answered = {name for name, entry in conditions.items() if entry["source"] not in ("request",)}
    asked = [question for question in asked if question["name"] not in answered]
    if mismatch and quantity_field and not any(q["name"] == quantity_field["name"] for q in asked):
        asked.insert(0, {"name": quantity_field["name"], "ask": quantity_field["ask"], "choices": None})
    if mismatch:
        item["question_reasons"].setdefault(quantity_field["name"], mismatch)
    if asked:
        item.update(status="NEEDS_INPUT", reason="조건을 확인해야 해요.",
                    questions=[_field_question(item, question) for question in asked])
        return item
    state = {"spec_id": spec["id"], "inputs": values, "basis_date": session.get("basis_date")}
    try:
        gated = gate(state)
        if gated.get("status") == "BLOCKED":
            item.update(status="BLOCKED", reason=gated["reason"], computed_result=gated["result"],
                        result_revision=item["input_revision"])
            return item
        computed = compute(state)
        if computed["status"] == "MISSING_INFO":
            item.update(status="NEEDS_INPUT", reason=computed["reason"],
                        questions=[_field_question(item, question) for question in computed["questions"]
                                   if question["name"] not in answered])
            return item
        if computed["status"] != "COMPUTED":
            item.update(status="BLOCKED" if computed["status"] == "BLOCKED" else "ERROR", reason=computed["reason"],
                        computed_result=computed.get("result"), result_revision=item["input_revision"])
            return item
        priced = price({**state, "result": computed["result"]})
    except Exception as exc:  # 한 공종의 오류가 다른 공종을 막지 않는다
        item.update(status="ERROR", reason=f"{type(exc).__name__}: {str(exc)[:200]}", result_revision=item["input_revision"])
        return item
    item.update(status="PRICED", reason="", computed_result=computed["result"], priced_result=priced["priced"],
                result_revision=item["input_revision"], review_status=gated.get("review_status", ""))
    return item


def run_items(session: EstimateSession) -> EstimateSession:
    """공종을 순서대로 진행하고, 남은 질문을 모은다. 바뀌지 않은 질문은 같은 id·version을 유지한다."""
    session = copy.deepcopy(session)
    pending = {}
    for item_id in session["item_order"]:
        item = run_item(session["items"][item_id], session)
        if item["status"] in ("NEEDS_WORK", "NEEDS_INPUT", "READY") and not item["questions"]:
            # 입력이 필요하다면서 물을 질문이 없으면 완료로 넘기지 않는다.
            item.update(status="ERROR", reason="확인할 질문 없이 입력 대기 상태가 되어 계산을 멈췄어요.",
                        result_revision=item["input_revision"])
            session["diagnostics"].append({"item_id": item_id, "error": "needs_input_without_question"})
        session["items"][item_id] = item
        pending.update({question["question_id"]: question for question in item["questions"]})
    session["pending_questions"] = pending
    return session


def session_complete(session: EstimateSession) -> bool:
    """모든 공종이 끝난 상태(계산·미지원·보류·오류)이고 남은 질문이 없을 때만 완료다."""
    return not session["pending_questions"] and all(
        item["status"] in SETTLED and item.get("result_revision") == item["input_revision"]
        for item in session["items"].values())


# ---- 답 적용 ----

def _normalize_answer(question: dict, value, spec: dict | None):
    """선택지·형식이 맞으면 저장할 값, 아니면 None."""
    field = question["field"]
    if field == "work":
        # 기존 fill과 같이 절 제목 전체 또는 겹치지 않는 절 번호를 받는다.
        if value in question["allowed_values"]:
            return value
        matches = [choice for choice in question["allowed_values"]
                   if str(choice).split(" ")[1:2] == [str(value)] or str(choice).startswith(f"{value} ")]
        return matches[0] if len(matches) == 1 else None
    if field.startswith("apply_adj_"):
        return value if value in ("예", "아니오") else None
    definition = next((f for f in (spec or {}).get("inputs", []) if f["name"] == field), None)
    if definition is None:
        return None
    if definition.get("labels") and value not in definition.get("allowed_values", []):
        matches = [raw for raw, label in definition["labels"].items() if label == value]
        value = matches[0] if len(matches) == 1 else value
    if not _valid_for_field(value, definition):
        return None
    if definition["type"] in ("positive_rational", "positive_currency") and value != "모름":
        return _format_rational(Fraction(str(value).replace(",", "")))
    return value


def apply_answers(session: EstimateSession, reply: dict) -> EstimateSession:
    """한 요청의 답을 같은 상태 기준으로 모두 검증한 뒤, 유효한 답을 함께 반영한다.

    - 현재 질문과 id·version이 같은 답만 적용한다. 다른 질문의 답은 다른 공종 질문을 무효화하지 않는다.
    - 선택지에 없는 답은 반영하지 않고 이유와 함께 다시 묻는다.
    - 오래된 질문의 답은 적용하지 않고 notices에 남긴다. 완료된 견적의 상태는 바꾸지 않는다.
    """
    session = copy.deepcopy(session)
    session["notices"] = []
    snapshot = session["pending_questions"]
    valid: dict[str, list] = {}
    for answer in reply.get("answers", []):
        qid, version, value = answer.get("question_id"), answer.get("version"), answer.get("value")
        question = snapshot.get(qid)
        if question is None or question["version"] != version:
            current = [q["question_id"] for q in snapshot.values()
                       if q["item_id"] == (question or {}).get("item_id", qid.split(":")[0])]
            session["notices"].append({"kind": "stale", "question_id": qid, "message": STALE, "current_questions": current})
            session["diagnostics"].append({"stale_answer": qid, "version": version})
            continue
        if question.get("scope") == "common":
            # 공통 공사 조건 답: 공종 계산은 그대로 두고 세션 공통 조건만 바꾼다(원가계산서만 다시 만든다).
            definition = next(field for field in _common_fields() if field["name"] == question["field"])
            if value in (question["allowed_values"] or []) and _valid_for_field(value, definition):
                session["common_conditions"][question["field"]] = {"value": value, "source": "answer", "explicit": True}
                session["revision"] += 1
            else:
                session["notices"].append({"kind": "invalid", "question_id": qid, "message": INVALID})
            continue
        item = session["items"][question["item_id"]]
        spec = load_specs().get(item["selected_spec_id"])
        normalized = _normalize_answer(question, value, spec)
        if normalized is None:
            item["question_reasons"][question["field"]] = INVALID
            session["notices"].append({"kind": "invalid", "question_id": qid, "message": INVALID})
            continue
        valid.setdefault(question["item_id"], []).append((question, normalized))
    for item_id, answers in valid.items():
        item = session["items"][item_id]
        for question, value in answers:
            if question["field"] == "work":
                candidate = next(c for c in item["candidates"] if c["section"] == value)
                choose_work(item, {"decision": "chosen", "confirmed": True, "section_no": candidate["section_no"],
                                   "section": candidate["section"]}, _spec_for(candidate))
                if not item["selected_spec_id"]:
                    item.update(status="UNSUPPORTED", reason=f"{candidate['section_no']} 절의 계산 명세가 없습니다",
                                result_revision=item["input_revision"])
            else:
                spec = load_specs()[item["selected_spec_id"]]
                quantity_field = _quantity_field(spec)
                if quantity_field and question["field"] == quantity_field["name"]:
                    set_quantity(item, value, quantity_field.get("unit"), "answer")
                    item["question_reasons"].pop(question["field"], None)
                else:
                    set_explicit(item, question["field"], value, "answer")
    if valid:
        session["revision"] += 1
    return session


# ---- 부모 그래프 ----

class EstimateGraphState(TypedDict, total=False):
    plan: dict
    estimate: EstimateSession
    reply: dict


def _load_plan(state: EstimateGraphState) -> dict:
    return {} if state.get("estimate") else {"estimate": new_session(state["plan"])}


def _run(state: EstimateGraphState) -> dict:
    return {"estimate": run_items(state["estimate"])}


def _aggregate(state: EstimateGraphState) -> dict:
    return {"estimate": aggregate(state["estimate"])}


def _ask(state: EstimateGraphState) -> dict:
    reply = interrupt({"estimate_id": state["estimate"]["estimate_id"],
                       "questions": list(state["estimate"]["pending_questions"].values()),
                       "notices": state["estimate"].get("notices", [])})
    return {"reply": reply}


def _apply(state: EstimateGraphState) -> dict:
    return {"estimate": apply_answers(state["estimate"], state.get("reply") or {}), "reply": {}}


def _after_run(state: EstimateGraphState) -> str:
    return "ask" if state["estimate"]["pending_questions"] else END


def build_estimate_graph(checkpointer=None):
    """부모 견적 흐름. 질문은 여기 ask에서만 중단·재개한다. 공종마다 별도 대화를 만들지 않는다."""
    graph = StateGraph(EstimateGraphState)
    graph.add_node("load_plan", _load_plan)
    graph.add_node("run_items", _run)
    graph.add_node("aggregate", _aggregate)
    graph.add_node("ask", _ask)
    graph.add_node("apply_answers", _apply)
    graph.add_edge(START, "load_plan")
    graph.add_edge("load_plan", "run_items")
    graph.add_edge("run_items", "aggregate")
    graph.add_conditional_edges("aggregate", _after_run, {"ask": "ask", END: END})
    graph.add_edge("ask", "apply_answers")
    graph.add_edge("apply_answers", "run_items")
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else MemorySaver())


def answer_after_completion(session: EstimateSession, reply: dict) -> EstimateSession:
    """이미 완료된 견적에 답이 들어오면 상태를 바꾸지 않고 안내만 남긴다."""
    if session["pending_questions"]:
        return aggregate(run_items(apply_answers(session, reply)))
    session = copy.deepcopy(session)
    session["notices"] = [{"kind": "stale", "question_id": answer.get("question_id"),
                           "message": "이미 계산이 끝난 견적이에요. 이 답은 반영하지 않았어요.", "current_questions": []}
                          for answer in reply.get("answers", [])]
    return session
