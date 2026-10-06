"""Measure one real estimate's provider usage (makes billable API calls).

Run: .venv/Scripts/python.exe evals/measure_estimate_cost.py
Prompts, API keys, embeddings and user accounts are never written to the report.
This runs the normal graph, including its existing timeouts and retry policy.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def calculate_list_cost(calls: list[dict]) -> dict:
    """2026-10-06 standard global prices; fail closed for other models/providers."""
    amounts = []
    for call in calls:
        if not call.get("success"):
            amounts.append(None)  # Missing response usage is not proof of zero billing.
        elif (call["provider"], call["model"]) == ("vertex", "gemini-3.5-flash-lite"):
            usage = call.get("usage") or {}
            if "prompt_token_count" not in usage or "candidates_token_count" not in usage:
                amounts.append(None)
                continue
            cached = usage.get("cached_content_token_count", 0)
            amounts.append(((usage["prompt_token_count"] - cached) * 0.30 + cached * 0.03
                            + (usage["candidates_token_count"] + usage.get("thoughts_token_count", 0)) * 2.50)
                           / 1_000_000)
        elif (call["provider"], call["model"]) == ("studio", "gemini-embedding-2"):
            tokens = (call.get("raw_usage") or {}).get("usageMetadata", {}).get("promptTokenCount")
            amounts.append(tokens * 0.20 / 1_000_000 if tokens is not None else None)
        else:
            amounts.append(None)
    complete = bool(amounts) and all(amount is not None for amount in amounts)
    total = sum(amounts) if complete else None
    return {"price_checked_at": "2026-10-06", "basis": "standard global list price before credits and tax",
            "usd_per_call": amounts, "complete_usage": complete, "usd_total": total,
            "assumed_krw_per_usd": 1400,
            "krw_total_at_assumed_rate": total * 1400 if total is not None else None,
            "sources": ["https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing",
                        "https://ai.google.dev/gemini-api/docs/pricing#gemini-embedding-2"],
            "excludes": ["hosting", "database", "initial corpus embedding", "credits", "tax"]}


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    os.environ["AGENT_LLM"] = "on"
    os.environ["AGENT_OFFLINE"] = "0"
    from google.genai.models import Models
    from google.genai._api_client import BaseApiClient
    from langgraph.types import Command
    from backend.agent.graph import build_graph, capture_node_timings
    from backend.agent.state import new_state

    calls = []
    turn = 1

    original_request = BaseApiClient.request

    def measured_request(self, *args, **kwargs):
        response = original_request(self, *args, **kwargs)
        if calls and calls[-1]["kind"] == "embedding":
            body = json.loads(response.body) if response.body else {}
            # The SDK drops some embedding usage fields. Preserve only usage, never vectors.
            def usage_fields(value):
                if isinstance(value, dict):
                    output = {}
                    for key, item in value.items():
                        if key in ("usageMetadata", "statistics", "metadata"):
                            output[key] = item
                        elif isinstance(item, (dict, list)):
                            child = usage_fields(item)
                            if child:
                                output[key] = child
                    return output
                if isinstance(value, list):
                    return [child for item in value if (child := usage_fields(item))]
                return None
            calls[-1]["raw_usage"] = usage_fields(body)
        return response

    def wrap(method, kind):
        def measured(self, *args, **kwargs):
            row = {"turn": turn, "kind": kind, "model": kwargs.get("model"),
                   "provider": "vertex" if self._api_client.vertexai else "studio"}
            calls.append(row)
            started = time.perf_counter()
            try:
                response = method(self, *args, **kwargs)
                usage = getattr(response, "usage_metadata", None)
                row["usage"] = usage.model_dump(mode="json", exclude_none=True) if usage else None
                if kind == "embedding":
                    row["statistics"] = [item.statistics.model_dump(mode="json", exclude_none=True)
                                         if item.statistics else None for item in response.embeddings or []]
                    row["metadata"] = (response.metadata.model_dump(mode="json", exclude_none=True)
                                       if response.metadata else None)
                row["model_version"] = getattr(response, "model_version", None)
                row["success"] = True
                return response
            except Exception as exc:
                # Do not persist exception text: SDK errors can contain credential-bearing URLs.
                row.update(success=False, error_type=type(exc).__name__, code=getattr(exc, "code", None))
                raise
            finally:
                row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return measured

    question = "철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"
    answers = {"work": "6-1-4", "pump_size": "32m", "slump_band": "15㎝",
               "facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ", "placement": "붐",
               "vibrator_used": True, "reset_status": "없음", "concrete_supply": "관급",
               "work_category": "기타 토목공사", "duration": "1~6개월",
               "contractor_type": "종합건설업", "project_scale": "이 견적만"}
    report = {"measured_at": datetime.now(timezone.utc).isoformat(), "question": question,
              "basis_date": "2026-10-01", "answers": answers, "calls": calls, "turns": []}
    started = time.perf_counter()
    try:
        with patch.object(Models, "generate_content", wrap(Models.generate_content, "llm")), \
                patch.object(Models, "embed_content", wrap(Models.embed_content, "embedding")), \
                patch.object(BaseApiClient, "request", measured_request):
            graph = build_graph()
            config = {"configurable": {"thread_id": uuid4().hex}}
            with capture_node_timings() as timings:
                state = graph.invoke(new_state(question, report["basis_date"]), config)
            report["turns"].append({"turn": turn, "status": state.get("status"), "timings": timings})
            if graph.get_state(config).next:
                turn = 2
                with capture_node_timings() as timings:
                    state = graph.invoke(Command(resume=answers), config)
                report["turns"].append({"turn": turn, "status": state.get("status"), "timings": timings})
            report.update(status=state.get("status"), route=state.get("route"),
                          route_source=state.get("route_source"), search=state.get("search_info"),
                          contract_amount=(state.get("statement") or {}).get("totals"),
                          complete=bool(state.get("statement")) and not graph.get_state(config).next)
    except Exception as exc:
        report.update(complete=False, error_type=type(exc).__name__)
    report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    report["list_cost"] = calculate_list_cost(calls)
    output = ROOT / "evals/results/estimate_cost_measurement.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
