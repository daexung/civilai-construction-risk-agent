"""초안의 품 할증·감은 같은 절의 원문과 일치할 때만 적용한다."""

from __future__ import annotations

import re
from fractions import Fraction

from agent.tools.calc.numbers import parse_fraction
from agent.tools.source.citation import _chunks, resolve_cites

BLOCK_REASON = "이 할증 규칙은 아직 자동 계산하지 않음"
DISCRETIONARY = ("까지", "할 수 있", "이내", "범위", "정도", "내외", "이상 적용")


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


def _source(spec: dict, item: dict) -> tuple[dict | None, str | None]:
    source = str(item.get("source", ""))
    section = spec.get("section_no")
    division = spec.get("division")
    # 초안의 출처 문장은 청크의 표 머리글/설명 접두어를 생략할 수 있다.
    marker = re.sub(r"^(?:비고\s*[-–]\s*|\[주\]\s*)", "", source).strip()
    marker = marker[:16]
    for chunk in _chunks():
        if chunk.get("section_no") != section or chunk.get("division") != division:
            continue
        for line in chunk["text"].splitlines():
            if marker and marker in line:
                quote = line.split(" | ", 1)[-1].strip()
                return chunk, quote
    return None, None


def _blocked(item: dict, chunk: dict | None, quote: str | None) -> dict:
    citation = resolve_cites({"chunk_id": chunk["chunk_id"], "quote": quote}) if chunk else []
    return {"status": "blocked", "reason": BLOCK_REASON, "source": item.get("source", ""),
            "citations": citation}


def apply_adjustments(spec: dict, inputs: dict, lines: list[dict]) -> dict:
    params = spec["quantity_model"]["params"]
    selected = [item for item in params.get("surcharges", []) + params.get("note_adjustments", [])
                if all(inputs.get(name) == value for name, value in item.get("when", {}).items())]
    applicable = []
    memos = []
    for item in selected:
        chunk, quote = _source(spec, item)
        text = " ".join(str(item.get(key, "")) for key in ("rate", "change", "source"))
        if not re.search(r"\d|%|×|[xX*]", text):
            memos.append(item.get("source", ""))
            continue
        if chunk is None or quote is None:
            return _blocked(item, chunk, quote)
        # 선택 적용 문구는 초안에서 삭제되었더라도 원문 기준으로 판정한다.
        if any(word in quote or word in text for word in DISCRETIONARY):
            return _blocked(item, chunk, quote)
        if any(word in text for word in ("참조", "산식", "누적", "복리", "p188-t")):
            return _blocked(item, chunk, quote)
        parsed = _number(quote)
        if parsed is None:
            return _blocked(item, chunk, quote)
        kind, value = parsed
        declared = item.get("rate")
        if declared is not None:
            try:
                if parse_fraction(declared) != value:
                    return _blocked(item, chunk, quote)
            except (ValueError, ZeroDivisionError):
                return _blocked(item, chunk, quote)
        applicable.append((item, kind, value, chunk, quote))

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
        for item, kind, value, chunk, quote in selected_for_line:
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
            citation = resolve_cites({"chunk_id": chunk["chunk_id"], "quote": quote})[0]
            adjustments.append({"종류": kind, "값": str(value), "원문 인용": quote,
                                "citations": [citation]})
            line["citations"].append(citation)
        if multiplier < 0:
            return _blocked(selected_for_line[0][0], selected_for_line[0][3], selected_for_line[0][4])
        result = base * multiplier * (1 + additions)
        line["exact"] = str(result)
        # 일당 작업조의 단위당 품 자릿수는 기존 계산기의 정밀도에 맞춘다.
        if line["places"]:
            from agent.tools.calc.unit_rounding import round_quantity
            line["applied"] = round_quantity(result, line["places"])
        else:
            from agent.tools.calc.daily_crew import _exact_text
            line["applied"] = _exact_text(result)
        line["formula"] += f" × {multiplier} × (1 + {additions})" if multiplier != 1 else f" × (1 + {additions})"
        line["adjustments"] = adjustments
        line["citations"].extend(rule_cite)
    return {"status": "computed", "memos": memos}
