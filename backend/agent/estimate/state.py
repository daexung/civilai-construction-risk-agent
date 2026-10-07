"""복수 공종 견적의 부모 상태(EstimateSession)와 공종 상태(EstimateItem).

- 원래 요청은 바꾸지 않는다.
- 공종마다 자기 상태만 가진다. 다른 공종의 조건·결과를 덮어쓰지 않는다.
- 조건의 기준은 EstimateItem.conditions/quantity다. 단일 공종 노드에 넘기는 inputs는 실행할 때마다
  이 값으로 다시 만든다(flow.py).
- 공통 공사 조건(공사 종류·기간·업종·규모)은 세션에만 둔다.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from fractions import Fraction
from typing import Literal, TypedDict

from backend.agent.nodes.fill import _UNIT_ALIASES, _common_fields, _format_rational, _norm, _valid_for_field

SCHEMA_VERSION = 1
DEFAULT_MAX_ITEMS = 3   # 기존 코드의 상한. 운영 값은 환경변수 ESTIMATE_MAX_ITEMS로만 바꾼다.
ITEM_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")
RESERVED_IDS = {"common", "intent"}
COMMON_FIELDS = {field["name"] for field in _common_fields()}

ItemStatus = Literal["NEEDS_WORK", "NEEDS_INPUT", "READY", "PRICED", "UNSUPPORTED", "NOT_FOUND", "BLOCKED", "ERROR"]
# 사용자 답·조건이 바뀌기 전에는 다시 계산하지 않는 상태.
SETTLED = {"PRICED", "UNSUPPORTED", "NOT_FOUND", "BLOCKED", "ERROR"}


class Question(TypedDict, total=False):
    question_id: str          # "{item_id}:{field}" 또는 "common:{field}"
    version: str              # 질문 대상·조건(명세·선택지)이 바뀔 때만 바뀐다
    scope: Literal["intent", "common", "item"]
    item_id: str | None
    field: str
    kind: str                 # "work" | "choice" | "value"
    allowed_values: list | str | None
    required: bool
    ask: str
    reason: str | None


class EstimateItem(TypedDict, total=False):
    item_id: str
    request_text: str
    source_spans: list
    quantity: dict | None     # {value, unit, source}
    explicit: dict            # 사용자가 준 값(계획·답변). {field: {value, source}} — 명세가 바뀌면 호환 값만 남긴다
    conditions: dict          # 확정 명세 기준으로 구성한 조건. {field: {value, source, explicit}}
    selected_spec_id: str
    selection: dict | None    # {decision, confirmed, section_no, section}
    candidates: list
    hits: list | None         # 검색 캐시(request_text 기준)
    status: ItemStatus
    reason: str
    questions: list           # 이 공종이 지금 기다리는 질문
    question_reasons: dict    # 잘못된 답 등으로 다시 묻는 이유 {field: reason}
    computed_result: dict | None
    labor_key: str | None     # computed_result를 만든 명세·품 조건·물량의 해시
    priced_result: dict | None
    price_key: str | None     # priced_result를 만든 품 키·가격 조건·기준일의 해시
    input_revision: int
    result_revision: int | None


class EstimateSession(TypedDict, total=False):
    schema_version: int
    estimate_id: str
    revision: int
    original_request: str
    source_plan: dict         # 견적을 시작한 입력 계획(다시 보내기 시 새 견적으로 재실행)
    intent: str
    basis_date: str | None
    common_conditions: dict   # {field: {value, source, explicit}}
    items: dict               # {item_id: EstimateItem}
    item_order: list
    pending_questions: dict   # {question_id: Question}
    aggregate_result: dict | None
    statement: dict | None
    diagnostics: list
    notices: list             # 이번 요청에서 사용자에게 알릴 안내(오래된 답 등)


def max_items_setting() -> int:
    """공종 수 상한(설정 한 곳). 계산 구조는 개수와 관계없이 N개를 처리하고, 상한은 계획 검증에서만 쓴다."""
    raw = os.environ.get("ESTIMATE_MAX_ITEMS", "").strip()
    if not raw:
        return DEFAULT_MAX_ITEMS
    if not raw.isdigit() or int(raw) < 1:
        raise ValueError("ESTIMATE_MAX_ITEMS는 1 이상의 정수여야 합니다")
    return int(raw)


class PlanError(ValueError):
    """계획을 계산으로 넘길 수 없다. 항목을 버리지 않고 이유를 돌려준다."""


def _rational(value) -> str:
    amount = Fraction(str(value).replace(",", ""))
    if amount <= 0:
        raise ValueError("물량은 0보다 커야 합니다")
    return _format_rational(amount)


def unit_key(unit: str | None) -> str | None:
    """단위를 비교용 이름으로 바꾼다(㎥·m3·루베 → m3, 개·개소·ea → 개수)."""
    if not unit:
        return None
    text = _norm(unit)
    if text in ("ea",):
        return "count"
    for key, aliases in _UNIT_ALIASES.items():
        if text in {_norm(alias) for alias in aliases}:
            return "count" if key in ("개", "개소") else key
    return None


def question_version(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:10]


def new_session(plan: dict, max_items: int | None = None) -> EstimateSession:
    """구조화된 계획을 검증해 세션을 만든다. 상한(설정)을 넘거나 형식이 틀리면 PlanError."""
    limit = max_items_setting() if max_items is None else max_items
    items = plan.get("items")
    if not isinstance(items, list) or not items:
        raise PlanError("공종 항목이 없습니다")
    if len(items) > limit:
        raise PlanError(f"한 번에 {limit}개 공종까지 계산할 수 있어요. 요청한 {len(items)}개: "
                        + ", ".join(str(item.get("request_text")) for item in items))
    common_fields = {field["name"]: field for field in _common_fields()}
    common = {}
    for name, value in (plan.get("common_conditions") or {}).items():
        if name not in common_fields or not _valid_for_field(value, common_fields[name]):
            raise PlanError(f"공통 조건 값이 올바르지 않습니다: {name}")
        common[name] = {"value": value, "source": "plan", "explicit": True}
    session_items, order = {}, []
    for number, raw in enumerate(items, 1):
        if not isinstance(raw, dict):
            raise PlanError(f"{number}번 공종 형식이 올바르지 않습니다")
        text = raw.get("request_text")
        if not isinstance(text, str) or not text.strip() or len(text) > 500:
            raise PlanError(f"{number}번 공종의 요청 문장이 올바르지 않습니다")
        quantity = None
        if raw.get("quantity") is not None:
            unit = raw["quantity"].get("unit")
            if unit_key(unit) is None:
                raise PlanError(f"{number}번 공종의 물량 단위를 알 수 없습니다: {unit}")
            quantity = {"value": _rational(raw["quantity"]["value"]), "unit": unit, "source": "plan"}
        explicit = {}
        for name, value in (raw.get("conditions") or {}).items():
            if name in COMMON_FIELDS:
                raise PlanError(f"{number}번 공종에 공통 조건 {name}을(를) 넣을 수 없습니다")
            explicit[name] = {"value": value, "source": "plan"}
        item_id = raw.get("item_id", f"i{number}")
        if not isinstance(item_id, str) or not ITEM_ID.fullmatch(item_id) or item_id in RESERVED_IDS:
            raise PlanError(f"{number}번 공종 ID가 올바르지 않습니다: {item_id!r} (영문·숫자·_·- 1~32자)")
        if item_id in session_items:
            raise PlanError(f"공종 ID가 중복됩니다: {item_id!r} ({order.index(item_id) + 1}번과 {number}번)")
        session_items[item_id] = EstimateItem(
            item_id=item_id, request_text=text.strip(), source_spans=list(raw.get("source_spans") or []),
            quantity=quantity, explicit=explicit, conditions={}, selected_spec_id="", selection=None,
            candidates=[], hits=None, status="NEEDS_WORK", reason="", questions=[], question_reasons={},
            computed_result=None, priced_result=None, input_revision=0, result_revision=None)
        order.append(item_id)
    # 공종 누락·중복 실행이 없도록 항목 수와 순서를 맞춘다.
    if len(session_items) != len(items) or order != list(session_items) or len(set(order)) != len(order):
        raise PlanError("공종 항목 수와 순서가 맞지 않습니다")
    return EstimateSession(
        source_plan=json.loads(json.dumps(plan, ensure_ascii=False, default=str)),  # 다시 보내기용 원래 입력 계획
        schema_version=SCHEMA_VERSION, estimate_id=uuid.uuid4().hex, revision=0,
        original_request=plan.get("original_request", ""), intent="estimate", basis_date=plan.get("basis_date"),
        common_conditions=common, items=session_items, item_order=order, pending_questions={},
        aggregate_result=None, statement=None, diagnostics=[], notices=[])


# ---- 캐시 무효화 규칙 ----

def _bump(item: EstimateItem) -> None:
    # 품 결과(computed_result)는 지우지 않는다. 계산 도구가 품 입력 키(labor_key)로 최신인지 판정해
    # 가격 조건만 바뀐 경우 품을 다시 계산하지 않는다(estimate/tools.py).
    item["input_revision"] += 1
    item["priced_result"] = None
    item["result_revision"] = None
    if item["status"] in SETTLED:
        item["status"] = "READY"


def set_request_text(item: EstimateItem, text: str, quantity: dict | None = None) -> None:
    """요청 전체 교체: 검색·후보·선택·명세·조건·결과와 물량을 모두 새 요청 기준으로 다시 만든다.

    물량은 새 계획 값(quantity)이 있으면 그 값, 없으면 비운다(새 요청 문장에서 다시 읽거나 다시 묻는다).
    이전 답(explicit·물량)은 새 요청과 충돌할 수 있으므로 쓰지 않고 dropped_conditions에 기록한다.
    특정 조건만 고칠 때는 set_quantity·set_explicit을 쓴다(다른 조건과 검색 결과 유지).
    """
    dropped = item.setdefault("dropped_conditions", [])
    for name, entry in item["explicit"].items():
        dropped.append({"field": name, "value": entry["value"], "reason": "요청이 바뀌어 다시 확인"})
    if item.get("quantity"):
        dropped.append({"field": "quantity", "value": item["quantity"]["value"], "unit": item["quantity"]["unit"],
                        "reason": "요청이 바뀌어 다시 확인"})
    item["request_text"] = text.strip()
    item["quantity"] = None
    if quantity is not None:
        if unit_key(quantity.get("unit")) is None:
            raise PlanError(f"물량 단위를 알 수 없습니다: {quantity.get('unit')}")
        item["quantity"] = {"value": _rational(quantity["value"]), "unit": quantity["unit"], "source": "plan"}
    item.update(hits=None, candidates=[], selection=None, selected_spec_id="", conditions={}, explicit={},
                question_reasons={}, questions=[])
    _bump(item)
    item["status"] = "NEEDS_WORK"


def set_quantity(item: EstimateItem, value, unit: str, source: str) -> None:
    """물량이 바뀌면 계산 결과만 버린다(검색·선택은 유지)."""
    item["quantity"] = {"value": _rational(value), "unit": unit, "source": source}
    _bump(item)


def set_explicit(item: EstimateItem, field: str, value, source: str) -> None:
    """조건 값이 바뀌면 계산 결과만 버린다."""
    item["explicit"][field] = {"value": value, "source": source}
    item["question_reasons"].pop(field, None)
    _bump(item)


def choose_work(item: EstimateItem, selection: dict, spec: dict | None) -> None:
    """공종을 고르거나 바꾸면 명세·조건·결과를 다시 만든다. 검색 결과와 후보는 유지한다.

    새 명세에 없는 사용자 값은 버린다(호환되지 않는 이전 조건을 유지하지 않음).
    """
    previous = item.get("selected_spec_id")
    item["selection"] = selection
    item["selected_spec_id"] = spec["id"] if spec else ""
    reasons = {}
    if spec and previous != spec["id"]:
        fields = {field["name"]: field for field in spec["inputs"]}
        kept = {}
        for name, entry in item["explicit"].items():
            if name not in fields:
                # 할증 적용 답(apply_adj_*)처럼 새 명세에 없는 값은 쓰지 않고 기록만 남긴다.
                item.setdefault("dropped_conditions", []).append({"field": name, "value": entry["value"],
                                                                  "reason": "선택한 공종에 없는 조건"})
            elif _valid_for_field(entry["value"], fields[name]):
                kept[name] = entry
            else:
                reasons[name] = "앞서 받은 값이 이 공종의 선택지와 맞지 않아요. 다시 골라 주세요."
        item["explicit"] = kept
    item["conditions"] = {}
    item["question_reasons"] = reasons
    _bump(item)


def set_common(session: EstimateSession, field: str, value) -> None:
    """공통 공사 조건 수정: 공종 계산 결과는 유지하고, 통합 원가계산서만 다시 만든다(aggregate)."""
    definition = next((item for item in _common_fields() if item["name"] == field), None)
    if definition is None or not _valid_for_field(value, definition):
        raise PlanError(f"공통 조건 값이 올바르지 않습니다: {field}")
    session["common_conditions"][field] = {"value": value, "source": "answer", "explicit": True}
    session["revision"] += 1
