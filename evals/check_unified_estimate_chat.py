"""Offline checks for unified single/multi-item Dialogue, question scope, and export.

All retrieval is mocked at the production tools.retrieve call site. No trial API,
local query cache, model, embedding client, remote DB, or loopback server is used.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch
from io import BytesIO
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")

from openpyxl import load_workbook  # noqa: E402
from backend.agent.estimate import aggregate as aggregate_module, dialogue, scope, tools  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.api import dialogue_service  # noqa: E402
from backend.api.tables import build_xlsx  # noqa: E402
from backend.api.main import ChatRequest, _uses_dialogue  # noqa: E402
from backend.agent.tools.source import citation  # noqa: E402


TEXT = "수성페인트 롤러칠 100㎡ + 실내 방수 20㎡ 비용 견적"


def _mock_hit(query: str) -> dict:
    wanted = "6-4-3" if "방수" in query else "11-2-2"
    spec = next(value for value in load_specs().values() if value["section_no"] == wanted)
    return {"rank": 1, "section_no": spec["section_no"], "division": spec["division"],
            "section": f"{spec['section_no']} {spec['title']}", "page": 200,
            "table_id": None, "text": spec["title"], "chunk_id": "mock-production-retrieve"}


def main() -> None:
    free_state = {"free_card_answers": 0, "pending": [
        {"field": "field", "ref": "field@v@1"}]}
    with patch.object(dialogue_service.dialogue, "load", return_value=free_state):
        for paid_field in ("scope::s1_2", "scope_owner::c3_4", "item::continue"):
            assert not dialogue_service.free_card_answer(object(), "offline", {
                "answers": {paid_field: "yes"}, "refs": {paid_field: "ref"}})
        assert dialogue_service.free_card_answer(object(), "offline", {
            "answers": {"field": "yes"}, "refs": {"field": "field@v@1"}})
    print("PASS scope, owner, and continue cards are chargeable; ordinary condition cards stay free")

    analysis = scope.analyze_request(TEXT)
    questions = dialogue._scope_questions(analysis, 1)
    assert len(analysis["work_items"]) == 2 and len(questions) == 2, (analysis, questions)
    first = dialogue.run_turn(dialogue.new_dialogue(), {"message": TEXT})
    assert not first.get("session") and len(first["pending"]) == 2
    retrieve_calls = []
    def retrieve_mock(state: dict) -> dict:
        retrieve_calls.append(state["query"])
        return {"hits": [_mock_hit(state["query"])], "search_info": {"method": "mock-production-retrieve",
                "api_calls": 0, "warnings": []}}

    graph = dialogue.build_dialogue_graph()
    thread_id = "unified-offline-test"
    with patch.object(tools, "retrieve", side_effect=retrieve_mock) as retrieval_spy, \
            patch.object(citation, "_pages", return_value=defaultdict(lambda: {"printed_page": None, "division": None})), \
            patch.object(aggregate_module, "calculate_cost_statement",
                         wraps=aggregate_module.calculate_cost_statement) as statement_spy:
        scoped = dialogue_service.respond(graph, thread_id, {"message": TEXT})
        scope_answers = {question["name"]: "계산에 포함" for question in scoped["questions"]}
        scope_refs = {question["name"]: question["ref"] for question in scoped["questions"]}
        confirmed = dialogue_service.respond(graph, thread_id,
                    {"answers": scope_answers, "refs": scope_refs})
        dialogue_service.restore(graph, thread_id)
        saved = dialogue.load(graph, thread_id)
        assert len(retrieve_calls) == 2 and retrieval_spy.call_count == 2, (retrieve_calls, scoped, confirmed, dialogue.load(graph, thread_id))
        assert len(saved["session"]["item_order"]) == 2
        assert confirmed["llm_info"]["tool_calls"] <= dialogue.MAX_TOOL_CALLS
        item_ids = list(saved["session"]["item_order"])
        assert item_ids == [f"i{row['evidence']['start']}_{row['evidence']['end']}"
                            for row in sorted(analysis["work_items"], key=lambda row: row["evidence"]["start"])]
        assert saved["pending"] and all("::" in q["field"] for q in saved["pending"])

    # Same question fields on the two trades must have distinct refs. A swapped
        # cross-item ref is rejected and leaves both item revisions unchanged.
        assert all("::" in question["field"] for question in saved["pending"])
        before_revisions = {key: saved["session"]["items"][key]["input_revision"] for key in item_ids}
        source_question = next(question for question in saved["pending"] if question["item_id"] == item_ids[0])
        foreign_field = f"{item_ids[1]}::{source_question['field'].split('::', 1)[1]}"
        swapped_answers = {foreign_field: source_question["choices"][0] if source_question.get("choices") else "1"}
        swapped_refs = {foreign_field: source_question["ref"]}
        rejected = dialogue_service.respond(graph, thread_id, {"answers": swapped_answers, "refs": swapped_refs})
        rejected_state = dialogue.load(graph, thread_id)
        assert "반영하지 않았어요" in rejected["answer"]
        assert before_revisions == {key: rejected_state["session"]["items"][key]["input_revision"] for key in item_ids}

        # Use the fresh refs from the restored checkpoint; choose the first valid
        # server-provided option (or a bounded numeric value for free-entry fields).
        current = rejected_state
        for _ in range(8):
            if not current.get("pending"):
                break
            answers, refs = {}, {}
            for question in current["pending"]:
                field = question["field"]
                if field.endswith("::continue"):
                    value = "계속 진행"
                elif question.get("choices"):
                    value = question["choices"][0]
                else:
                    local = field.split("::", 1)[-1]
                    value = {"coat_count": "2", "floor_count": "1", "building_height": "3",
                             "quantity": "10", "thickness": "10mm"}.get(local, "1")
                answers[field] = value
                refs[field] = question["ref"]
            resumed = dialogue_service.respond(graph, thread_id, {"answers": answers, "refs": refs})
            assert resumed["llm_info"]["tool_calls"] <= dialogue.MAX_TOOL_CALLS
            current = dialogue.load(graph, thread_id)
        assert not current.get("pending"), current.get("pending")
        final_session = current["session"]
        assert all(final_session["items"][item_id]["status"] == "PRICED" for item_id in item_ids)
        assert final_session["statement"] and final_session["aggregate_result"]["direct_total"] > 0
        assert statement_spy.call_count == 1, statement_spy.call_count

        single_thread = "unified-single-offline-test"
        single_text = "실내 방수 20㎡ 비용 견적"
        single_first = dialogue_service.respond(graph, single_thread, {"message": single_text})
        single_answers = {q["name"]: "계산에 포함" for q in single_first["questions"]}
        single_refs = {q["name"]: q["ref"] for q in single_first["questions"]}
        single_done = dialogue_service.respond(graph, single_thread,
                         {"answers": single_answers, "refs": single_refs})
        single_state = dialogue.load(graph, single_thread)
        assert single_state["unified_estimate"] and len(single_state["session"]["item_order"]) == 1
        assert single_done["llm_info"]["tool_calls"] <= dialogue.MAX_TOOL_CALLS
        assert len(retrieve_calls) >= 3
        print("PASS one-item requests use the same scope/session/item runner")

        response = dialogue_service.response(thread_id, current)
        assert len(response["multi_trade_items"]) == 2
        assert response["result"] is None and response["priced"] is None
        assert all(item.get("priced") and item.get("labor") is not None
                   and item.get("result") and item.get("tables")
                   and "not_calculated_scope" in item for item in response["multi_trade_items"])
        workbook = load_workbook(BytesIO(build_xlsx(response)), data_only=True)
        detail_rows = list(workbook["공종별상세"].iter_rows(min_row=5, values_only=True))
        assert [row[0] for row in detail_rows] == item_ids, detail_rows
        by_id = {item["item_id"]: item for item in response["multi_trade_items"]}
        assert all(float(row[7]) == float(by_id[row[0]]["priced"]["reference_amounts"]["total"])
                   for row in detail_rows), [(row, by_id[row[0]]["priced"]["reference_amounts"]) for row in detail_rows]
        print("PASS scope cards, distinct trade IDs, composite refs, and cross-item rejection")
        print("PASS mocked production retrieve call site used twice; no trial/cache/model/embedding/DB")
        print("PASS both trade calculations feed one shared cost statement and ordered XLSX rows")

        # An untargeted edit asks for a target. The chosen item is edited in place,
        # the sibling result remains untouched, and the aggregate is recalculated once.
        before_items = {item_id: final_session["items"][item_id] for item_id in item_ids}
        target_reply = dialogue_service.respond(graph, thread_id, {"message": "물량 101㎡로 바꿔"})
        target_q = next(q for q in target_reply["questions"] if q["name"] == "target_item")
        chosen_label = next(choice for choice in target_q["choices"] if "수성페인트" in choice)
        edited = dialogue_service.respond(graph, thread_id,
                    {"answers": {"target_item": chosen_label}, "refs": {"target_item": target_q["ref"]}})
        edited_state = dialogue.load(graph, thread_id)
        paint_id = next(item_id for item_id in item_ids if "수성페인트" in
                        edited_state["session"]["items"][item_id]["request_text"])
        sibling_id = next(item_id for item_id in item_ids if item_id != paint_id)
        assert edited_state["session"]["items"][paint_id]["quantity"]["value"] == "101"
        assert edited_state["session"]["items"][sibling_id]["computed_result"] == before_items[sibling_id]["computed_result"]
        assert edited_state["session"]["statement"] and edited_state["session"]["aggregate_result"]["direct_total"] > 0
        after_revisions = {item_id: edited_state["session"]["items"][item_id]["input_revision"] for item_id in item_ids}
        stale_question = next((q for q in saved["pending"] if q["item_id"] == paint_id), None)
        stale = dialogue_service.respond(graph, thread_id,
                  {"answers": {stale_question["field"]: stale_question["choices"][0] if stale_question.get("choices") else "1"},
                   "refs": {stale_question["field"]: stale_question["ref"]}}) if stale_question else {"answer": ""}
        stale_state = dialogue.load(graph, thread_id)
        assert "오래되었거나" in stale["answer"]
        assert after_revisions == {item_id: stale_state["session"]["items"][item_id]["input_revision"] for item_id in item_ids}
        print("PASS target confirmation edits one item, preserves its sibling, and rejects stale refs")

    # Repeated work names at different positions remain distinct source items.
    repeated = "내부 도장 100㎡ 그리고 외부 도장 20㎡"
    repeated_analysis = scope.analyze_request(repeated)
    repeated_receipt = scope.confirm_analysis(repeated, repeated_analysis,
                        dialogue._scope_decisions(repeated_analysis,
                            {q["field"]: "계산에 포함" for q in dialogue._scope_questions(repeated_analysis, 1)}))["confirmation"]
    repeated_plan = scope.confirmed_result(repeated, repeated_analysis, repeated_receipt)["calculation"]["plan"]
    repeated_ids = [item["item_id"] for item in repeated_plan["items"]]
    assert len(repeated_ids) == 2 and repeated_ids[0] != repeated_ids[1]
    print("PASS same-trade locations retain separate stable source IDs")

    uncertain = scope.analyze_request("철판 두께 0.6㎜")
    uncertain_q = dialogue._scope_questions(uncertain, 1)
    if uncertain_q:
        assert {"조건으로 반영", "바탕면으로 반영"}.issubset(set(uncertain_q[0]["choices"]))
        print("PASS unconfirmed scope offers condition/background choices without dropping source text")

    class Checkpointer:
        def get_tuple(self, config):
            if config["configurable"]["thread_id"].startswith("dlg:"):
                return None
            return type("Checkpoint", (), {"checkpoint": {"channel_values": {"route": "qa"}}})()
    assert _uses_dialogue(Checkpointer(), "qa-to-estimate",
                          ChatRequest(message="콘크리트 타설 비용 견적"))
    assert not _uses_dialogue(Checkpointer(), "legacy-estimate-edit",
                              ChatRequest(message="물량 200㎥로 바꿔"))
    print("PASS QA-to-estimate transitions to Dialogue while saved legacy estimate edits stay legacy")


if __name__ == "__main__":
    main()
