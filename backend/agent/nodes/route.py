"""질문을 견적, 품셈 상담, 범위 밖으로 분류한다."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

from backend.agent.state import AgentState
from backend.agent.tools.llm import client as llm_client


COST_TERMS = (
    "노무비", "인건비", "공사비", "견적", "예산", "일위대가", "단가", "물량", "대가",
    "비용", "금액", "얼마", "인력", "인원", "공수", "품", "설치", "해체", "시공",
    "개소", "㎡", "ton", "kg", "km", "루베",
)
QUANTITY_UNIT = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:m3|m2|m|km|t|ton|kg|개소|개|평|㎡|㎥)(?![a-z])", re.I)
SYSTEM_PROMPT = (Path(__file__).resolve().parents[1] / "tools/llm/prompts/router.md").read_text(encoding="utf-8")
ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": ["estimate", "qa", "out_of_scope"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
        "search_query": {"type": "string"},
    },
    "required": ["route", "confidence", "reason", "search_query"],
}


def _rule_route(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", query)
    return "estimate" if any(term in normalized for term in COST_TERMS) or QUANTITY_UNIT.search(normalized) else "out_of_scope"


def _previous_summary(state: AgentState) -> str:
    previous = state.get("previous_context") or {}
    route_name = {"estimate": "견적", "qa": "상담", "out_of_scope": "범위 밖"}.get(previous.get("previous_route"), "")
    return " / ".join(part for part in (route_name, previous.get("work"), previous.get("result")) if part) or "없음"


def route(state: AgentState, generate_fn=None) -> dict:
    query = state["query"]
    rule = _rule_route(query)
    fallback = {"route": rule, "route_confidence": None,
                "route_reason": "기존 단서 낱말 규칙으로 분류했습니다.", "route_source": "rule"}
    if rule == "out_of_scope":
        fallback.update(status="OUT_OF_SCOPE", reason="공사비·품셈 계산 질문이 아닙니다")
    if os.environ.get("AGENT_LLM", "off") != "on":
        return fallback
    prompt = f"직전 대화: {_previous_summary(state)}\n이번 질문: {query}"
    try:
        result = (generate_fn or llm_client.generate)(
            prompt, SYSTEM_PROMPT, response_schema=ROUTE_SCHEMA,
            timeout_ms=3000, max_attempts=2, retry_delays=[0.3],
        )
        data = json.loads(result.text if isinstance(result, llm_client.LLMResult) else result)
        if not isinstance(data, dict) or data.get("route") not in ("estimate", "qa", "out_of_scope"):
            raise ValueError("invalid route")
        confidence = data.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("invalid confidence")
        reason = data.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason.strip().splitlines()) != 1:
            raise ValueError("invalid reason")
    except Exception:
        return fallback
    search_query = data.get("search_query")
    if not isinstance(search_query, str) or len(search_query.strip().splitlines()) > 1:
        return fallback
    chosen = data["route"] if confidence >= 0.6 else "qa"
    output = {"route": chosen, "route_confidence": float(confidence),
              "route_reason": reason.strip(),
              "route_source": "llm" if confidence >= 0.6 else "llm_low_confidence"}
    if search_query.strip():
        output["search_query"] = search_query.strip()
    if chosen == "out_of_scope":
        output.update(status="OUT_OF_SCOPE", reason="공사비·품셈 계산 질문이 아닙니다")
    return output
