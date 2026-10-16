"""사용자 요청 범위를 보수적으로 나누고, 별도 확인 뒤 단일 항목 계획을 만든다.

분석만으로는 계산 가능한 계획을 만들지 않는다. 규칙 분석은 일부 익숙한 작업 표현을
보조로 인식하며, 연결 표현으로 나뉜 나머지 요청 구절은 그대로 미확정으로 보존한다.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from decimal import Decimal, InvalidOperation


ANALYSIS_VERSION = 2
_WORKS = {
    "도장": re.compile(r"페인트|도장|칠하|칠해|칠칠|도색"),
    "조적": re.compile(r"조적(?!벽)|(?:조적벽|벽돌).{0,8}(?:쌓|시공)|쌓.{0,4}(?:벽돌|조적)"),
    "방수": re.compile(r"방수"),
    "철거": re.compile(r"철거|제거|뜯어"),
}
_SURFACES = re.compile(r"조적벽|콘크리트(?:벽|바닥|면)|벽돌벽|벽면|바닥면|벽|바닥")
_CONNECTOR = re.compile(r"\s*(또는|혹은|아니면|그리고|및|하고|와|과|,|/|\+)\s*")
_ALTERNATIVES = {"또는", "혹은", "아니면"}
_ADVICE = re.compile(r"(?:해야\s*하는지|해야\s*할지|아야\s*하는지|아야\s*할지|필요한지|여부|할지\s*말지)")
_NEGATION = re.compile(r"제외|빼고|하지\s*말|안\s*해|불필요")
_REPEAT = re.compile(r"(?<![\w.])([+-]?\d[\d,]*(?:\.\d+)?)\s*회")
_MEASURE = re.compile(r"(?<![\d.])([+-]?\d[\d,]*(?:\.\d+)?)\s*(㎥|m3|㎡|m2|cm|mm|m|개소|개|일)(?![\w])", re.I)
_METHODS = {"도장": re.compile(r"롤러칠|붓칠|뿜칠")}
_EVIDENCE_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"},
                    "start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1}},
                    "required": ["text", "start", "end"]}
MODEL_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "work_items": {"type": "array", "items": {"type": "object", "properties": {
            "work": {"type": "string"}, "evidence": _EVIDENCE_SCHEMA,
            "conditions": {"type": "array", "items": {"type": "object", "properties": {
                "kind": {"type": "string", "enum": ["quantity", "repeat_count", "condition"]},
                "value": {"type": "string"}, "unit": {"type": "string"}, "evidence": _EVIDENCE_SCHEMA},
                "required": ["kind", "value", "evidence"]}}},
            "required": ["work", "evidence", "conditions"]}},
        "substrates": {"type": "array", "items": {"type": "object", "properties": {
            "surface": {"type": "string"}, "evidence": _EVIDENCE_SCHEMA}, "required": ["surface", "evidence"]}},
        "excluded_requests": {"type": "array", "items": {"type": "object", "properties": {
            "work": {"type": "string"}, "evidence": _EVIDENCE_SCHEMA}, "required": ["work", "evidence"]}},
        "unconfirmed_scope": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "evidence": _EVIDENCE_SCHEMA}, "required": ["text", "evidence"]}},
    },
    "required": ["work_items", "substrates", "excluded_requests", "unconfirmed_scope"],
}


def _json_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _span(text: str, start: int, end: int) -> dict[str, Any]:
    return {"text": text[start:end], "start": start, "end": end}


def _split_segments(text: str) -> list[dict[str, Any]]:
    segments, start = [], 0
    for match in _CONNECTOR.finditer(text):
        left, right = start, match.start()
        while left < right and text[left].isspace():
            left += 1
        while right > left and text[right - 1].isspace():
            right -= 1
        if left < right:
            segments.append({"text": text[left:right], "start": left, "end": right,
                             "connector_after": match.group(1)})
        start = match.end()
    left, right = start, len(text)
    while left < right and text[left].isspace():
        left += 1
    while right > left and text[right - 1].isspace():
        right -= 1
    if left < right:
        segments.append({"text": text[left:right], "start": left, "end": right, "connector_after": None})
    return segments


def _matches(pattern: re.Pattern, text: str, start: int = 0, end: int | None = None):
    return [(m.start() + start, m.end() + start, m) for m in pattern.finditer(text, 0, len(text) if end is None else end)]


def _analysis_hash(result: dict) -> str:
    return _json_hash({key: value for key, value in result.items() if key != "analysis_hash"})


def analyze_request(text: str) -> dict[str, Any]:
    """작업·바탕·조건·제외·미확정 구절을 만든다. 절대 계산 계획은 반환하지 않는다."""
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise ValueError("요청은 비어 있지 않은 2,000자 이하 문장이어야 합니다")

    work_items, substrates, exclusions, unconfirmed, segments, all_conditions = [], [], [], [], [], []
    alternative_group = 0
    previous_connector = None
    for raw in _split_segments(text):
        start, end, phrase = raw["start"], raw["end"], raw["text"]
        work_hits = []
        for name, pattern in _WORKS.items():
            work_hits.extend((a, b, name) for a, b, _ in _matches(pattern, phrase, start))
        work_hits.sort()
        # 같은 구절의 재료 이름과 작업 동사를 하나의 작업으로 묶되, 다른 구절의 같은 공종은 보존한다.
        unique_hits = []
        for a, b, name in work_hits:
            previous = next((hit for hit in reversed(unique_hits) if hit[2] == name), None)
            if previous:
                intervening = phrase[previous[1] - start:a - start]
                separate_quantity = any(q.start() + start >= previous[1] and q.start() + start < a
                                        for pattern in (_MEASURE, _REPEAT) for q in pattern.finditer(phrase))
                separate_location = bool(re.search(r"내부|외부|실내|실외|옥내|옥외|[0-9]+층", intervening))
                if not separate_quantity and not separate_location:
                    continue
            unique_hits.append((a, b, name))

        # 기존 도막은 제거 대상의 설명이다. 새 도장은 '다시 칠함' 구절에서 따로 찾는다.
        has_removal = any(name == "철거" for _, _, name in unique_hits)
        if has_removal and "기존" in phrase:
            unique_hits = [hit for hit in unique_hits if hit[2] != "도장"]
            repaint = re.search(r"다시\s*(?:칠|도장)|재도장", phrase)
            if repaint:
                unique_hits.append((start + repaint.start(), start + repaint.end(), "도장"))
                unique_hits.sort()

        advice = bool(_ADVICE.search(phrase))
        negated = bool(_NEGATION.search(phrase))
        alt = previous_connector in _ALTERNATIVES or raw.get("connector_after") in _ALTERNATIVES
        if alt:
            alternative_group += 1
        span_id = f"s{start}_{end}"
        evidence = _span(text, start, end)
        task_ids, substrate_ids, condition_ids = [], [], []
        excluded_hits = []
        if alt:
            classification = "unconfirmed"
            reason = "선택 전인 대안 구절"
        elif advice:
            classification = "unconfirmed"
            reason = "실행 요청인지 묻는 말인지 불확실"
        elif unique_hits and negated:
            classification = "excluded"
            reason = "원문에서 제외 또는 실행하지 말라고 표현"
            excluded_hits = unique_hits
            for a, b, name in unique_hits:
                exclusions.append({"work": name, "evidence": _span(text, a, b), "segment_id": span_id})
            excluded_quantities = [(a, b, "repeat_count", m.group(1), "회")
                                   for a, b, m in _matches(_REPEAT, phrase, start)]
            excluded_quantities += [(a, b, "quantity", m.group(1), m.group(2))
                                    for a, b, m in _matches(_MEASURE, phrase, start)]
            for qa, qb, kind, value, unit in excluded_quantities:
                condition = {"id": f"c{qa}_{qb}", "kind": kind, "value": value, "unit": unit,
                             "evidence": _span(text, qa, qb), "segment_id": span_id, "unattached": True}
                all_conditions.append(condition)
                condition_ids.append(condition["id"])
        elif unique_hits:
            classification = "requested"
            reason = None
            # 수량이 하나의 구절에 두 작업 이상 붙으면 어느 작업의 양인지 확인한다.
            quantities = []
            quantities.extend((a, b, "repeat_count", m.group(1), "회", m)
                              for a, b, m in _matches(_REPEAT, phrase, start))
            quantities.extend((a, b, "quantity", m.group(1), m.group(2), m)
                              for a, b, m in _matches(_MEASURE, phrase, start))
            quantity_owners = []
            for qa, qb, kind, value, unit, match in quantities:
                preceding = [hit for hit in unique_hits if hit[1] <= qa]
                owner = preceding[-1] if preceding else None
                between = phrase[(owner[1] - start):(qa - start)] if owner else ""
                intervening_surfaces = [(m.start(), m.end(), m.group())
                                        for m in _SURFACES.finditer(between)]
                attachable = owner is not None and not _unclassified_text(between, 0, intervening_surfaces)
                quantity_owners.append((owner, attachable))
            per_task_qty = {hit: 0 for hit in unique_hits}
            for (owner, attachable) in quantity_owners:
                if owner is not None and attachable:
                    per_task_qty[owner] += 1
            if len(unique_hits) > 1 and quantities and any(per_task_qty[hit] == 0 for hit in unique_hits):
                classification = "unconfirmed"
                reason = "여러 작업이 한 구절의 수량을 공유할 수 있음"
            unattached_quantities = []
            for index, (a, b, name) in enumerate(unique_hits):
                task_id = f"w{a}_{b}"
                task_conditions = []
                if classification == "requested":
                    for quantity_index, (qa, qb, kind, value, unit, match) in enumerate(quantities):
                        if kind == "repeat_count" and name != "도장":
                            continue
                        owner, attachable = quantity_owners[quantity_index]
                        if owner != (a, b, name) or not attachable:
                            unattached_quantities.append((qa, qb, kind, value, unit))
                            continue
                        condition = {"id": f"c{qa}_{qb}", "kind": kind, "value": value, "unit": unit,
                                     "evidence": _span(text, qa, qb), "segment_id": span_id}
                        task_conditions.append(condition)
                        all_conditions.append({**condition, "work_id": task_id, "segment_id": span_id})
                        condition_ids.append(condition["id"])
                work_items.append({"id": task_id, "work": name, "evidence": _span(text, a, b),
                                   "segment_id": span_id, "conditions": task_conditions})
                task_ids.append(task_id)
            for qa, qb, kind, value, unit in unattached_quantities:
                condition = {"id": f"c{qa}_{qb}", "kind": kind, "value": value, "unit": unit,
                             "evidence": _span(text, qa, qb), "segment_id": span_id, "unattached": True}
                all_conditions.append(condition)
                condition_ids.append(condition["id"])
            if classification == "unconfirmed":
                unconfirmed.append({"span_id": span_id, "text": phrase, "evidence": evidence, "reason": reason})
            else:
                surface_preview = [(a, b, m.group()) for a, b, m in _matches(_SURFACES, phrase, start)]
                residual = _unclassified_text(phrase, start, surface_preview, unique_hits)
                if residual or unattached_quantities:
                    classification, reason = "unconfirmed", "작업으로 분류하지 못한 원문 내용이 남음"
                    if re.search(r"합쳐서|공유|전체\s*수량|합계", residual):
                        for task in [item for item in work_items if item["segment_id"] == span_id]:
                            for condition in task["conditions"]:
                                condition["ambiguous"] = True
                                condition["unattached"] = True
                        for condition in all_conditions:
                            if condition.get("segment_id") == span_id:
                                condition["ambiguous"] = True
                                condition["unattached"] = True
                    unconfirmed.append({"span_id": span_id, "text": phrase, "evidence": evidence,
                                        "reason": reason, "unclassified_text": residual})
        else:
            surface_hits = [(a, b, m.group()) for a, b, m in _matches(_SURFACES, phrase, start)]
            # 콘크리트는 벽·바닥 바탕으로만 쓰일 때 표면으로 분류한다.
            for a, b, surface in surface_hits:
                sid = f"b{a}_{b}"
                substrates.append({"id": sid, "surface": surface, "evidence": _span(text, a, b),
                                   "segment_id": span_id})
                substrate_ids.append(sid)
            quantities = [(a, b, "repeat_count", m.group(1), "회", m)
                          for a, b, m in _matches(_REPEAT, phrase, start)]
            quantities += [(a, b, "quantity", m.group(1), m.group(2), m)
                           for a, b, m in _matches(_MEASURE, phrase, start)]
            residual = _unclassified_text(phrase, start, surface_hits)
            if surface_hits and not residual:
                classification, reason = "background", None
            elif quantities and not residual:
                classification, reason = "condition", "작업에 연결되지 않은 조건"
            else:
                classification, reason = "unconfirmed", "지원하는 작업으로 분류하지 못한 원문 구절"
            if classification == "unconfirmed":
                unconfirmed.append({"span_id": span_id, "text": phrase, "evidence": evidence, "reason": reason})
            for qa, qb, kind, value, unit, match in quantities:
                condition = {"id": f"c{qa}_{qb}", "kind": kind, "value": value, "unit": unit,
                             "evidence": _span(text, qa, qb), "segment_id": span_id, "unattached": True}
                all_conditions.append(condition)
                condition_ids.append(condition["id"])

        # 요청 문구에 붙은 작업이 아닌 기존 바탕면도 별도 자료로 보존한다.
        if unique_hits:
            for a, b, m in _matches(_SURFACES, phrase, start):
                sid = f"b{a}_{b}"
                if not any(existing["id"] == sid for existing in substrates):
                    substrates.append({"id": sid, "surface": m.group(), "evidence": _span(text, a, b),
                                       "segment_id": span_id})
                    substrate_ids.append(sid)

        # 숫자가 0 이하이거나 단위를 안전하게 넘길 수 없으면 확인 없이 계획에 넣지 않는다.
        for task in [item for item in work_items if item["segment_id"] == span_id]:
            for condition in task["conditions"]:
                try:
                    positive = Decimal(condition["value"].replace(",", "")) > 0
                except (InvalidOperation, ValueError):
                    positive = False
                if not positive:
                    unconfirmed.append({"span_id": span_id, "text": phrase, "evidence": condition["evidence"],
                                       "reason": "수량은 양수인지 확인해야 합니다"})
                    classification = "unconfirmed"
                    reason = "수량은 양수인지 확인해야 합니다"

        known_condition_ids = {condition["id"] for condition in all_conditions}
        for method_pattern in _METHODS.values():
            for method in method_pattern.finditer(phrase):
                qa, qb = start + method.start(), start + method.end()
                cid = f"c{qa}_{qb}"
                if cid not in known_condition_ids:
                    all_conditions.append({"id": cid, "kind": "condition", "value": method.group(),
                                          "unit": None, "evidence": _span(text, qa, qb),
                                          "segment_id": span_id, "unattached": True})
                    condition_ids.append(cid)
                    known_condition_ids.add(cid)
        for a, b, match in _matches(_REPEAT, phrase, start):
            cid = f"c{a}_{b}"
            if cid not in known_condition_ids:
                all_conditions.append({"id": cid, "kind": "repeat_count", "value": match.group(1), "unit": "회",
                                      "evidence": _span(text, a, b), "segment_id": span_id, "unattached": True})
                condition_ids.append(cid)
                known_condition_ids.add(cid)
        for a, b, match in _matches(_MEASURE, phrase, start):
            cid = f"c{a}_{b}"
            if cid not in known_condition_ids:
                all_conditions.append({"id": cid, "kind": "quantity", "value": match.group(1), "unit": match.group(2),
                                      "evidence": _span(text, a, b), "segment_id": span_id, "unattached": True})
                condition_ids.append(cid)
                known_condition_ids.add(cid)

        segments.append({"span_id": span_id, **evidence, "classification": classification,
                         "reason": reason, "work_ids": task_ids, "substrate_ids": substrate_ids,
                         "condition_ids": condition_ids,
                         "alternative_group": alternative_group if alt else None})
        previous_connector = raw.get("connector_after")

    # 표면 언급과 작업 구절이 나뉜 경우에도 표면은 바탕으로 남긴다.
    # 한 작업 구절의 여러 물량은 단위나 의도를 임의로 고르지 않는다.
    for segment in segments:
        task_list = [task for task in work_items if task["segment_id"] == segment["span_id"]]
        qty_count = sum(len(task["conditions"]) for task in task_list)
        if len(task_list) > 1 and qty_count:
            for task in task_list:
                task["conditions"] = []
            segment["classification"] = "unconfirmed"
            segment["reason"] = "작업별 수량 소속을 확인해야 함"
            unconfirmed.append({"span_id": segment["span_id"], "text": segment["text"],
                                "evidence": _span(text, segment["start"], segment["end"]),
                                "reason": segment["reason"]})

    # 같은 구절에서 분류되지 않은 일상적인 요청 끝말은 그대로 보존하고 확인을 요구한다.
    unconfirmed = _dedupe_unconfirmed(unconfirmed)
    question = []
    if unconfirmed:
        question.append("미확정 구절과 대안을 작업에 넣을지, 뺄지 또는 조건으로 볼지 확인해 주세요.")
    if exclusions:
        question.append("제외 요청을 그대로 적용할지 확인해 주세요.")
    if any(len([w for w in work_items if w["segment_id"] == segment["span_id"]]) > 1 for segment in segments):
        question.append("한 구절에 있는 여러 작업의 수량을 나누어 알려 주세요.")
    if len(work_items) > 1:
        question.append("여러 작업이 확인됐습니다. 이번 단계에서는 한 작업만 계획으로 만들 수 있습니다.")

    decision_spans = list(segments)
    for substrate in substrates:
        decision_spans.append({"span_id": substrate["id"], **substrate["evidence"],
                               "classification": "background", "reason": None,
                               "work_ids": [], "substrate_ids": [substrate["id"]], "condition_ids": [],
                               "alternative_group": None})
    for condition in all_conditions:
        decision_spans.append({"span_id": condition["id"], **condition["evidence"],
                               "classification": "condition", "reason": condition.get("unattached"),
                               "work_ids": [condition["work_id"]] if condition.get("work_id") else [],
                               "substrate_ids": [], "condition_ids": [condition["id"]],
                               "alternative_group": None})
    result = {"analysis_version": ANALYSIS_VERSION, "source_text": text, "scope_spans": decision_spans,
              "work_items": work_items, "substrates": substrates, "conditions": all_conditions,
              "excluded_requests": exclusions, "unconfirmed_scope": unconfirmed,
              "questions": list(dict.fromkeys(question)), "calculation": {"mode": "not_ready"},
              "limitations": ["규칙 분석은 보조용이며 일부 익숙한 작업 표현만 인식합니다. 알 수 없는 구절은 미확정으로 남깁니다."]}
    result["analysis_hash"] = _analysis_hash(result)
    return result


_NON_SCOPE_WORDS = re.compile(r"견적|공사비|계산|산출|알려|해주세요|해줘|해\s*줘|부탁|포함|전체|공사|작업|요청|좀|만|현재|기존|새로|신설|시공|해야|하는지|여부|견적서|수성|유성|에다?|에서|으로|의|을|를|은|는|도|내부|외부|실내|실외|바탕|칠해|칠하|칠|다시")


def _unclassified_text(phrase: str, start: int, surface_hits: list[tuple[int, int, str]],
                       task_hits: list[tuple[int, int, str]] | None = None) -> str:
    chars = list(phrase)
    spans = [(a - start, b - start) for a, b, _ in surface_hits]
    spans += [(a - start, b - start) for a, b, _ in (task_hits or [])]
    spans += [(m.start(), m.end()) for pattern in (_MEASURE, _REPEAT) for m in pattern.finditer(phrase)]
    spans += [(m.start(), m.end()) for pattern in _METHODS.values() for m in pattern.finditer(phrase)]
    for left, right in spans:
        for pos in range(left, right):
            chars[pos] = " "
    remainder = "".join(chars)
    return _NON_SCOPE_WORDS.sub(" ", remainder).strip()


def _dedupe_unconfirmed(items: list[dict]) -> list[dict]:
    result, seen = [], set()
    for item in items:
        key = (item["span_id"], item["evidence"]["start"], item["evidence"]["end"], item["reason"])
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result


def validate_model_analysis(text: str, proposed: dict) -> dict[str, Any]:
    """모델 결과를 위치·분류 대조에 사용한다. 빠진 구절은 결과에서 미확정으로 남긴다."""
    if not isinstance(proposed, dict) or set(proposed) != {"work_items", "substrates", "excluded_requests", "unconfirmed_scope"}:
        raise ValueError("모델 분석 결과의 필드가 올바르지 않습니다")
    if any(not isinstance(value, list) for value in proposed.values()):
        raise ValueError("모델 분석 결과는 목록 형식이어야 합니다")
    analysis = analyze_request(text)
    supported_names = set(_WORKS)
    accepted_work = []
    observed_conditions = set()
    unsupported_model = []
    observed = {"work_items": set(), "substrates": set(), "excluded_requests": set(), "unconfirmed_scope": set()}

    def quote_span(evidence: Any) -> tuple[int, int, str]:
        if isinstance(evidence, dict) and set(evidence) == {"text", "start", "end"}:
            quote, start, end = evidence["text"], evidence["start"], evidence["end"]
            if (not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int)
                    or isinstance(end, bool) or start < 0 or end <= start or text[start:end] != quote):
                raise ValueError("근거 위치가 원문과 다릅니다")
        elif isinstance(evidence, str):
            quote = evidence
            start = text.find(quote)
            if start >= 0 and text.find(quote, start + 1) >= 0:
                raise ValueError("중복 구절은 시작 위치를 함께 보내야 합니다")
            end = start + len(quote)
        else:
            raise ValueError("근거는 원문 구절과 시작·끝 위치가 필요합니다")
        if not isinstance(quote, str) or not quote.strip():
            raise ValueError("근거 구절이 비어 있습니다")
        return start, end, quote

    for field, entity_name in (("work_items", "work"), ("substrates", "surface"),
                               ("excluded_requests", "work")):
        for item in proposed[field]:
            if not isinstance(item, dict) or "id" in item:
                raise ValueError("모델이 임의 항목 ID를 만들었거나 항목 형식이 올바르지 않습니다")
            if field == "work_items" and not isinstance(item.get("conditions"), list):
                raise ValueError("모델 작업의 조건 목록 형식이 올바르지 않습니다")
            label = item.get(entity_name)
            begin, finish, quote = quote_span(item.get("evidence"))
            if not isinstance(label, str) or not label:
                raise ValueError("모델 항목 이름이 없습니다")
            if field == "work_items":
                if label not in supported_names:
                    unsupported_model.append({"span_id": f"s{begin}_{finish}", "text": text[begin:finish],
                                              "evidence": _span(text, begin, finish),
                                              "reason": "모델이 제안했지만 공종을 안전하게 연결할 수 없음"})
                    continue
                target = next((task for task in analysis["work_items"] if task["work"] == label
                               and task["evidence"]["start"] >= begin and task["evidence"]["end"] <= finish), None)
                if not target:
                    raise ValueError("모델 작업 이름이 해당 원문 위치의 요청 작업과 다릅니다")
                key = target["id"]
                if key in observed[field]:
                    raise ValueError("모델이 같은 작업 구절을 중복했습니다")
                observed[field].add(key)
                for condition in item.get("conditions", []):
                    if not isinstance(condition, dict) or "id" in condition:
                        raise ValueError("모델 조건 형식이 올바르지 않습니다")
                    cb, ce, condition_quote = quote_span(condition.get("evidence"))
                    segment = next(span for span in analysis["scope_spans"]
                                   if span["span_id"] == target["segment_id"])
                    if cb < segment["start"] or ce > segment["end"]:
                        raise ValueError("조건 근거가 해당 작업 구절 밖에 있습니다")
                    match = next((known for known in target["conditions"]
                                  if known["kind"] == condition.get("kind")
                                  and known["value"] == condition.get("value")
                                  and known.get("unit") == condition.get("unit")
                                  and known["evidence"]["start"] >= cb and known["evidence"]["end"] <= ce), None)
                    if not match:
                        raise ValueError("모델 조건의 수량·단위·작업 소속이 원문 분석과 다릅니다")
                    observed_conditions.add(match["id"])
            elif field == "substrates":
                if label not in text[begin:finish]:
                    raise ValueError("바탕면 이름이 근거와 다릅니다")
                target = next((surface for surface in analysis["substrates"] if surface["surface"] == label
                               and surface["evidence"]["start"] >= begin and surface["evidence"]["end"] <= finish), None)
                if not target:
                    raise ValueError("원문에서 바탕면으로 확인되지 않은 값입니다")
                observed[field].add(target["id"])
            else:
                target = next((entry for entry in analysis["excluded_requests"] if entry.get("work") == label
                               and entry["evidence"]["start"] >= begin and entry["evidence"]["end"] <= finish), None)
                if not target:
                    raise ValueError("원문에서 제외 요청으로 확인되지 않은 값입니다")
                observed[field].add(target["span_id"])

    for item in proposed["unconfirmed_scope"]:
        if not isinstance(item, dict) or "id" in item or not isinstance(item.get("text"), str):
            raise ValueError("미확정 구절 형식이 올바르지 않습니다")
        begin, finish, quote = quote_span(item.get("evidence"))
        if text[begin:finish] != item["text"]:
            raise ValueError("미확정 내용이 근거 구절과 다릅니다")
        target = next((entry for entry in analysis["unconfirmed_scope"]
                       if entry["evidence"]["start"] >= begin and entry["evidence"]["end"] <= finish), None)
        if target:
            observed["unconfirmed_scope"].add(target["span_id"])

    # 모델이 놓친 규칙 분석 구절도 미확정으로 되돌린다. 근거가 있다는 이유로 준비 완료하지 않는다.
    gaps = []
    for field in ("work_items", "substrates", "excluded_requests", "unconfirmed_scope"):
        for expected in analysis[field]:
            key = expected["id"] if field in ("work_items", "substrates") else expected["span_id"]
            if key not in observed[field]:
                span = expected["evidence"]
                gaps.append({"span_id": expected.get("segment_id", expected.get("span_id", key)),
                             "text": span["text"], "evidence": span,
                             "reason": "모델 결과에서 원문 구절을 확인하지 못함"})
    for condition in analysis["conditions"]:
        if condition["id"] not in observed_conditions:
            gaps.append({"span_id": condition.get("segment_id", "condition"),
                         "text": condition["evidence"]["text"], "evidence": condition["evidence"],
                         "reason": "모델 결과에서 조건이나 작업별 수량 연결을 확인하지 못함"})
    analysis["unconfirmed_scope"] = _dedupe_unconfirmed(analysis["unconfirmed_scope"] + gaps + unsupported_model)
    if analysis["unconfirmed_scope"]:
        analysis["questions"] = list(dict.fromkeys(analysis["questions"] + [
            "모델이 놓치거나 분류하지 못한 구절을 확인해 주세요."]))
    analysis["calculation"] = {"mode": "not_ready"}
    analysis["analysis_hash"] = _analysis_hash({key: value for key, value in analysis.items() if key != "analysis_hash"})
    return analysis


def analyze_request_with_model(text: str, generate=None) -> dict[str, Any]:
    """명시적으로 호출할 때만 기존 LLM 클라이언트(또는 주입 모의 함수)를 실행한다."""
    if generate is None:
        from backend.agent.tools.llm.client import generate as llm_generate
        generate = llm_generate
    try:
        response = generate(text, "작업·바탕·조건·제외·미확정 구절을 원문에서 빠짐없이 분류하세요. 추정은 미확정으로 두고, 각 항목에 정확한 근거 구절을 적으세요.",
                            response_schema=MODEL_ANALYSIS_SCHEMA, timeout_ms=5000, max_attempts=1)
        raw = response.text if hasattr(response, "text") else response
        proposal = json.loads(raw) if isinstance(raw, str) else raw
        return validate_model_analysis(text, proposal)
    except Exception as exc:
        result = analyze_request(text)
        for span in result["scope_spans"]:
            span["classification"] = "unconfirmed"
            span["reason"] = "모델 분석이 실패해 사람이 확인해야 함"
        result["unconfirmed_scope"].append({"span_id": result["scope_spans"][0]["span_id"], "text": text,
                                           "evidence": _span(text, 0, len(text)),
                                           "reason": f"모델 분석 실패: {type(exc).__name__}"})
        result["questions"] = list(dict.fromkeys(result["questions"] + ["모델 분석 실패로 모든 작업 범위를 확인해야 합니다."]))
        result["calculation"] = {"mode": "not_ready"}
        result["analysis_hash"] = _analysis_hash({key: value for key, value in result.items() if key != "analysis_hash"})
        return result


def _decision_digest(decisions: list[dict]) -> str:
    return _json_hash(decisions)


def confirm_analysis(text: str, analysis: dict, decisions: list[dict]) -> dict[str, Any]:
    """모든 분석 구절에 대한 사람의 선택을 검증하고 원문/버전에 묶인 확인증을 만든다."""
    if (not isinstance(analysis, dict) or analysis.get("analysis_version") != ANALYSIS_VERSION
            or analysis.get("source_text") != text or analysis.get("analysis_hash") != _analysis_hash(analysis)):
        raise ValueError("분석 결과가 원문 또는 현재 분석 버전과 다릅니다")
    if not isinstance(decisions, list):
        raise ValueError("확인 선택은 목록이어야 합니다")
    spans = {span["span_id"]: span for span in analysis["scope_spans"]}
    received = {}
    for entry in decisions:
        if not isinstance(entry, dict) or set(entry) - {"span_id", "action", "work"}:
            raise ValueError("확인 선택 형식이 올바르지 않습니다")
        span_id, action = entry.get("span_id"), entry.get("action")
        if span_id not in spans or span_id in received:
            raise ValueError("확인 대상이 없거나 중복되었습니다")
        span = spans[span_id]
        allowed = {"requested": {"include_work", "exclude_work"},
                   "excluded": {"keep_excluded", "include_work"},
                   "background": {"keep_background"}, "condition": {"keep_condition"},
                   "unconfirmed": {"include_work", "exclude_work", "keep_condition", "keep_background"}}
        if action not in allowed[span["classification"]]:
            raise ValueError("이 구절에 허용되지 않은 선택입니다")
        normalized = {"span_id": span_id, "action": action}
        if action == "include_work" and span["classification"] in ("unconfirmed", "excluded"):
            work = entry.get("work")
            if not isinstance(work, str) or not work.strip() or work not in span["text"]:
                raise ValueError("포함할 작업 이름은 해당 원문 구절 안에서 골라야 합니다")
            recognized = [task["work"] for task in analysis["work_items"]
                          if task["segment_id"] == span_id]
            if recognized and work not in recognized:
                raise ValueError("이 구절에 이미 인식된 작업 후보가 있습니다. 후보 중 하나를 선택하거나 범위를 나누어 확인해 주세요")
            normalized["work"] = work
        received[span_id] = normalized
    if set(received) != set(spans):
        raise ValueError("아직 선택하지 않은 원문 구절이 있습니다")
    normalized = [received[key] for key in sorted(received, key=lambda value: spans[value]["start"])]
    body = {"version": ANALYSIS_VERSION, "source_hash": _json_hash(text),
            "analysis_hash": analysis["analysis_hash"], "decisions": normalized}
    receipt = {**body, "decision_hash": _decision_digest(normalized)}
    receipt["receipt_hash"] = _json_hash(receipt)
    return {"status": "confirmed_scope", "confirmation": receipt}


def confirmed_result(text: str, analysis: dict, confirmation: dict) -> dict[str, Any]:
    """재검증한 확인증으로만 단일 공종 호환 계획을 만든다."""
    if (not isinstance(analysis, dict) or analysis.get("analysis_version") != ANALYSIS_VERSION
            or analysis.get("analysis_hash") != _analysis_hash(analysis) or analysis.get("source_text") != text):
        raise ValueError("분석 결과가 변경되어 확인을 다시 받아야 합니다")
    if not isinstance(confirmation, dict) or set(confirmation) != {
            "version", "source_hash", "analysis_hash", "decisions", "decision_hash", "receipt_hash"}:
        raise ValueError("확인증 형식이 올바르지 않습니다")
    check = dict(confirmation)
    receipt_hash = check.pop("receipt_hash")
    if receipt_hash != _json_hash(check):
        raise ValueError("확인증 값이 바뀌었습니다")
    if (confirmation["version"] != ANALYSIS_VERSION or confirmation["source_hash"] != _json_hash(text)
            or confirmation["analysis_hash"] != analysis["analysis_hash"]
            or confirmation["decision_hash"] != _decision_digest(confirmation["decisions"])):
        raise ValueError("확인증이 현재 원문이나 분석에 연결되지 않습니다")
    # 다시 검증해 대상 누락·중복·허용되지 않은 선택을 막는다.
    verified = confirm_analysis(text, analysis, confirmation["decisions"])
    if verified["confirmation"] != confirmation:
        raise ValueError("확인증이 현재 선택 목록과 다릅니다")

    decisions = {entry["span_id"]: entry for entry in confirmation["decisions"]}
    span_map = {span["span_id"]: span for span in analysis["scope_spans"]}
    confirmed_excluded = [entry for entry in analysis["excluded_requests"]
                          if decisions[entry["segment_id"]]["action"] == "keep_excluded"]
    existing_exclusions = {entry["segment_id"] for entry in confirmed_excluded}
    for span_id, decision in decisions.items():
        span = span_map[span_id]
        if decision["action"] == "exclude_work" and span["classification"] != "excluded":
            if span_id not in existing_exclusions:
                confirmed_excluded.append({"work": decision.get("work", span["text"]),
                                           "evidence": _span(text, span["start"], span["end"]),
                                           "segment_id": span_id})
                existing_exclusions.add(span_id)
    included = []
    for task in analysis["work_items"]:
        action = decisions[task["segment_id"]]["action"]
        if action == "include_work":
            included.append(dict(task, conditions=list(task["conditions"])))
    for span_id, decision in decisions.items():
        span = span_map[span_id]
        if decision["action"] == "include_work" and not span["work_ids"]:
            evidence_start = text.find(decision["work"], span["start"], span["end"])
            method_task = any(pattern.fullmatch(decision["work"]) for pattern in _METHODS.values())
            task_name = "도장" if method_task else decision.get("work")
            included.append({"id": f"w{evidence_start}_{evidence_start + len(decision['work'])}",
                             "work": task_name,
                             "evidence": _span(text, evidence_start, evidence_start + len(decision["work"])),
                             "segment_id": span_id,
                             "conditions": [condition for condition in analysis["conditions"]
                                            if condition.get("segment_id") == span_id]})
        elif (decision["action"] == "include_work" and span["classification"] == "unconfirmed"
              and decision.get("work") and not any(task.get("segment_id") == span_id
                                                     and task["work"] == decision["work"] for task in included)):
            evidence_start = text.find(decision["work"], span["start"], span["end"])
            method_task = any(pattern.fullmatch(decision["work"]) for pattern in _METHODS.values())
            task_name = "도장" if method_task else decision["work"]
            included.append({"id": f"w{evidence_start}_{evidence_start + len(decision['work'])}",
                             "work": task_name,
                             "evidence": _span(text, evidence_start, evidence_start + len(decision["work"])),
                             "segment_id": span_id,
                             "conditions": [condition for condition in analysis["conditions"]
                                            if condition.get("segment_id") == span_id]})

    if any(condition.get("ambiguous") for task in included for condition in task["conditions"]):
        return {"status": "confirmed_scope", "work_items": included,
                "calculation": {"mode": "not_ready", "blocked": True,
                                "reason": "한 작업의 전체 수량을 나눌 수 없습니다."},
                "confirmation": confirmation}
    # 확인한 별도 조건은 작업 하나에만 붙인다. 둘 이상이면 소속을 묻고 멈춘다.
    included_condition_ids = {condition["id"] for task in included for condition in task["conditions"]}
    unattached = [condition for condition in analysis["conditions"] if condition.get("unattached")
                  and condition["id"] not in included_condition_ids
                  and decisions[condition["id"]]["action"] == "keep_condition"
                  and decisions[condition["segment_id"]]["action"] not in ("keep_excluded", "exclude_work")]
    remaining_unattached = []
    for condition in unattached:
        owner = [task for task in included if task["segment_id"] == condition["segment_id"]]
        if len(owner) == 1:
            if not any(existing["id"] == condition["id"] for existing in owner[0]["conditions"]):
                owner[0]["conditions"].append(condition)
        else:
            remaining_unattached.append(condition)
    if remaining_unattached:
        return {"status": "confirmed_scope", "work_items": included,
                "calculation": {"mode": "not_ready", "blocked": True,
                                "reason": "작업에 연결되지 않은 조건이 남아 있습니다."},
                "confirmation": confirmation}

    if len(included) != 1:
        return {"status": "confirmed_scope", "source_text": text, "work_items": included,
                "substrates": analysis["substrates"], "excluded_requests": confirmed_excluded,
                "unconfirmed_scope": [], "calculation": {"mode": "not_ready",
                "reason": "이번 단계는 확인된 단일 작업만 기존 세션 계획으로 바꿉니다."}, "confirmation": confirmation}
    task = included[0]
    quantities = [condition for condition in task["conditions"] if condition["kind"] == "quantity"]
    try:
        invalid_quantity = any(Decimal(q["value"].replace(",", "")) <= 0 for q in quantities)
    except InvalidOperation:
        invalid_quantity = True
    # 서로 다른 단위는 도구에 보내기 전에 물량으로 단정하지 않는다. 원문 조건으로 보존해
    # 선택 명세가 실제 물량 단위(예: ㎜ 두께와 ㎡ 면적)를 가른 뒤 기존 입력 파서가 연결한다.
    repeated_same_unit = len({condition.get("unit") for condition in quantities}) < len(quantities)
    if repeated_same_unit or invalid_quantity:
        return {"status": "confirmed_scope", "work_items": included, "calculation": {"mode": "not_ready",
                "blocked": True, "reason": "한 작업에 같은 단위의 수량이 둘 이상 있습니다."},
                "confirmation": confirmation}
    task_conditions = list(task["conditions"])
    selected_background = [substrate for substrate in analysis["substrates"]
                           if decisions[substrate["id"]]["action"] == "keep_background"]
    task_segment = span_map[task["segment_id"]]
    selected_text = task_segment["text"]
    if task["work"] not in selected_text:
        selected_text = f"{task['work']} {selected_text}"
    request_parts = [(task_segment["start"], selected_text)]
    request_parts.extend((condition["evidence"]["start"], condition["evidence"]["text"])
                         for condition in task_conditions
                         if not (task_segment["start"] <= condition["evidence"]["start"]
                                 and condition["evidence"]["end"] <= task_segment["end"]))
    request_parts.extend((substrate["evidence"]["start"], substrate["evidence"]["text"])
                         for substrate in selected_background
                         if substrate.get("segment_id") != task["segment_id"])
    request_text = " ".join(part for _, part in sorted(set(request_parts)))
    source_spans = [{"kind": "work", "value": task["work"], **task["evidence"]}]
    source_spans.extend({"kind": condition["kind"], "value": condition["value"], **condition["evidence"]}
                        for condition in task_conditions)
    source_spans.extend({"kind": "background", "value": substrate["surface"], **substrate["evidence"]}
                        for substrate in selected_background)
    item = {"item_id": "i1", "request_text": request_text, "source_spans": source_spans}
    if len(quantities) == 1:
        from backend.agent.estimate.state import unit_key
        if unit_key(quantities[0]["unit"]) is None:
            return {"status": "confirmed_scope", "work_items": included,
                    "calculation": {"mode": "not_ready", "blocked": True,
                                    "reason": "기존 세션에서 처리할 수 없는 단위입니다."},
                    "confirmation": confirmation}
        item["quantity"] = {"value": quantities[0]["value"], "unit": quantities[0]["unit"]}
    plan = {"original_request": text, "items": [item]}
    return {"status": "confirmed_scope", "source_text": text, "work_items": included,
            "substrates": analysis["substrates"], "excluded_requests": confirmed_excluded,
            "unconfirmed_scope": [], "confirmation": confirmation,
            "calculation": {"mode": "single_trade", "plan": plan}}


if __name__ == "__main__":
    import sys

    print(json.dumps(analyze_request(" ".join(sys.argv[1:])), ensure_ascii=False, indent=2))
