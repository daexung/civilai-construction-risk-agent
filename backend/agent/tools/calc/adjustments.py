"""초안의 품 할증·감은 같은 절의 원문과 일치할 때만 적용한다."""

from __future__ import annotations

import re
from fractions import Fraction

from backend.agent.tools.calc.numbers import parse_fraction
from backend.agent.tools.calc.daily_crew import _exact_text
from backend.agent.tools.source.citation import _chunks, cite_table, resolve_cites

BLOCK_REASON = "이 할증 규칙은 아직 자동 계산하지 않음"
RANGE_WORDS = ("까지", "이내", "범위", "정도", "내외", "이상 적용")
ACTION_WORDS = ("가산", "감", "요율", "적용", "산정", "계상")


def _number(text: str) -> tuple[str, Fraction] | None:
    additions = re.findall(r"(\d+(?:\.\d+)?)\s*%\s*(?:를\s*)?가산", text)
    reductions = re.findall(r"(\d+(?:\.\d+)?)\s*%\s*(?:를\s*)?감(?:하여)?", text)
    multipliers = re.findall(r"[×xX*]\s*(0?\.\d+|\d+(?:\.\d+)?)", text)
    percent_multipliers = re.findall(r"(\d+(?:\.\d+)?)\s*%\s*승수", text)
    if len(additions) + len(reductions) + len(multipliers) + len(percent_multipliers) != 1:
        return None
    if additions:
        return "가산", parse_fraction(additions[0]) / 100
    if reductions:
        return "감", parse_fraction(reductions[0]) / 100
    if percent_multipliers:
        return "승수", parse_fraction(percent_multipliers[0]) / 100
    return "승수", parse_fraction(multipliers[0])


def _norm(value: object) -> str:
    return re.sub(r"\s+", "", str(value)).replace("~", "∼")


def _conditions(item: dict) -> dict:
    when = item.get("when") or {}
    return when if isinstance(when, dict) else {}


def matches(item: dict, inputs: dict) -> bool:
    for name, expected in _conditions(item).items():
        if isinstance(expected, str) and (match := re.fullmatch(r"\s*(>=|<=|>|<|==|!=)\s*(\d+(?:\.\d+)?)\s*", expected)):
            if name not in inputs:
                return False
            try:
                actual = parse_fraction(inputs[name])
                target = parse_fraction(match.group(2))
            except (ValueError, ZeroDivisionError):
                return False
            op = match.group(1)
            if not {">": actual > target, ">=": actual >= target, "<": actual < target,
                    "<=": actual <= target, "==": actual == target, "!=": actual != target}[op]:
                return False
        elif isinstance(expected, dict) and ("min" in expected or "max" in expected):
            if name not in inputs:
                return False
            try:
                actual = parse_fraction(inputs[name])
                lower = parse_fraction(expected["min"]) if "min" in expected else None
                upper = parse_fraction(expected["max"]) if "max" in expected else None
            except (ValueError, TypeError, ZeroDivisionError):
                return False
            if lower is not None and not (actual >= lower if expected.get("min_inclusive", True) else actual > lower):
                return False
            if upper is not None and not (actual <= upper if expected.get("max_inclusive", True) else actual < upper):
                return False
        elif inputs.get(name) != expected:
            return False
    return True


def _target(item: dict) -> Fraction | None:
    try:
        if item.get("rate") is not None:
            return parse_fraction(item["rate"])
    except (ValueError, ZeroDivisionError):
        pass
    parsed = _number(str(item.get("change", "")))
    return parsed[1] if parsed else None


def _sentences(chunk: dict) -> list[str]:
    sentences = []
    for raw in chunk["text"].splitlines()[1:]:
        line = raw.split(" | ", 1)[-1].strip()
        line = re.sub(r"(?:^|\s)-\s+(?=[가-힣])", ". ", line)
        sentences.extend(part.strip(" .") + "." for part in re.split(r"(?<=다\.)\s*", line)
                         if part.strip(" ."))
    return sentences


def _percent_values(sentence: str) -> list[Fraction]:
    return [parse_fraction(number) / 100
            for number in re.findall(r"(\d+(?:\.\d+)?)\s*%", sentence)]


