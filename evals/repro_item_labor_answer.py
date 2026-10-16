"""Reproduce the exact local item-labor selection/answer route flow."""
from __future__ import annotations

import faulthandler
import json
import traceback

faulthandler.enable()
faulthandler.dump_traceback_later(10, repeat=True)

QUERY = "시멘트 액체방수를 바닥에 300㎡ 바르려면 인력 품은 어떻게 잡아야 해?"


def main() -> int:
    print("IMPORTS_START", flush=True)
    from starlette.requests import Request
    from unittest.mock import patch

    from backend.api import item_labor_trial as api
    from backend.shared import embedding
    from backend.knowledge import embed_index
    from evals.check_multi_trade_chat_trial import scope_choices

    print("IMPORTS_READY", flush=True)
    api._TRIALS.clear()
    request = Request({"type": "http", "client": ("127.0.0.1", 49156), "headers": []})
    with patch.object(embedding, "embed_texts", side_effect=AssertionError("embedding called")), \
            patch.object(embed_index, "make_client", side_effect=AssertionError("embedding client created")):
        trial = api.analyze(request, api.AnalyzeRequest(text=QUERY))
        print("ANALYZE_OK", flush=True)
        choices = scope_choices(trial["analysis"])
        for span, choice in zip(trial["analysis"]["scope_spans"], choices):
            if span["classification"] == "unconfirmed" and span.get("work_ids"):
                choice.update(action="include_work", work="방수")
        token, trial_id = trial["owner_token"], trial["trial_id"]
        confirmed = api.confirm(request, trial_id, api.ConfirmRequest(decisions=choices), token)
        item = confirmed["items"][0]
        print("CONFIRMED_ITEM", json.dumps({
            "item_id": item["item_id"], "request_text": item["request_text"],
            "source_spans": item["source_spans"],
        }, ensure_ascii=False), flush=True)

        searched = api.search_item(request, trial_id, item["item_id"], api.SearchRequest(), token)
        item = searched["items"][0]
        print("SEARCH_RESULT", json.dumps({
            "search_status": item["search_status"],
            "search_info": item.get("search_info"),
            "selected_specification": item.get("selected_specification"),
            "candidates": [{key: c.get(key) for key in ("section_no", "section", "spec_id")}
                           for c in item.get("candidates", [])],
            "questions": [{key: q.get(key) for key in ("question_id", "version", "field", "choices")}
                          for q in item.get("questions", [])],
        }, ensure_ascii=False), flush=True)
        if item["search_status"] != "COMPLETE" or not (item.get("search_info") or {}).get("query_cache_hit"):
            print("STOP: exact query cache miss; answer not submitted", flush=True)
            return 2

        candidate = next((c for c in item.get("candidates", [])
                          if str(c.get("section_no", "")) == "6-4-1"), None)
        question = next((q for q in item.get("questions", []) if q.get("field") == "work"), None)
        if candidate is None:
            print("STOP: 6-4-1 absent from candidates; no other item selected", flush=True)
            return 3
        if question is None:
            print("STOP: no work-selection question; answer endpoint not called", flush=True)
            return 4

        payload = api.AnswerRequest(question_id=question["question_id"],
                                    version=question["version"], value=candidate["section"])
        print("ANSWER_REQUEST", json.dumps({
            "question_id": payload.question_id, "version": payload.version,
            "value": payload.value,
        }, ensure_ascii=False), flush=True)
        try:
            answered = api.answer_item(request, trial_id, item["item_id"], payload, token)
        except Exception:
            print("ANSWER_EXCEPTION_TRACEBACK", flush=True)
            traceback.print_exc()
            return 5
        answer_item = answered["items"][0]
        print("ANSWER_FUNCTION_SUCCESS", json.dumps({
            "selected_specification": answer_item.get("selected_specification"),
            "status": answer_item.get("status"),
            "questions": answer_item.get("questions", []),
            "search_info": answer_item.get("search_info"),
        }, ensure_ascii=False), flush=True)
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException:
        traceback.print_exc()
        raise
    finally:
        faulthandler.cancel_dump_traceback_later()
