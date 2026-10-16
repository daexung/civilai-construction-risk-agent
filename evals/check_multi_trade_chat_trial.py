"""Verify the local multi-trade route against pinned files without a DB or embedding calls."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["LOCAL_TRIAL_ITEM_LABOR"] = "on"
os.environ["AGENT_OFFLINE"] = "1"
os.environ["AGENT_LLM"] = "off"
os.environ.setdefault("KNOWLEDGE_ASSET_DIR", r"C:\Users\user\Desktop\PROJECTS\civilai-construction-risk-agent\data\knowledge")

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402
from backend.agent.estimate.local_v1_search import QueryCacheMiss, get_local_v1_search  # noqa: E402
from backend.agent.estimate.scope import analyze_request, confirm_analysis, confirmed_result  # noqa: E402
from backend.api import item_labor_trial as api  # noqa: E402
from backend.shared import embedding  # noqa: E402
from backend.knowledge import embed_index  # noqa: E402


def scope_choices(analysis: dict) -> list[dict]:
    decisions = []
    for span in analysis["scope_spans"]:
        action = {"requested": "include_work", "background": "keep_background",
                  "condition": "keep_condition", "excluded": "keep_excluded"}.get(
                      span["classification"], "exclude_work")
        decision = {"span_id": span["span_id"], "action": action}
        if span["classification"] == "unconfirmed":
            task = next((row for row in analysis["work_items"] if row["segment_id"] == span["span_id"]), None)
            if task:
                decision.update(action="include_work", work=task["work"])
        decisions.append(decision)
    return decisions


def main() -> None:
    hit_query = "시멘트 액체방수를 바닥에 300㎡ 바르려면 인력 품은 어떻게 잡아야 해?"
    search = get_local_v1_search()
    # Fail closed if the route or Retriever ever attempts external embeddings.
    with patch.object(embedding, "embed_texts", side_effect=AssertionError("embedding called")), \
            patch.object(embed_index, "make_client", side_effect=AssertionError("client created")):
        hit = search.search(hit_query)
        assert hit["search_info"]["query_cache_hit"] and hit["search_info"]["api_calls"] == 0
        assert hit["hits"]
        try:
            search.search(hit_query + " 검증용 신규문구 9xq")
        except QueryCacheMiss:
            pass
        else:
            raise AssertionError("unique query should stop at cache miss")

        api._TRIALS.clear()
        request = Request({"type": "http", "client": ("127.0.0.1", 49152), "headers": []})
        trial_data = api.analyze(request, api.AnalyzeRequest(text=hit_query))
        token, trial_id = trial_data["owner_token"], trial_data["trial_id"]
        assert "owner_token_hash" not in str(trial_data)
        unconfirmed = next(span for span in trial_data["analysis"]["scope_spans"]
                           if span["classification"] == "unconfirmed" and span["work_ids"])
        invalid_choices = [{**entry, "work": "시멘트 액체방수"}
                           if entry["span_id"] == unconfirmed["span_id"] else entry
                           for entry in scope_choices(trial_data["analysis"])]
        try:
            api.confirm(request, trial_id, api.ConfirmRequest(decisions=invalid_choices), token)
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("overlapping custom work must be rejected")
        confirmed = api.confirm(request, trial_id, api.ConfirmRequest(decisions=scope_choices(trial_data["analysis"])), token)
        item = confirmed["items"][0]
        assert item["request_text"] == hit_query, item["request_text"]
        try:
            api.SearchRequest.model_validate({"hits": hit["hits"]})
        except Exception:
            pass
        else:
            raise AssertionError("client-supplied hits must be rejected")
        actual = api.search_item(request, trial_id, item["item_id"], api.SearchRequest(), token)
        result = actual["items"][0]
        assert result["search_status"] == "COMPLETE", result
        assert result["search_info"]["query_cache_hit"] is True
        assert result["candidates"], result
        assert result["search_info"]["api_calls"] == 0

        split_text = "내부 도장 100㎡ 그리고 외부 도장 20㎡"
        split_analysis = analyze_request(split_text)
        split_receipt = confirm_analysis(split_text, split_analysis,
                                         scope_choices(split_analysis))["confirmation"]
        split_result = confirmed_result(split_text, split_analysis, split_receipt)
        assert len(split_result["work_items"]) == 2
        assert len({row["id"] for row in split_result["work_items"]}) == 2

        try:
            api.get_trial(request, trial_id, "wrong-owner-token")
        except HTTPException as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("wrong owner token must be rejected")
        api.invalidate_trial(request, trial_id, token)
        try:
            api._summary_payload(api._get_trial(trial_id, token))
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("invalidated summary must not export")

    print("PASS pinned-file hybrid cache hit; no embed/client calls")
    print("PASS cache miss stops without embedding")
    print("PASS server-side search; client hits rejected")
    print("PASS owner-token isolation and summary invalidation")
    print("PASS overlapping recognized work cannot duplicate, separate trades remain separate")


if __name__ == "__main__":
    main()
