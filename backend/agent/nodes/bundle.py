"""여러 공종이 담긴 질문을 항목별로 나눠 기존 단일 공종 계산을 반복하고, 원가계산서는 한 번만 만든다.

공종별 직접비(재료비·노무비·경비)만 더하고 간접비·일반관리비·이윤·부가세는 합친 직접비로
calculate_cost_statement를 한 번 호출해 중복 합산을 막는다.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from backend.agent.nodes.fill import _common_fields, _extract_common_inputs
from backend.agent.state import AgentState
from backend.agent.tools.calc.cost_statement import calculate_cost_statement

MAX_ITEMS = 3
# NFKC 이후 단위(㎥→m3, ㎡→m2). '6개월'은 물량이 아니다.
_UNIT = r"(?:m3|m2|km|kg|ton|톤|루베|개소|본|ea|m|t|개(?!월))"
_QUANTITY = re.compile(r"(?<![0-9a-z.])\d[\d,]*(?:\.\d+)?\s*" + _UNIT + r"(?![a-z0-9])", re.I)
# 치수(높이 3m 등)는 공종 물량이 아니다.
_DIMENSION = re.compile(r"(?:높이|폭|두께|깊이|지름|직경|간격)\s*$")
_SEPARATOR = re.compile(r",(?!\d{3}(?!\d))|;|\n|\s(?:그리고|및|또)\s")
_CONJUNCTION = re.compile(r"(\d\s*" + _UNIT + r")(?:와|과|하고|이랑|랑)\s", re.I)

# 다음 항목으로 넘어갈 때 비우는 항목별 상태.
_ITEM_RESET = {"spec_id": "", "selection": {}, "candidates": [], "hits": [], "inputs": {},
               "input_sources": {}, "questions": [], "reply": "", "result": {}, "priced": None,
               "statement": None, "review_status": "", "search_query": "", "status": "RUNNING",
               "reason": ""}
_SNAPSHOT = ("query", "status", "reason", "spec_id", "selection", "inputs", "input_sources",
             "result", "priced", "review_status")


def _has_quantity(text: str) -> bool:
    return any(not _DIMENSION.search(text[:match.start()]) for match in _QUANTITY.finditer(text))


def split_items(query: str) -> list[str]:
    """물량이 있는 조각을 항목으로 본다. 물량 없는 조각은 앞 항목(맨 앞이면 첫 항목)의 조건으로 붙인다."""
    text = _CONJUNCTION.sub(r"\1\n", unicodedata.normalize("NFKC", query))
    items: list[str] = []
    lead: list[str] = []
    for part in (part.strip() for part in _SEPARATOR.split(text)):
        if not part:
            continue
        if _has_quantity(part):
            items.append(part)
        elif items:
            items[-1] += " " + part
        else:
            lead.append(part)
    if lead and items:
        items[0] = " ".join([*lead, items[0]])
    return items


def split(state: AgentState) -> dict:
    items = split_items(state["query"]) if state.get("route") == "estimate" else []
    if len(items) < 2:
        return {}
    if len(items) > MAX_ITEMS:
        return {"status": "BLOCKED",
                "reason": f"한 번에 {MAX_ITEMS}개 공종까지 묶어 계산할 수 있어요. 공종을 나눠서 질문해 주세요."}
    return {"bundle_query": state["query"], "items": [{"query": item} for item in items],
            "item_index": 0, "query": items[0], "search_query": ""}


def item_label(state: AgentState) -> str:
    index = state.get("item_index", 0)
    return f"{index + 1}번 항목({state['items'][index]['query']})"


def collect(state: AgentState) -> dict:
    """현재 항목 결과를 저장하고 다음 항목을 준비한다. 마지막이면 공통 조건을 합친다."""
    index = state.get("item_index", 0)
    items = list(state["items"])
    items[index] = {key: state.get(key) for key in _SNAPSHOT}
    if ((state.get("priced") or {}).get("reference_amounts") or {}).get("total") is not None:
        items[index]["reason"] = ""  # 앞서 물었던 '조건을 확인해 주세요'가 남지 않게 한다
    index += 1
    if index < len(items):
        return {**_ITEM_RESET, "items": items, "item_index": index, "query": items[index]["query"]}
    # 공통 조건: 기본값 ← 항목에서 답한 값 ← 전체 질문에 쓴 값.
    inputs = {field["name"]: field["default"] for field in _common_fields()}
    sources = {name: "기본값" for name in inputs}
    for item in items:
        for name in inputs:
            source = (item.get("input_sources") or {}).get(name, "")
            if source and not source.startswith("기본값"):
                inputs[name], sources[name] = item["inputs"][name], source
    stated = _extract_common_inputs(state.get("bundle_query", ""))
    inputs.update(stated)
    sources.update({name: "질문" for name in stated})
    return {"items": items, "item_index": index, "query": state.get("bundle_query", ""),
            "inputs": inputs, "input_sources": sources, "spec_id": "", "result": {},
            "priced": None, "questions": []}


def bundle(state: AgentState) -> dict:
    items = state["items"]
    subtotals = {"재료비": 0, "노무비": 0, "경비": 0}
    unpriced: list[dict] = []
    excluded: list[dict] = []
    rate_version = None
    for number, item in enumerate(items, 1):
        reference = (item.get("priced") or {}).get("reference_amounts") or {}
        if reference.get("total") is None:
            unpriced.append({"name": f"{number}번 항목({item['query']})",
                             "reason": item.get("reason") or "계산하지 못한 공종"})
            continue
        for name in subtotals:
            subtotals[name] += int((reference.get("subtotals") or {}).get(name) or 0)
        priced = item["priced"]
        rate_version = rate_version or priced.get("rate_version") or {}
        for target, source in ((unpriced, priced.get("unpriced", [])), (excluded, priced.get("excluded", []))):
            target.extend(entry for entry in source
                          if not any(seen["name"] == entry["name"] for seen in target))
    if rate_version is None:  # 금액을 낸 항목이 하나도 없다
        return {"status": "BLOCKED", "statement": None,
                "reason": "묶을 수 있는 공종 계산 결과가 없어요. " +
                          "; ".join(f"{entry['name']}: {entry['reason']}" for entry in unpriced)}
    combined = {"reference_amounts": {"subtotals": subtotals, "total": sum(subtotals.values()), "volume": None},
                "rate_version": rate_version, "unpriced": unpriced, "excluded": excluded}
    result = calculate_cost_statement(combined, state.get("inputs", {}),
                                      state.get("basis_date") or date.today().isoformat())
    status = "PARTIAL" if result["status"] in ("PARTIAL", "UNCALCULATED") else "OK"
    return {"statement": result, "status": status, "reason": result.get("reason", "")}
