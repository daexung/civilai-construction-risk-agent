"""Equipment cost node — LangGraph adapter.

state['inputs']를 받아 agents/equipment_cost/service.py 를 호출하고
{equipment_result, equipment_response}를 반환하는 얇은 어댑터.
도메인 계산 로직은 agents/equipment_cost/service.py 에 있다.
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
from agents.equipment_cost.service import calculate_equipment_cost, _base_result


# ── helpers ────────────────────────────────────────────────────────────────────

def _latest_human_text(state: dict) -> str:
    for msg in reversed(state.get("messages") or []):
        if isinstance(msg, HumanMessage) or getattr(msg, "type", None) == "human":
            content = getattr(msg, "content", "")
            return content if isinstance(content, str) else str(content)
    return ""


def _state_update(result: dict) -> dict:
    return {
        "equipment_result": result,
        "equipment_response": json.dumps(result, ensure_ascii=False),
    }


# ── LangGraph node ─────────────────────────────────────────────────────────────

def equipment_node(state: dict) -> dict:
    log.debug("equipment_node entered")
    print("\n[장비 노드] deterministic 처리 시작")

    query = _latest_human_text(state)
    if query:
        is_blocked, reason = check_injection(query)
        if is_blocked:
            result = _base_result("ERROR", f"보안 정책에 의해 요청이 차단되었습니다: {reason}")
            result["is_relevant"] = False
            result["warnings"].append(block_reason_ko(reason))
            print("[장비 노드] 차단")
            return _state_update(result)

    try:
        inputs = state.get("inputs") or {}
        print(
            f'[장비 노드] ENTER  rates={inputs.get("rates")}  '
            f'duration_days={inputs.get("duration_days")}  '
            f'work_type={inputs.get("work_type")}'
        )
        result = calculate_equipment_cost(state, inputs)
        print(
            f'[장비 노드] EXIT  status={result["status"]}'
            f'  cost_items={len(result["cost_items"])}'
            f'  missing_fields={result["missing_fields"]}'
        )
        log.debug("equipment_node completed")
        print("[장비 노드] 완료")
        return _state_update(result)

    except Exception as exc:
        log.exception("equipment_node failed: %s", exc)
        result = _base_result("ERROR", f"장비 대기비 deterministic 처리 중 오류가 발생했습니다: {exc}")
        result["warnings"].append("예외는 전파하지 않고 equipment_result에 ERROR로 기록했습니다.")
        print("[장비 노드] 실패")
        return _state_update(result)