def _evidence(spec: dict, item: dict, inputs: dict | None = None) -> dict | None:
    target = _target(item)
    scoped = [chunk for chunk in _chunks() if chunk.get("section_no") == spec.get("section_no")
              and chunk.get("division") == spec.get("division")]
    application_cite = item.get("application_cite")
    if application_cite and not item.get("rate_table"):
        chunk = next((entry for entry in scoped
                      if entry.get("chunk_id") == application_cite.get("chunk_id")), None)
        quote = str(application_cite.get("quote", ""))
        if (chunk is None or not quote or _norm(quote) not in _norm(chunk.get("text", ""))
                or not any(word in quote for word in ACTION_WORDS)):
            return None
        parsed = _number(quote)
        matched = (parsed is not None and
                   (parsed[1] == target or (parsed[0] == "감" and target is not None
                                            and target < 0 and parsed[1] == abs(target))))
        quoted_rates = _percent_values(quote)
        # A source sentence may state separate rates for separate exact
        # conditions. Accept the condition's rate only when it occurs once in
        # this exact citation; caller matching already requires the rule's
        # declared inputs to match.
        matched = matched or (target is not None and quoted_rates.count(target) == 1)
        if not matched:
            return None
        evidence_rate = abs(target) if parsed and parsed[0] == "감" and target < 0 else target
        return {"chunk": chunk, "quote": quote, "citations": resolve_cites(application_cite),
                "rate": evidence_rate, "source_kind": "sentence"}
    # 한 문장 안에서 비율과 적용 동사를 함께 확인한다.
    def has_exact_rate(sentence: str) -> bool:
        if target is None:
            return False
        parsed = _number(sentence)
        if _percent_values(sentence) == [target]:
            return True
        return parsed is not None and parsed[1] == target

    sentence_pairs = [(chunk, sentence.strip(" .-|")) for chunk in scoped for sentence in _sentences(chunk)
                      if has_exact_rate(sentence) and any(word in sentence for word in ACTION_WORDS)]
    sentences = list({(chunk["chunk_id"], sentence): (chunk, sentence)
                      for chunk, sentence in sentence_pairs}.values())
    if len(sentences) == 1:
        chunk, quote = sentences[0]
        return {"chunk": chunk, "quote": quote, "citations": resolve_cites(
            {"chunk_id": chunk["chunk_id"], "quote": quote}), "rate": target, "source_kind": "sentence"}
    # 비율이 표에만 있으면 조건 머리글과 셀 값을 동시에 확인한다.
    table_hits = []
    conditions = {**(inputs or {}), **_conditions(item)}
    declared_rate_table = item.get("rate_table")
    for table in spec.get("tables", []):
        if declared_rate_table and table.get("id") != declared_rate_table.get("id"):
            continue
        if target is None and not any(word in table.get("role", "") for word in ("할증", "요율")):
            continue
        chunk = next((entry for entry in scoped if entry.get("chunk_id") == table.get("id")
                      and entry.get("kind") == "table"), None)
        if chunk is None:
            continue
        for row, columns in table.get("values", {}).items():
            if declared_rate_table and row != declared_rate_table.get("row", row):
                continue
            for column, raw in columns.items():
                if declared_rate_table and column != declared_rate_table.get("column", column):
                    continue
                if not any(_norm(value) == _norm(column) or _norm(value) == _norm(row)
                           for value in conditions.values()):
                    continue
                try:
                    raw_text = str(raw).strip()
                    if "%" in raw_text:
                        percentages = _percent_values(raw_text)
                        parsed = target if target in percentages else None
                    else:
                        parsed = parse_fraction(raw_text)
                        if (declared_rate_table and target is not None
                                and ("%" in str(table.get("unit", ""))
                                     or "(%)" in str(table.get("role", "")))):
                            parsed /= 100
                except (ValueError, ZeroDivisionError):
                    continue
                if parsed is None:
                    continue
                if (target is None or parsed == target) and _norm(column) in _norm(chunk["text"]):
                    table_hits.append((chunk, row, column, str(raw)))
    if len(table_hits) != 1:
        return None
    table_chunk, row, column, raw = table_hits[0]
    if target is None:
        target = parse_fraction(raw.strip().removesuffix("%")) / (100 if "%" in raw else 1)
    application_cite = item.get("application_cite")
    if application_cite:
        application_chunk = next((chunk for chunk in scoped
                                  if chunk.get("chunk_id") == application_cite.get("chunk_id")), None)
        quote = str(application_cite.get("quote", ""))
        normalized_quote = _norm(quote)
        if (application_chunk is None or not normalized_quote
                or normalized_quote not in _norm(application_chunk.get("text", ""))
                or not any(word in quote for word in ACTION_WORDS)):
            return None
        citations = [cite_table(table_chunk["chunk_id"], row, column, raw)]
        citations += resolve_cites(application_cite)
        return {"chunk": application_chunk, "quote": quote, "citations": citations,
                "rate": target, "source_kind": "table"}
    nearby = [(chunk, sentence) for chunk in scoped
              if chunk["source"]["page"] == table_chunk["source"]["page"]
              for sentence in _sentences(chunk)
              if "높이" in sentence and any(word in sentence for word in ACTION_WORDS)
              and "본 품은" not in sentence and "다." in sentence]
    if not nearby:
        return None
    # 가장 가까운 앞쪽 조각의 적용 문장을 선택한다.
    earlier = [entry for entry in nearby if int(entry[0]["chunk_id"].split("-")[1][1:]) <=
               int(table_chunk["chunk_id"].split("-")[1][1:])]
    application_chunk, quote = (earlier or nearby)[-1]
    citations = [cite_table(table_chunk["chunk_id"], row, column, raw)]
    citations += resolve_cites({"chunk_id": application_chunk["chunk_id"], "quote": quote})
    return {"chunk": application_chunk, "quote": quote, "citations": citations,
            "rate": target, "source_kind": "table"}


