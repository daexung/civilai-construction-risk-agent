"""Offline check: the shared applicability gate across calculator types, through the real
service tool (estimate/tools.py:compute_labor + gate.py), not a reimplementation.

No search/model mocking needed here: sessions are built directly via new_session with
explicit plan conditions (real contract, same as a plan-driven estimate), then run through
the actual compute_labor()/gate() used by the live dialogue/API path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")

from backend.agent.estimate import tools  # noqa: E402
from backend.agent.estimate.state import new_session, choose_work  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402

SPECS = list(load_specs().values())


def _session_for(spec: dict, text: str = "견적") -> dict:
    session = new_session({"items": [{"request_text": text}]})
    item = tools._item(session)
    choose_work(item, {"decision": "chosen", "confirmed": True,
                       "section_no": spec["section_no"], "section": spec["title"]}, spec)
    return session


def _answer(session: dict, spec: dict, name: str, value) -> None:
    from backend.agent.estimate.state import set_explicit
    set_explicit(tools._item(session), name, value, "answer")


def main() -> None:
    # 표시용 condition 키는 기존 명세에서 선택적이다. 안내 추가가 기존 공종을 깨뜨리지 않게
    # 실제 로더의 모든 명세로 확인한다(계산 정확성 전수 검사가 아니라 안내 계약 검사).
    for spec in SPECS:
        scope = tools.applicability_scope(spec)
        assert scope["title"].endswith(spec["title"]), spec["id"]
        for section in ("limits", "notes", "separate"):
            assert isinstance(scope[section], list), (spec["id"], section)
    print(f"PASS applicability guidance renders for all {len(SPECS)} loaded specs, including optional condition labels")

    # 1. formula 대표(1-1-2): 공통 경로(compute_labor)를 실제로 타고 applicability_scope가 선택
    #    직후부터 보이는지 확인. 계산 결과 자체의 정확도는 검증 범위가 아니다.
    formula_spec = next(s for s in SPECS if s["quantity_model"]["name"] == "formula" and s["section_no"] == "1-1-2")
    session = _session_for(formula_spec)
    result = tools.compute_labor(session)
    item = tools._item(session)
    assert item.get("applicability_scope", {}).get("title", "").endswith(formula_spec["title"]), item.get("applicability_scope")
    assert result["status"] in ("needs_input", "ok", "blocked"), result
    print("PASS formula(1-1-2) runs through compute_labor and shows applicability_scope from first exposure")

    # 1b. 설명형(비교식 없는) 선언만 있는 명세는 notes로만 노출되고, limits가 비어 자동 차단되지
    #     않는다. compute_labor는 이 note 때문에 blocked로 떨어지지 않는다(확인사항일 뿐).
    notes_only_spec = next(s for s in SPECS if tools.applicability_scope(s)["notes"]
                           and not tools.applicability_scope(s)["limits"])
    scope = tools.applicability_scope(notes_only_spec)
    session = _session_for(notes_only_spec)
    result = tools.compute_labor(session)
    assert result["status"] != "blocked", result
    assert tools._item(session)["applicability_scope"]["notes"], tools._item(session)["applicability_scope"]
    assert not tools._item(session)["applicability_scope"]["limits"]
    print(f"PASS explanation-only declaration ({notes_only_spec['id']}) surfaces as a note, "
          "not an automatic block")

    # 2. lookup_only 대표(1-2-3): 같은 공통 경로.
    lookup_spec = next(s for s in SPECS if s["quantity_model"]["name"] == "lookup_only" and s["section_no"] == "1-2-3")
    session = _session_for(lookup_spec)
    result = tools.compute_labor(session)
    assert result["status"] in ("needs_input", "ok", "blocked"), result
    print("PASS lookup_only(1-2-3) runs through the same compute_labor gate without error")

    # 3. AND 복합 조건(10-3-1 창호유리): 한쪽만 참이면 아직 위반이 아니고(계속 질문),
    #    둘 다 참이면 BLOCKED, 다른 쪽이 거짓이면 AND 규칙이 위반이라고 하지 않는다.
    and_spec = next(s for s in SPECS if s["division"] == "건축" and s["section_no"] == "10-3-1")

    session = _session_for(and_spec)
    _answer(session, and_spec, "glass_type", "판유리")  # thickness 없음: AND 미완성
    result = tools.compute_labor(session)
    assert result["status"] == "needs_input", result
    assert any(q["field"] == "thickness" for q in result["missing"]), result["missing"]
    print("PASS AND condition with only one side given keeps asking the other side (not BLOCKED yet)")

    session = _session_for(and_spec)
    _answer(session, and_spec, "glass_type", "판유리")
    _answer(session, and_spec, "thickness", "16mm이하")
    result = tools.compute_labor(session)
    assert result["status"] == "blocked", result
    print("PASS AND condition fully satisfied (판유리 + 16mm이하) is BLOCKED with the real reason")

    session = _session_for(and_spec)
    _answer(session, and_spec, "glass_type", "복층유리")  # AND의 다른 절이 거짓
    _answer(session, and_spec, "thickness", "16mm이하")
    result = tools.compute_labor(session)
    assert result["status"] != "blocked", result
    print("PASS AND condition with one false clause (복층유리) is not reported as violated")

    session = _session_for(and_spec)
    _answer(session, and_spec, "is_special_glass", True)  # 단일 조건 즉시 차단
    result = tools.compute_labor(session)
    assert result["status"] == "blocked", result
    print("PASS single-condition blocked_if (is_special_glass) still blocks immediately")

    # 4. 규칙 평가 오류(malformed)는 BLOCKED가 아니라 ERROR로 구분한다.
    #    실제 로드 명세는 이런 결함이 없으므로, 오류 분류 자체(check_blocked -> gate)를 검증하기
    #    위해 사본에 존재하지 않는 입력을 참조하는 보류 규칙을 주입한다(원본 spec 파일은 수정하지 않음).
    import copy
    broken = copy.deepcopy(and_spec)
    # 실존하는 수치 필드(quantity)에 숫자로 해석할 수 없는 기준값을 넣어, check_blocked이
    # 조건 자체를 평가할 수 없는 경우(규칙 평가 오류)를 만든다. 공식 범위 비교가 아니라 명세 결함이다.
    broken["blocked"] = [{"condition": "수치 해석 불가 기준값", "reason": "test", "blocked_if":
                          {"input": "quantity", "op": ">", "value": "숫자아님"}, "source": "test", "cite": None}]
    # gate()가 load_specs()[spec_id]로 명세를 다시 읽으므로, 그 사본을 실제 운영 gate() 호출에
    # 주입해 gate가 스스로 ERROR로 분류하는지 확인한다(테스트가 분류 if문을 복제하지 않는다).
    from unittest.mock import patch
    from backend.agent.nodes import gate as gate_module
    with patch.object(gate_module, "load_specs", return_value={broken["id"]: broken}):
        gate_result = gate_module.gate({"spec_id": broken["id"], "inputs": {"quantity": "10"}})
    assert gate_result["status"] == "ERROR", gate_result
    assert gate_result["status"] != "BLOCKED"
    print("PASS gate() itself classifies a malformed blocked rule as ERROR, not BLOCKED")

    # compute_labor()도 같은 사본으로 실제 운영 호출해, 최종 계산 경로에서도 같은 분류가 유지되는지 본다.
    from backend.agent.estimate.state import set_quantity
    with patch.object(tools, "_spec", return_value=broken):
        session = _session_for(and_spec)  # 선택 자체는 원본 spec으로, 내부 조회만 broken으로 가로챈다
        set_quantity(tools._item(session), "10", "㎡", "answer")
        _answer(session, and_spec, "glass_type", "판유리")
        _answer(session, and_spec, "thickness", "3mm이하")
        _answer(session, and_spec, "is_special_glass", False)
        result = tools.compute_labor(session)
    assert result["status"] == "error", result
    print("PASS compute_labor() also classifies the same malformed rule as error, not blocked")

    # 8. 다중 공종: 하나는 BLOCKED(공식 범위 밖), 하나는 정상 산정 -> 실제 aggregate()가 PARTIAL로
    #    구분하고, 차단된 항목의 사유를 보존하면서 정상 형제의 산정액은 그대로 둔다.
    from backend.agent.estimate import aggregate
    from backend.agent.estimate.state import set_explicit, set_quantity

    def _two_item_session(a_height: str, b_height: str) -> dict:
        session = new_session({"items": [{"request_text": "계단A"}, {"request_text": "계단B"}]})
        ids = session["item_order"]
        for item_id, height in zip(ids, (a_height, b_height)):
            item = tools._item(session, item_id)
            choose_work(item, {"decision": "chosen", "confirmed": True,
                               "section_no": STAIR["section_no"], "section": STAIR["title"]}, STAIR)
            set_quantity(item, "18", "㎡", "answer")
            set_explicit(item, "height", height, "answer")
            set_explicit(item, "width", "0.5", "answer")
        for item_id in ids:
            session["active_item_id"] = item_id
            result = tools.compute_labor(session)
            if result["status"] == "ok":
                tools.estimate_cost(session)
        return aggregate.aggregate(session)

    STAIR = next(s for s in SPECS if s["section_no"] == "2-7-7" and s["division"] == "공통")
    mixed = _two_item_session("8", "5")  # 하나는 차단, 하나는 정상
    outcome = mixed["aggregate_result"]
    assert outcome["status"] == "PARTIAL", outcome
    blocked_entry = next(e for e in outcome["excluded"] if "6m" in e["reason"])
    assert blocked_entry["status"] == "BLOCKED"
    priced_item_id = outcome["included"][0]
    assert outcome["items"][priced_item_id]["total"] is not None  # 정상 형제의 산정액은 보존
    assert outcome["direct_total"] > 0  # 0원 완료로 오인되지 않음(실제 정상 항목분 금액)
    print("PASS mixed blocked+normal multi-item: real aggregate() gives PARTIAL, keeps the blocked "
          "reason and the normal sibling's priced amount")

    both_blocked = _two_item_session("8", "9")  # 둘 다 범위 초과
    outcome2 = both_blocked["aggregate_result"]
    assert outcome2["status"] == "NO_RESULT", outcome2
    assert not outcome2["included"]
    assert both_blocked["statement"] is None  # 0원 완료 통계서를 만들지 않는다
    assert all(e["status"] == "BLOCKED" for e in outcome2["excluded"])
    print("PASS all-blocked multi-item: real aggregate() gives NO_RESULT with no statement "
          "(not mistaken for a 0원 complete estimate), each item keeps its own reason")

    # 9. 복원 경계(dialogue_service)에서의 안내 재구성: applicability_scope 필드가 없던 과거
    #    세션(단일·다중)을 응답으로 바꿀 때, 세션을 바꾸지 않고(복원이 아니라 조회) 확정된 선택
    #    명세로 안내를 다시 만든다. BLOCKED 사유·형제 항목의 입력/결과/revision은 그대로여야
    #    하고, 아직 공종이 확정되지 않은 항목에는 안내를 지어내지 않는다.
    from backend.api import dialogue_service
    import copy as _copy

    mixed2 = _two_item_session("8", "5")  # PARTIAL: 하나는 BLOCKED, 하나는 정상 산정
    ids2 = mixed2["item_order"]
    # 기준: 필드가 그대로 있는(이번 핫픽스 이후) 세션의 응답. 표시용 변환(단위 줄 서식 등)은
    # applicability_scope와 무관하므로, "필드 제거 전후 응답이 같다"로 부작용 없음을 확인한다.
    baseline_built = dialogue_service.response("legacy-multi-restore", {"session": _copy.deepcopy(mixed2)})
    baseline_by_id = {entry["item_id"]: entry for entry in baseline_built["multi_trade_items"]}

    restored_session = _copy.deepcopy(mixed2)
    for item_id in ids2:
        item = restored_session["items"][item_id]
        item.pop("applicability_scope", None)  # 이 필드가 생기기 전 과거 세션처럼 만든다
        if item.get("status") == "BLOCKED":
            item.pop("blocked_citations", None)
            item.pop("blocked_input", None)
    built = dialogue_service.response("legacy-multi-restore", {"session": restored_session})
    by_id = {entry["item_id"]: entry for entry in built["multi_trade_items"]}
    for item_id in ids2:
        entry, base_entry = by_id[item_id], baseline_by_id[item_id]
        scope = entry.get("applicability_scope")
        assert scope and scope["title"].endswith(STAIR["title"]), (item_id, scope)
        assert entry["input_revision"] == base_entry["input_revision"], (item_id, "input_revision changed")
        assert entry["priced"] == base_entry["priced"], (item_id, "priced changed by removing the field")
        assert entry["inputs"] == base_entry["inputs"], (item_id, "inputs changed by removing the field")
        if restored_session["items"][item_id].get("status") == "BLOCKED":
            # citations/input은 이 항목에서 함께 지운 blocked_citations/blocked_input의 기존
            # 기본값 동작(없으면 []·"")일 뿐 — 이번 수정 대상은 reason 보존과 scope 재구성이다.
            assert any("6m" in limit["reason"] for limit in scope["limits"]), scope["limits"]
            assert entry["result"]["reason"] == base_entry["result"]["reason"], entry["result"]
        else:
            # 정상 형제 항목은 지운 필드가 없으므로 결과가 완전히 같아야 한다.
            assert entry["result"] == base_entry["result"], (item_id, "sibling result changed")
    print("PASS legacy multi-item restore rebuilds each item's own scope from its selected spec "
          "without touching the BLOCKED reason or the normal sibling's input/priced/revision")

    # 단일 항목도 같은 경계에서 같은 계약을 지킨다(legacy_state 직접 확인, 필드 제거 전후 비교).
    single = _session_for(STAIR, "가설 계단")
    single_item = tools._item(single)
    from backend.agent.estimate.state import set_quantity as _set_quantity
    _set_quantity(single_item, "18", "㎡", "answer")
    _answer(single, STAIR, "height", "8")
    _answer(single, STAIR, "width", "0.9")
    result = tools.compute_labor(single)
    assert result["status"] == "blocked", result
    baseline_single = dialogue_service.legacy_state({"session": _copy.deepcopy(single)})
    before_revision = single_item["input_revision"]
    single_restored = _copy.deepcopy(single)
    restored_item = tools._item(single_restored)
    restored_item.pop("applicability_scope", None)
    restored_item.pop("blocked_citations", None)
    restored_item.pop("blocked_input", None)
    restored = dialogue_service.legacy_state({"session": single_restored})
    assert restored["status"] == "BLOCKED" and restored["status"] == baseline_single["status"]
    assert restored["reason"] == baseline_single["reason"] and "6m" in restored["reason"], restored["reason"]
    assert restored["result"]["reason"] == baseline_single["result"]["reason"], (restored["result"], baseline_single["result"])
    scope = restored.get("applicability_scope")
    assert scope and scope["title"].endswith(STAIR["title"]), scope
    assert any("6m" in limit["reason"] for limit in scope["limits"]), scope["limits"]
    assert single_item["input_revision"] == before_revision  # 복원은 조회일 뿐, 원본 세션을 바꾸지 않는다
    print("PASS legacy single-item restore rebuilds scope from the selected spec and keeps the "
          "BLOCKED reason/result/input_revision identical to the field-present baseline")

    # 아직 공종이 확정되지 않은 항목(후보만 있음)에는 안내를 지어내지 않는다.
    unselected = new_session({"items": [{"request_text": "미확정 공종"}]})
    unselected_item = tools._item(unselected)
    unselected_item["candidates"] = [{"spec_id": STAIR["id"], "section": STAIR["title"],
                                      "section_no": STAIR["section_no"], "division": STAIR["division"],
                                      "score": 1.0, "has_spec": True}]
    out = dialogue_service.legacy_state({"session": unselected})
    assert out.get("applicability_scope") is None, out.get("applicability_scope")
    print("PASS an item with only unconfirmed candidates gets no made-up applicability guidance")


if __name__ == "__main__":
    main()
