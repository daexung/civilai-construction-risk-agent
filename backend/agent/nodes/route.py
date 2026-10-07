"""질문을 견적, 품셈 상담, 범위 밖으로 분류한다."""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

from backend.agent.state import AgentState
from backend.agent.tools.llm import client as llm_client


# 규칙 대체도 router.md와 같은 기준을 쓴다: 돈을 물으면 견적, 돈 없이 품셈을 물으면 상담.
# 물량은 견적 근거가 아니다. ponytail: 낱말 규칙이라 경계 문항은 LLM보다 약하다.
MONEY = re.compile(r"비용|금액|공사비|노무비|인건비|견적|예산|원가|도급액|단가|얼마")
QA_TERMS = re.compile(r"품셈|(?<![제부상작])품(?!질)|인원|인력|몇\s*(?:명|인)|공수|할증|시공량|공구손료|"
                      r"기계경비|작업조|시간")
# 품셈 업무에 속하는 공종·장비 낱말. 돈도 품도 묻지 않을 때 범위 안인지 가린다.
WORK = re.compile(r"타설|콘크리트|레미콘|펌프차|거푸집|철근|철골|비계|도장|타일|미장|방수|굴착|포장|공종")
# 공사 물량 단위. NFKC는 ㎥·㎡를 m3·m2로 바꾼다.
QUANTITY = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:m3|m2|루베|개소|세제곱미터|제곱미터)", re.I)
# 계산 동사는 돈 요청이 아니다. 대상이 돈이면 견적, 인원·품·시간이면 상담, 대상이 없으면 견적으로 둔다.
COMPUTE = re.compile(r"계산|산출|산정")
# 산정 방법·의미를 묻는 말. 계산을 직접 요청하면 견적으로 둔다.
METHOD = re.compile(r"어떻게|어떤\s*(?:기준|방식|방법)|방법|방식|설명|의미|뜻")
REQUEST = re.compile(r"(?:계산|산출|산정|뽑아|만들어|견적\s*내)\s*(?:해\s*)?(?:줘|주세요|봐)|"
                     r"(?:계산|견적|비용|산출)\s*(?:좀\s*)?부탁|견적서|원가계산서")
# router.md가 범위 밖으로 둔 질문: 평당 공사비, 자재 시세, 도면 물량 산출.
OUTSIDE = re.compile(r"평당|시세|도면")
# 직전 견적의 물량·조건 변경이나 금액 재계산. '다시'만으로는 재계산이 아니다(다시 설명해줘).
RECALC = re.compile(r"바꿔|바꾸|변경|재계산|다시\s*(?:계산|해|뽑)|로\s*해\s*(?:줘|주세요)")
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


def _rule_route(query: str, previous_route: str | None = None) -> str:
    text = unicodedata.normalize("NFKC", query)
    if OUTSIDE.search(text):
        return "out_of_scope"
    if previous_route == "estimate" and RECALC.search(text):
        return "estimate"
    money = MONEY.findall(text)
    qa = QA_TERMS.search(text)
    if (money or qa or WORK.search(text)) and METHOD.search(text) and not REQUEST.search(text):
        return "qa"
    # "품이 얼마야", "시간은 얼마나"처럼 '얼마'만 있고 품을 묻는 질문은 상담이다.
    if money and not (qa and set(money) == {"얼마"}):
        return "estimate"
    if qa:
        return "qa"
    if COMPUTE.search(text):
        return "estimate"
    # 물량이 있는 공사 질문은 의도가 불명확해도 범위 밖이 아니라 상담으로 받는다.
    return "qa" if QUANTITY.search(text) else "out_of_scope"


def _previous_summary(state: AgentState) -> str:
    previous = state.get("previous_context") or {}
    route_name = {"estimate": "견적", "qa": "상담", "out_of_scope": "범위 밖"}.get(previous.get("previous_route"), "")
    return " / ".join(part for part in (route_name, previous.get("work"), previous.get("result")) if part) or "없음"


def route(state: AgentState, generate_fn=None) -> dict:
    query = state["query"]
    rule = _rule_route(query, (state.get("previous_context") or {}).get("previous_route"))
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