def _blocked(item: dict, evidence: dict | None, reason: str = BLOCK_REASON) -> dict:
    citation = evidence["citations"] if evidence else []
    return {"status": "blocked", "reason": reason, "source": item.get("source", ""),
            "citations": citation}


def _is_memo(item: dict) -> bool:
    numeric = " ".join(str(item.get(key, "")) for key in ("rate", "change"))
    return (not re.search(r"\d|%|×|[xX*]", numeric)
            and not re.search(r"\d+\s*%", str(item.get("source", ""))))


def classify_adjustment(spec: dict, item: dict) -> str:
    """재측정 보고서에서 조건 조합과 무관하게 규칙 한 건의 처리 범위를 센다."""
    text = " ".join(str(item.get(key, "")) for key in ("rate", "change", "source"))
    if _is_memo(item):
        return "memo"
    example_inputs = {}
    for field in spec.get("inputs", []):
        if field["type"] == "enum":
            example_inputs[field["name"]] = field["allowed_values"][0]
    example_inputs.update({key: value for key, value in _conditions(item).items()
                           if not (isinstance(value, str) and re.match(r"\s*[<>!=]", value))})
    evidence = _evidence(spec, item, example_inputs)
    if not evidence:
        return "blocked_other"
    quote = evidence["quote"]
    if (any(word in quote or word in text for word in RANGE_WORDS)
            and not item.get("source_rate_is_exact_for_condition")):
        return "blocked_range"
    if (any(word in text for word in ("산식", "누적", "복리"))
            or (evidence["source_kind"] != "table" and
                re.search(r"(?:매\s*\d+|증가시마다)", quote)
                and not item.get("source_rate_is_exact_for_condition"))):
        return "blocked_cumulative_formula"
    if "할 수 있" in quote:
        return "user_confirmation"
    return "automatic"


def adjustment_questions(spec: dict, inputs: dict) -> list[dict]:
    items = spec["quantity_model"]["params"].get("surcharges", []) + spec["quantity_model"]["params"].get("note_adjustments", [])
    questions = []
    for number, item in enumerate(items, 1):
        if not matches(item, inputs):
            continue
        evidence = _evidence(spec, item, inputs)
        if not evidence or "할 수 있" not in evidence["quote"]:
            continue
        name = f"apply_adj_{number}"
        if name in inputs:
            continue
        excerpt = evidence["quote"][:40]
        questions.append({"name": name,
                          "ask": f"품셈에 '{excerpt}' — 가산할 수 있다고 되어 있습니다. 적용할까요?",
                          "choices": ["예", "아니오"], "citations": evidence["citations"]})
    return questions


