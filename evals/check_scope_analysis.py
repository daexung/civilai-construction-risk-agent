"""요청 범위 분석, 사용자 확인, 기존 단일 공종 도구 연결을 오프라인으로 검사한다."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.estimate.scope import (analyze_request, analyze_request_with_model, confirm_analysis,
                                          confirmed_result, validate_model_analysis)  # noqa: E402
from backend.agent.estimate.state import new_session  # noqa: E402
from backend.agent.estimate import tools  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402


def _decisions(analysis, overrides=None):
    overrides = overrides or {}
    output = []
    for span in analysis["scope_spans"]:
        if span["span_id"] in overrides:
            output.append({"span_id": span["span_id"], **overrides[span["span_id"]]})
        elif span["classification"] == "requested":
            output.append({"span_id": span["span_id"], "action": "include_work"})
        elif span["classification"] == "excluded":
            output.append({"span_id": span["span_id"], "action": "keep_excluded"})
        elif span["classification"] == "background":
            output.append({"span_id": span["span_id"], "action": "keep_background"})
        elif span["classification"] == "condition":
            output.append({"span_id": span["span_id"], "action": "keep_condition"})
        else:
            output.append({"span_id": span["span_id"], "action": "exclude_work"})
    return output


def _evidence(text, phrase):
    start = text.find(phrase)
    return {"text": phrase, "start": start, "end": start + len(phrase)}


def main() -> int:
    checks = []

    def add(name, passed):
        checks.append((name, bool(passed)))

    sample = "조적벽에 수성페인트 2회 100㎡"
    analysis = analyze_request(sample)
    add("existing wall is substrate; paint is one job; repeat/area remain source conditions",
        len(analysis["work_items"]) == 1 and analysis["work_items"][0]["work"] == "도장"
        and [s["surface"] for s in analysis["substrates"]] == ["조적벽"]
        and {(c["kind"], c["value"], c["unit"]) for c in analysis["conditions"]}
        >= {("repeat_count", "2", "회"), ("quantity", "100", "㎡")}
        and analysis["calculation"] == {"mode": "not_ready"})

    receipt = confirm_analysis(sample, analysis, _decisions(analysis))["confirmation"]
    ready = confirmed_result(sample, analysis, receipt)
    plan = ready["calculation"].get("plan", {})
    session = new_session(plan)
    item = session["items"][session["item_order"][0]]
    add("only explicit, complete confirmation creates EstimateSession plan",
        ready["calculation"]["mode"] == "single_trade" and item["quantity"]["value"] == "100"
        and item["request_text"].startswith("도장 ") and "수성페인트" in item["request_text"]
        and len(item["source_spans"]) >= 4)

    paint = next(spec for spec in load_specs().values() if spec["section_no"] == "11-2-2")
    found = tools.find_work(session, hits=[{"section_no": paint["section_no"], "division": paint["division"],
        "rank": 1, "section": f"{paint['section_no']} {paint['title']}", "chunk_id": "paint-fixture", "score": 10}])
    selected = tools.set_conditions(session, "", work=paint["section_no"], source="answer")
    computed = tools.compute_labor(session)
    add("confirmed single plan reaches existing tools without losing its quantity",
        found["status"] == "needs_input" and not selected["rejected"] and item["quantity"]["value"] == "100"
        and computed["status"] in ("ok", "needs_input"))

    unknown_examples = [
        ("도장100㎡와 전기배선20m", "전기배선20m"),
        ("도장과 소방/통신/환기/철골/알수없는작업", "소방"),
        ("도장100㎡ 환기설비2대", "환기설비"),
    ]
    results = [(text, analyze_request(text)) for text, _ in unknown_examples]
    all_unknown = analyze_request("도장과 소방/통신/환기/철골/알수없는작업")
    add("unknown connected trades and residual phrases are retained, never silently ready",
        all(any(needle in unknown["text"] for unknown in analysis["unconfirmed_scope"])
            and analysis["calculation"]["mode"] == "not_ready" for (text, needle), (_, analysis)
            in zip(unknown_examples, results))
        and {"소방", "통신", "환기", "철골", "알수없는작업"}
        <= {span["text"] for span in all_unknown["unconfirmed_scope"]})

    unknown_text = unknown_examples[0][0]
    unknown_analysis = analyze_request(unknown_text)
    unknown_override = {span["span_id"]: {"action": "include_work", "work": "전기배선"}
                        for span in unknown_analysis["scope_spans"]
                        if span["classification"] == "unconfirmed"}
    user_checked = confirm_analysis(unknown_text, unknown_analysis, _decisions(unknown_analysis, unknown_override))["confirmation"]
    multi = confirmed_result(unknown_text, unknown_analysis, user_checked)
    add("user explicitly including a previously unknown trade leaves multi-work result not_ready",
        multi["calculation"]["mode"] == "not_ready" and len(multi["work_items"]) == 2)

    repeated = analyze_request("내부 도장100㎡와 외부 도장20㎡")
    add("same trade at separate locations stays two tasks with separate quantities",
        len(repeated["work_items"]) == 2
        and [task["conditions"][0]["value"] for task in repeated["work_items"]] == ["100", "20"]
        and repeated["calculation"]["mode"] == "not_ready")

    concrete = analyze_request("콘크리트벽 도장")
    add("concrete wall is substrate, not an inferred concrete trade",
        [task["work"] for task in concrete["work_items"]] == ["도장"]
        and [base["surface"] for base in concrete["substrates"]] == ["콘크리트벽"]
        and not concrete["unconfirmed_scope"])

    exclusion_text = "수성페인트 롤러칠 2회 벽면100㎡, 방수20㎡는 제외"
    excluded_analysis = analyze_request(exclusion_text)
    exclude_decisions = _decisions(excluded_analysis)
    exclude_receipt = confirm_analysis(exclusion_text, excluded_analysis, exclude_decisions)["confirmation"]
    excluded_result = confirmed_result(exclusion_text, excluded_analysis, exclude_receipt)
    excluded_item = excluded_result["calculation"]["plan"]["items"][0]
    add("confirmed paint method, coat count, surface and area survive; excluded waterproof phrase does not leak",
        excluded_result["calculation"]["mode"] == "single_trade"
        and "롤러칠" in excluded_item["request_text"] and "2회" in excluded_item["request_text"]
        and "100㎡" in excluded_item["request_text"] and "방수" not in excluded_item["request_text"]
        and "20㎡" not in excluded_item["request_text"]
        and any(span["kind"] == "background" for span in excluded_item["source_spans"]))

    alt_text = "도장 또는 방수"
    alt_analysis = analyze_request(alt_text)
    alt_overrides = {}
    for span in alt_analysis["scope_spans"]:
        if span["classification"] == "unconfirmed":
            chosen = "방수" if "방수" in span["text"] else None
            alt_overrides[span["span_id"]] = ({"action": "include_work", "work": chosen} if chosen
                                               else {"action": "exclude_work"})
    alt = confirmed_result(alt_text, alt_analysis,
        confirm_analysis(alt_text, alt_analysis, _decisions(alt_analysis, alt_overrides))["confirmation"])
    add("alternative is not a task set until the user chooses one", len(alt["work_items"]) == 1
        and alt["work_items"][0]["work"] == "방수" and alt["calculation"]["mode"] == "single_trade")

    decimal_text = "도장2.5m2"
    decimal_result = analyze_request(decimal_text)
    decimal_decisions = _decisions(decimal_result)
    decimal_ready = confirmed_result(decimal_text, decimal_result,
        confirm_analysis(decimal_text, decimal_result, decimal_decisions)["confirmation"])
    zero_result, negative_result = analyze_request("도장0㎡"), analyze_request("도장-3㎡")
    def confirmed_invalid(text, result):
        overrides = {}
        for span in result["scope_spans"]:
            if span["classification"] == "unconfirmed":
                overrides[span["span_id"]] = {"action": "include_work", "work": "도장"}
        receipt = confirm_analysis(text, result, _decisions(result, overrides))["confirmation"]
        return confirmed_result(text, result, receipt)

    zero_confirmed = confirmed_invalid("도장0㎡", zero_result)
    negative_confirmed = confirmed_invalid("도장-3㎡", negative_result)
    add("decimal, zero and negative quantities are preserved without conversion",
        any(c["value"] == "2.5" and c["unit"] == "m2" for c in decimal_result["conditions"])
        and decimal_ready["calculation"]["mode"] == "single_trade"
        and new_session(decimal_ready["calculation"]["plan"])["items"]["i1"]["quantity"]["value"] == "2.5"
        and any(c["value"] == "0" for c in zero_result["conditions"])
        and zero_result["unconfirmed_scope"] and any(c["value"] == "-3" for c in negative_result["conditions"])
        and negative_result["unconfirmed_scope"]
        and zero_confirmed["calculation"]["mode"] == "not_ready"
        and negative_confirmed["calculation"]["mode"] == "not_ready")

    conversion = analyze_request("도장10000cm")
    conversion_overrides = {s["span_id"]: {"action": "include_work"} for s in conversion["scope_spans"]
                            if s["classification"] == "requested"}
    conversion_overrides.update({s["span_id"]: {"action": "keep_condition"} for s in conversion["scope_spans"]
                                 if s["classification"] == "condition"})
    converted = confirmed_result("도장10000cm", conversion,
        confirm_analysis("도장10000cm", conversion, _decisions(conversion, conversion_overrides))["confirmation"])
    add("unsupported quantity units stay literal and cannot be silently normalized",
        any(c["value"] == "10000" and c["unit"] == "cm" for c in conversion["conditions"])
        and converted["calculation"]["mode"] == "not_ready")

    # 확인증은 원문·분석 해시와 전체 선택에 묶이며, 불완전/위조/재사용 입력은 거부한다.
    try:
        confirm_analysis(sample, analysis, _decisions(analysis)[:-1])
        missing_rejected = False
    except ValueError:
        missing_rejected = True
    altered = dict(receipt, source_hash="fake")
    try:
        confirmed_result(sample, analysis, altered)
        forged_rejected = False
    except ValueError:
        forged_rejected = True
    try:
        confirmed_result(sample + " ", analysis, receipt)
        stale_rejected = False
    except ValueError:
        stale_rejected = True
    try:
        confirm_analysis(sample, {**analysis, "work_items": []}, _decisions(analysis))
        tamper_rejected = False
    except ValueError:
        tamper_rejected = True
    add("missing decisions, forged confirmation, changed source and edited analysis are rejected",
        missing_rejected and forged_rejected and stale_rejected and tamper_rejected)

    changed_request_rejections = 0
    for changed_text in ("조적벽에 방수 2회 100㎡", "조적벽에 수성페인트 2회 101㎡"):
        try:
            confirmed_result(changed_text, analysis, receipt)
        except ValueError:
            changed_request_rejections += 1
    add("work and quantity edits invalidate prior confirmation", changed_request_rejections == 2)

    exclusion_text = "도장100㎡와 방수20㎡는 제외"
    exclusion_analysis = analyze_request(exclusion_text)
    exclusion_receipt = confirm_analysis(exclusion_text, exclusion_analysis,
                                         _decisions(exclusion_analysis))["confirmation"]
    try:
        confirmed_result("도장100㎡와 방수20㎡", exclusion_analysis, exclusion_receipt)
        exclusion_edit_rejected = False
    except ValueError:
        exclusion_edit_rejected = True
    add("changing an exclusion invalidates prior confirmation", exclusion_edit_rejected)

    model_text = "도장100㎡와 방수20㎡"
    model_proposal = {"work_items": [
        {"work": "도장", "evidence": _evidence(model_text, "도장"), "conditions": [
            {"kind": "quantity", "value": "100", "unit": "㎡", "evidence": _evidence(model_text, "100㎡")}]},
        {"work": "방수", "evidence": _evidence(model_text, "방수"), "conditions": [
            {"kind": "quantity", "value": "20", "unit": "㎡", "evidence": _evidence(model_text, "20㎡")}]}],
        "substrates": [], "excluded_requests": [], "unconfirmed_scope": []}
    mock_seen = {}

    def mock_generate(prompt, system, **kwargs):
        mock_seen.update(kwargs)
        return model_proposal

    modeled = analyze_request_with_model(model_text, generate=mock_generate)
    add("injected mock model uses schema and never auto-creates a plan",
        mock_seen.get("response_schema") is not None and modeled["calculation"]["mode"] == "not_ready")

    missing_task = dict(model_proposal, work_items=model_proposal["work_items"][:1])
    missing_task_result = validate_model_analysis(model_text, missing_task)
    add("model omission of a source work becomes unconfirmed", missing_task_result["calculation"]["mode"] == "not_ready"
        and any("방수" in item["text"] for item in missing_task_result["unconfirmed_scope"]))

    missing_quantity = {**model_proposal, "work_items": [
        {"work": "도장", "evidence": _evidence(model_text, "도장"), "conditions": []},
        model_proposal["work_items"][1]]}
    missing_quantity_result = validate_model_analysis(model_text, missing_quantity)
    add("model quantity omission becomes a source-linked confirmation gap",
        missing_quantity_result["calculation"]["mode"] == "not_ready"
        and any(item["text"] == "100㎡" for item in missing_quantity_result["unconfirmed_scope"]))

    wrong_quantity = {**model_proposal, "work_items": [
        {"work": "도장", "evidence": _evidence(model_text, "도장"), "conditions": [
            {"kind": "quantity", "value": "20", "unit": "㎡", "evidence": _evidence(model_text, "20㎡")}]},
        model_proposal["work_items"][1]]}
    cross_task_rejected = False
    try:
        validate_model_analysis(model_text, wrong_quantity)
    except ValueError:
        cross_task_rejected = True
    add("model cannot attach the next work's amount to this work", cross_task_rejected)

    swapped_values = {**model_proposal, "work_items": [
        {"work": "도장", "evidence": _evidence(model_text, "도장"), "conditions": [
            {"kind": "quantity", "value": "20", "unit": "㎡", "evidence": _evidence(model_text, "100㎡")}]},
        {"work": "방수", "evidence": _evidence(model_text, "방수"), "conditions": [
            {"kind": "quantity", "value": "100", "unit": "㎡", "evidence": _evidence(model_text, "20㎡")}]}]}
    swapped_rejected = False
    try:
        validate_model_analysis(model_text, swapped_values)
    except ValueError:
        swapped_rejected = True
    add("model cannot swap numeric values between jobs", swapped_rejected)

    substrate_text = "콘크리트벽 도장100㎡"
    no_substrate = {"work_items": [{"work": "도장", "evidence": _evidence(substrate_text, "도장"),
        "conditions": [{"kind": "quantity", "value": "100", "unit": "㎡",
                        "evidence": _evidence(substrate_text, "100㎡")}] }],
        "substrates": [], "excluded_requests": [], "unconfirmed_scope": []}
    missing_substrate_result = validate_model_analysis(substrate_text, no_substrate)
    add("model omission of a background surface remains a confirmation gap",
        missing_substrate_result["calculation"]["mode"] == "not_ready"
        and any(item["text"] == "콘크리트벽" for item in missing_substrate_result["unconfirmed_scope"]))

    wrong_location = dict(model_proposal, work_items=[dict(model_proposal["work_items"][0],
        evidence={"text": "도장", "start": 1, "end": 3}), model_proposal["work_items"][1]])
    position_rejected = False
    try:
        validate_model_analysis(model_text, wrong_location)
    except ValueError:
        position_rejected = True
    duplicate_text = "도장10㎡와 도장20㎡"
    repeated_proposal = {"work_items": [{"work": "도장", "evidence": "도장", "conditions": []}],
        "substrates": [], "excluded_requests": [], "unconfirmed_scope": []}
    duplicate_rejected = False
    try:
        validate_model_analysis(duplicate_text, repeated_proposal)
    except ValueError:
        duplicate_rejected = True
    add("wrong location and ambiguous duplicate evidence are rejected", position_rejected and duplicate_rejected)

    failure = analyze_request_with_model("도장100㎡", generate=lambda *a, **k: {})
    add("model failure returns explicitly unconfirmed, never ready", failure["calculation"]["mode"] == "not_ready"
        and bool(failure["unconfirmed_scope"]) and bool(failure["questions"]))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    failed = [name for name, passed in checks if not passed]
    print(f"{len(checks) - len(failed)}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
