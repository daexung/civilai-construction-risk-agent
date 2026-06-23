"""Material cost node — LangGraph adapter.

state['inputs']를 받아 agents/material_cost/service.py 를 호출하고
Command(material_result, material_response)를 반환하는 얇은 어댑터.
도메인 계산 로직은 agents/material_cost/service.py 에 있다.
"""
from __future__ import annotations

import json
import os
import sys

from langchain_core.messages import HumanMessage

from logger import get_logger

log = get_logger(__name__)

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from common.security import check_injection, block_reason_ko
from agents.material_cost.service import calculate_material_cost, _base_result


# ── helpers ────────────────────────────────────────────────────────────────────

def _latest_human_text(state: dict) -> str:
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", None) == "human":
            content = getattr(msg, "content", "")
            return content if isinstance(content, str) else str(content)
    return ""


def _state_update(result: dict) -> dict:
    return {
        "material_result": result,
        "material_response": json.dumps(result, ensure_ascii=False),
    }


# ── LangGraph node ─────────────────────────────────────────────────────────────

def material_node(state: dict) -> dict:
    log.debug("material_node entered")
    print("\n[자재 노드] 처리 시작")

    query = _latest_human_text(state)
    if query:
        is_blocked, reason = check_injection(query)
        if is_blocked:
            result = _base_result("ERROR", f"보안 정책에 의해 요청이 차단되었습니다: {reason}")
            result["is_relevant"] = False
            result["warnings"].append(block_reason_ko(reason))
            print("[자재 노드] 차단")
            return _state_update(result)

    try:
        inputs = state.get("inputs") or {}
        result = calculate_material_cost(inputs)
        log.debug("material_node completed")
        print("[자재 노드] 완료")
        return _state_update(result)

    except Exception as exc:
        log.exception("material_node failed: %s", exc)
        result = _base_result("ERROR", f"자재비 처리 중 오류가 발생했습니다: {exc}")
        result["warnings"].append("예외는 전파하지 않고 material_result에 ERROR로 기록했습니다.")
        print("[자재 노드] 실패")
        return _state_update(result)