def apply_adjustments(spec: dict, inputs: dict, lines: list[dict]) -> dict:
    params = spec["quantity_model"]["params"]
    # Source notes sometimes give an absolute per-unit deduction for named
    # resources (rather than a percentage of the entire crew). Keep this
    # declarative and opt-in: every resource amount must be explicit and tied
    # to an exact source quote before it can change a line.
    for item in params.get("absolute_resource_adjustments", []):
        if not matches(item, inputs):
            continue
        cite = item.get("cite") or {}
        chunk_id = cite.get("chunk_id")
        quote = str(cite.get("quote", ""))
        source_chunk = next((chunk for chunk in _chunks()
                             if chunk.get("chunk_id") == chunk_id), None)
        if (source_chunk is None or not quote
                or _norm(quote) not in _norm(source_chunk.get("text", ""))):
            return _blocked(item, None, "absolute resource adjustment lacks an exact source quote")
        citations = resolve_cites(cite)
        if not citations:
            return _blocked(item, None, "absolute resource adjustment source citation is unresolved")
        for adjustment in item.get("resources", []):
            name = adjustment.get("name")
            matches_for_resource = [line for line in lines
                                    if line.get("name") == name and line.get("kind") == "labor"]
            if len(matches_for_resource) != 1:
                return _blocked(item, None, f"absolute adjustment must match one labor line: {name}")
            line = matches_for_resource[0]
            try:
                amount = parse_fraction(adjustment["amount"])
                current = Fraction(line["exact"])
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                return _blocked(item, None, f"invalid absolute adjustment for {name}")
            if amount < 0 or amount > current:
                return _blocked(item, None, f"absolute adjustment exceeds source quantity for {name}")
            line["exact"] = str(current - amount)
            line["applied"] = _exact_text(current - amount)
            line["formula"] = f"{line.get('formula', '')} − {amount}{adjustment.get('unit', '인')}"
            line["rule"] = f"source exact per-unit deduction: {quote}"
            line.setdefault("citations", []).extend(citations)
    items = params.get("surcharges", []) + params.get("note_adjustments", [])
    selected = [(number, item) for number, item in enumerate(items, 1)
                if matches(item, inputs) and (not item.get("implemented_by")
                                               or item.get("implemented_by") == "additional_materials_included_allowance")]
    applicable = []
    memos = []
    for number, item in selected:
        if item.get("implemented_by") == "additional_materials_included_allowance":
            # A source note can state that listed material coefficients already
            # include their loss allowance. In that case, link the note to the
            # exact material tables and retain the coefficient unchanged; do
            # not add the allowance a second time or treat it as a labor rate.
            material_table_ids = set(item.get("material_table_ids", []))
            declared_table_ids = {material.get("table") for material in
                                  params.get("additional_materials", []) if material.get("table")}
            cite = item.get("cite") or {}
            chunk = next((entry for entry in _chunks()
                          if entry.get("chunk_id") == cite.get("chunk_id")), None)
            quote = str(cite.get("quote", ""))
            if (not material_table_ids or not material_table_ids <= declared_table_ids
                    or chunk is None or not quote
                    or _norm(quote) not in _norm(chunk.get("text", ""))
                    or "할증이 포함" not in quote):
                return _blocked(item, None, "included material allowance lacks linked source tables or exact note citation")
            memos.append(item.get("source", "source material rate already includes allowance"))
            continue
        evidence = _evidence(spec, item, inputs)
        text = " ".join(str(item.get(key, "")) for key in ("rate", "change", "source"))
        if _is_memo(item):
            memos.append(item.get("source", ""))
            continue
        if evidence is None:
            return _blocked(item, evidence)
        quote = evidence["quote"]
        # 선택 적용 문구는 초안에서 삭제되었더라도 원문 기준으로 판정한다.
        if (any(word in quote or word in text for word in RANGE_WORDS)
                and not item.get("source_rate_is_exact_for_condition")):
            return _blocked(item, evidence, "할증률이 범위로 정해져 있어 적용 비율을 정해야 함")
        if (any(word in text for word in ("산식", "누적", "복리"))
                or (evidence["source_kind"] != "table" and
                    re.search(r"(?:매\s*\d+|증가시마다)", quote)
                    and not item.get("source_rate_is_exact_for_condition"))):
            return _blocked(item, evidence)
        if "할 수 있" in quote:
            answer = inputs.get(f"apply_adj_{number}")
            if answer not in ("예", "아니오"):
                return {"status": "ask", "missing": [f"apply_adj_{number}"],
                        "questions": adjustment_questions(spec, inputs)}
            if answer == "아니오":
                memos.append(f"사용자 선택: 미적용 — {quote}")
                continue
        operation = item.get("operation")
        parsed = _number(quote)
        if operation == "multiply":
            quote = evidence["quote"]
            table_multiplier = (evidence.get("source_kind") == "table"
                                and re.search(r"곱(?:하여|해|한다|한다면|한다\.)", quote))
            explicit_percent_multiplier = (
                evidence.get("source_kind") == "sentence"
                and evidence["rate"] in _percent_values(quote)
                and re.search(r"(?:본 품|품의).{0,16}\d+(?:\.\d+)?\s*%.*(?:적용|계상|곱)", quote))
            if not (table_multiplier or explicit_percent_multiplier):
                return _blocked(item, evidence)
            kind = "승수"
        elif operation is not None:
            return _blocked(item, evidence)
        else:
            kind = parsed[0] if parsed and parsed[1] == evidence["rate"] else "가산"
        quoted_rates = _percent_values(evidence["quote"])
        sentence_rate_matches = ((parsed is not None and
                                  (parsed[1] == evidence["rate"] or
                                   (parsed[0] == "감" and parsed[1] == abs(evidence["rate"]))))
                                 or (quoted_rates.count(evidence["rate"]) == 1
                                     and any(word in evidence["quote"] for word in ACTION_WORDS)))
        if (operation != "multiply" and evidence.get("source_kind") != "table"
                and not sentence_rate_matches):
            return _blocked(item, evidence)
        if "참조" in text and evidence.get("source_kind") != "table":
            return _blocked(item, evidence)
        applicable.append((item, kind, evidence["rate"], evidence))

    # 1-4-2: 감·승수는 기본품에 선적용하고 가산율은 합산한다.
    rule_quote = "W=기본품×(1＋a1＋a2＋a3＋………an)"
    rule_cite = resolve_cites({"chunk_id": "p80-x0", "quote": rule_quote}) if applicable else []
    for line in lines:
        if line["kind"] not in ("labor", "equipment"):
            continue
        selected_for_line = [entry for entry in applicable
                             if not entry[0].get("applies_to") or line["name"] in entry[0]["applies_to"]]
        if not selected_for_line:
            continue
        base = Fraction(line["exact"])
        multiplier = Fraction(1)
        additions = Fraction(0)
        adjustments = []
        seen = set()
        for item, kind, value, evidence in selected_for_line:
            quote = evidence["quote"]
            signature = (kind, value, quote)
            if signature in seen:
                continue
            seen.add(signature)
            if kind == "가산":
                additions += value
            elif kind == "감":
                multiplier *= 1 - value
            else:
                multiplier *= value
            citations = evidence["citations"]
            adjustments.append({"종류": kind, "값": str(value), "원문 인용": quote,
                                "citations": citations})
            line["citations"].extend(citations)
        if multiplier < 0:
            return _blocked(selected_for_line[0][0], selected_for_line[0][3])
        result = base * multiplier * (1 + additions)
        line["exact"] = str(result)
        # 일당 작업조의 단위당 품 자릿수는 기존 계산기의 정밀도에 맞춘다.
        if line["places"]:
            from backend.agent.tools.calc.unit_rounding import round_quantity
            line["applied"] = round_quantity(result, line["places"])
        else:
            line["applied"] = _exact_text(result)
        line["formula"] += f" × {multiplier} × (1 + {additions})" if multiplier != 1 else f" × (1 + {additions})"
        line["adjustments"] = adjustments
        line["citations"].extend(rule_cite)
    return {"status": "computed", "memos": memos}
