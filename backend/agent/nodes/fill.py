"""명세 입력을 규칙으로 읽고 확인할 조건을 한 번에 모은다."""

from __future__ import annotations

import re
import unicodedata
from fractions import Fraction
import json
from pathlib import Path

from backend.agent.rules.specs import load_specs
from backend.agent.state import AgentState
from backend.agent.tools.calc.adjustments import adjustment_questions

_COMMON_INPUTS = Path(__file__).resolve().parents[1] / "rules/cost_statement_inputs.json"


def _common_fields() -> list[dict]:
    return json.loads(_COMMON_INPUTS.read_text(encoding="utf-8"))["fields"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


def _type_mentions(query: str, field: dict) -> list[tuple[int, int, str]]:
    """같은 Type 표현을 중복 세지 않고 원문 위치와 함께 반환한다."""
    found = []
    for value in field["allowed_values"]:
        for spelling in [value, *field.get("synonyms", {}).get(value, [])]:
            needle = _norm(spelling)
            for match in re.finditer(re.escape(needle), query):
                found.append((match.start(), match.end(), value))
    found.sort(key=lambda hit: (hit[0], -(hit[1] - hit[0])))
    distinct = []
    for hit in found:
        if not any(hit[0] < other[1] and other[0] < hit[1] for other in distinct):
            distinct.append(hit)
    return distinct


def _enum_matches(query: str, field: dict) -> set[str]:
    matches = set()
    for value in field["allowed_values"]:
        for spelling in [value, field.get("labels", {}).get(value, ""),
                         *field.get("synonyms", {}).get(value, [])]:
            needle = _norm(spelling)
            if needle and needle in query:
                matches.add(value)
    return matches


def _extract_common_inputs(text: str) -> dict:
    normalized = _norm(text)
    fields = _common_fields()
    values = {}
    for field in fields:
        name = field["name"]
        if name == "project_scale":
            if "이견적만" in normalized or "이번견적만" in normalized:
                values[name] = "이 견적만"
            else:
                scale = re.search(r"([\d,]+(?:\.\d+)?)\s*(억|원)", normalized)
                if scale:
                    amount = Fraction(scale.group(1).replace(",", ""))
                    amount *= 100_000_000 if scale.group(2) == "억" else 1
                    if amount.denominator == 1 and amount > 0:
                        values[name] = str(amount.numerator)
            continue
        matches = []
        for value in field["allowed_values"]:
            for spelling in [value, *field.get("synonyms", {}).get(value, [])]:
                needle = _norm(spelling)
                if needle and needle in normalized:
                    matches.append((len(needle), value))
        if name == "duration":
            if "36개월초과" in normalized or "3년초과" in normalized:
                matches.append((100, "36개월 초과"))
            elif re.search(r"(?:13|1[3-9]|2\d|3[0-6])\s*(?:~|-|에서|부터)\s*36\s*개월|(?:13|1[3-9]|2\d|3[0-6])\s*개월", normalized):
                matches.append((100, "13~36개월"))
            elif re.search(r"(?:7|8|9|10|11|12)\s*(?:~|-|에서|부터)\s*12?\s*개월|(?:7|8|9|10|11|12)\s*개월", normalized):
                matches.append((100, "7~12개월"))
            elif "1개월미만" in normalized or "30일미만" in normalized:
                matches.append((100, "1개월 미만"))
            elif re.search(r"(?:1\s*(?:~|-|에서|부터)\s*6\s*개월|6\s*개월)", normalized):
                matches.append((100, "1~6개월"))
        if matches:
            max_length = max(length for length, _ in matches)
            selected = {value for length, value in matches if length == max_length}
            if len(selected) == 1:
                values[name] = selected.pop()
        else:
            # 공사 종류 낱말(아파트·교량·하천 등)로 대표 종류를 고른다. 서로 다른 종류가 섞이면 고르지 않는다.
            hit = {value for value, words in field.get("keywords", {}).items()
                   if any(_norm(word) in normalized for word in words)}
            if len(hit) == 1:
                values[name] = hit.pop()
    return values


def _type_values(query: str, field: dict) -> set[str]:
    mentions = _type_mentions(query, field)
    if not mentions:
        return set()
    if field["name"] == "site_type":
        return {value for start, _, value in mentions
                if re.search(r"(?:현장조건|현장)", query[max(0, start - 8):start])}
    return {value for start, _, value in mentions
            if not re.search(r"(?:현장조건|현장)", query[max(0, start - 8):start])}


def _format_rational(exact: Fraction) -> str:
    if exact.denominator == 1:
        return str(exact.numerator)
    # 유한소수는 원래 크기를 정확한 십진 문자열로 저장한다.
    denominator = exact.denominator
    while denominator % 2 == 0:
        denominator //= 2
    while denominator % 5 == 0:
        denominator //= 5
    if denominator == 1:
        return _finite_decimal(exact)
    return f"{exact.numerator}/{exact.denominator}"


def _volume(query: str) -> tuple[str | None, str | None]:
    # NFKC는 ㎥를 m3로 바꾼다. 한글 단위는 그대로 유지한다.
    pattern = re.compile(r"(?<![0-9a-z.])(-?\d[\d,]*(?:\.\d+)?(?:/\d+)?)\s*(m3|루베)(?![a-z])", re.I)
    found = []
    for match in pattern.finditer(query):
        try:
            found.append(Fraction(match.group(1).replace(",", "")))
        except (ValueError, ZeroDivisionError):
            return None, "물량 숫자를 해석할 수 없습니다"
    if len(set(found)) > 1:
        return None, "물량이 둘 이상입니다"
    if found:
        if found[0] <= 0:
            return None, "물량은 0보다 커야 합니다"
        return _format_rational(found[0]), None
    wrong_unit = re.search(r"(?<![0-9a-z.])-?\d[\d,]*(?:\.\d+)?\s*(?:m2|m|톤)(?![a-z0-9^])", query, re.I)
    if wrong_unit:
        return None, "물량 단위가 ㎥/m3/루베가 아닙니다"
    without_options = re.sub(
        r"\d+-\d+-\d+|타입\d+|\d+유형|\d+(?:~|-)\d+cm|\d+cm|"
        r"\d+(?:~|-)\d+개월|\d+개월|\d+일|\d[\d,]*(?:\.\d+)?(?:억|원)",
        "", query)
    bare = re.search(r"(?<![0-9a-z.])-?\d[\d,]*(?:\.\d+)?(?![0-9a-z.]|cm|유형)", without_options)
    if bare:
        return None, "물량 단위가 없습니다"
    return None, None


_UNIT_ALIASES = {
    "m3": ("m3", "m^3", "루베", "세제곱미터", "입방미터", "cbm"),
    "m2": ("m2", "m^2", "제곱미터", "평방미터"),
    "ton": ("ton", "톤", "t"),
    "m": ("m", "미터"),
    "km": ("km", "킬로미터"),
    "kg": ("kg", "킬로그램"),
    "개소": ("개소",), "개": ("개",), "본": ("본",), "대": ("대",), "층": ("층",),
}


def _quantity(query: str, unit: str) -> tuple[str | None, str | None]:
    normalized_unit = _norm(unit)
    key = next((name for name, aliases in _UNIT_ALIASES.items()
                if normalized_unit in aliases), None)
    if key is None:
        return None, None
    aliases = sorted(_UNIT_ALIASES[key], key=len, reverse=True)
    pattern = re.compile(r"(?<![0-9a-z.])(-?\d[\d,]*(?:\.\d+)?(?:/\d+)?)"
                         r"(?:" + "|".join(map(re.escape, aliases)) + r")(?![a-z0-9^])", re.I)
    found = []
    for match in pattern.finditer(query):
        try:
            found.append(Fraction(match.group(1).replace(",", "")))
        except (ValueError, ZeroDivisionError):
            return None, "물량 숫자를 해석할 수 없습니다"
    if len(set(found)) > 1:
        return None, "물량이 둘 이상입니다"
    if found:
        if found[0] <= 0:
            return None, "물량은 0보다 커야 합니다"
        return _format_rational(found[0]), None
    return None, None


def _ready_mix_price(query: str) -> tuple[str | None, str | None]:
    if query.strip() in ("모름", "몰라요", "모르겠습니다") or re.search(
            r"(?:레미콘(?:단가|가격)?|m3당|루베당).*모름", query):
        return "모름", None
    pattern = re.compile(
        r"(?:레미콘(?:단가|가격)?(?:m3당|루베당)?|m3당|루베당)"
        r"([\d,]+(?:\.\d+)?)(만원|원)?"
    )
    found = []
    for match in pattern.finditer(query):
        try:
            amount = Fraction(match.group(1).replace(",", ""))
        except (ValueError, ZeroDivisionError):
            return None, "레미콘 단가를 해석할 수 없습니다"
        if match.group(2) == "만원":
            amount *= 10_000
        if amount <= 0:
            return None, "레미콘 단가는 0보다 커야 합니다"
        found.append(amount)
    if len(set(found)) > 1:
        return None, "서로 다른 레미콘 단가가 함께 언급되었습니다"
    if found:
        return _format_rational(found[0]), None
    return None, None


def _finite_decimal(value: Fraction) -> str:
    denominator = value.denominator
    twos = fives = 0
    while denominator % 2 == 0:
        twos += 1
        denominator //= 2
    while denominator % 5 == 0:
        fives += 1
        denominator //= 5
    places = max(twos, fives)
    scaled = value.numerator * (10 ** places // value.denominator)
    digits = str(scaled).zfill(places + 1)
    return digits[:-places] + "." + digits[-places:]


def extract_inputs(query: str, spec: dict) -> tuple[dict, dict]:
    """질문에서 명시된 값만 찾는다. 모호한 입력은 values에 넣지 않는다."""
    normalized = _norm(query)
    values: dict = {}
    ambiguities: dict[str, str] = {}
    quantity_name = spec["quantity_model"]["params"].get("quantity_input")
    for field in spec["inputs"]:
        name = field["name"]
        if field["type"] == "positive_currency":
            value, reason = _ready_mix_price(normalized)
            if value is not None:
                values[name] = value
            elif reason:
                ambiguities[name] = reason
        elif field["type"] == "positive_rational":
            if name == quantity_name and _norm(field.get("unit", "")) not in ("m3", "루베", "세제곱미터"):
                value, reason = _quantity(normalized, field.get("unit", ""))
            else:
                value, reason = _volume(normalized)
            if value is not None:
                values[name] = value
            elif reason:
                ambiguities[name] = reason
        elif field["type"] == "enum":
            if name in ("facility_type", "site_type"):
                matches = _type_values(normalized, field)
            elif name == "reset_status":
                matches = (_enum_matches(normalized, field)
                           if re.search(r"재셋팅|리셋팅|이동", normalized) else set())
            else:
                matches = _enum_matches(normalized, field)
            if name == "pump_size" and re.search(r"(?<!\d)(?:21|28)(?:m|미터)",
                                                  unicodedata.normalize("NFKC", query).casefold()):
                ambiguities[name] = "21m·28m 펌프차는 65~75㎥/hr로 6-1-4의 80㎥/hr 이상 적용범위에 맞지 않습니다"
            if len(matches) > 1:
                ambiguities[name] = "서로 다른 선택지가 함께 언급되었습니다"
            elif matches:
                values[name] = next(iter(matches))
        elif name == "vibrator_used":
            negative = any(term in normalized for term in ("진동기없이", "진동기미사용", "진동기안씀", "진동기안써"))
            positive = any(term in normalized for term in ("진동기사용", "진동기씀"))
            if negative and positive:
                ambiguities[name] = "진동기 사용 여부가 서로 다르게 언급되었습니다"
            elif negative or positive:
                values[name] = positive
    return values, ambiguities


def _hint(query: str, field: dict, tables: dict) -> dict | None:
    table = tables[field["decision_table"]]
    normalized = _norm(query)
    for value, row in table["values"].items():
        criterion = row.get("적용기준", "")
        for part in re.split(r"[,·･，]", criterion):
            word = part.strip().split(" ")[0]
            if word and _norm(word) in normalized:
                return {"value": value, "matched": word}
    return None


def _work_choice(reply: str, candidates: list[dict]) -> dict | None:
    text = _norm(reply)
    exact = [candidate for candidate in candidates if _norm(candidate["section"]) in text]
    if len(exact) == 1:
        return exact[0]
    aliases = {"6-1-1": ("레미콘",), "6-1-2": ("현장비빔",), "6-1-4": ("펌프차",)}
    matches = []
    for candidate in candidates:
        section_no = candidate["section_no"]
        title = candidate["section"]
        words = (section_no, title, *aliases.get(section_no, ()))
        if any(_norm(word) in text for word in words):
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


def _compatible_inputs(inputs: dict, sources: dict, spec: dict) -> tuple[dict, dict]:
    retained = {}
    retained_sources = {}
    for field in spec["inputs"]:
        name = field["name"]
        if name not in inputs or not _valid_for_field(inputs[name], field):
            continue
        retained[name] = inputs[name]
        if name in sources:
            retained_sources[name] = sources[name]
    for field in _common_fields():
        name = field["name"]
        if name in inputs and _valid_for_field(inputs[name], field):
            if name == "work_category" and sources.get(name, "").startswith("기본값"):
                continue
            retained[name] = inputs[name]
            if name in sources:
                retained_sources[name] = sources[name]
    return retained, retained_sources


def _valid_positive_rational(value: object) -> bool:
    try:
        return Fraction(str(value)) > 0
    except (ValueError, ZeroDivisionError):
        return False


def _valid_for_field(value: object, field: dict) -> bool:
    kind = field["type"]
    if kind == "enum":
        return value in field["allowed_values"]
    if kind == "boolean":
        return type(value) is bool
    if kind == "positive_rational":
        return _valid_positive_rational(value)
    if kind == "positive_currency":
        return value == "모름" or _valid_positive_rational(value)
    if kind == "nonnegative_integer":
        return type(value) is int and value >= 0
    if kind == "project_scale":
        if value == "이 견적만":
            return True
        try:
            return Fraction(str(value)) > 0
        except (ValueError, ZeroDivisionError):
            return False
    return False


def _reply_parts(reply: object) -> tuple[dict, str]:
    """재개 값을 (선택 답 dict, 자유 입력 text)로 나눈다."""
    if isinstance(reply, dict):
        if "answers" in reply or "text" in reply:
            return dict(reply.get("answers") or {}), reply.get("text") or ""
        return dict(reply), ""
    return {}, reply or ""


def fill(state: AgentState) -> dict:
    spec_id = state.get("spec_id", "")
    spec = load_specs()[spec_id] if spec_id else None
    previous = state.get("inputs", {})
    inputs = dict(previous)
    sources = dict(state.get("input_sources", {}))
    reply = state.get("reply", "")
    answers, reply_text = _reply_parts(reply)
    field_answers = {name: value for name, value in answers.items() if name != "work"}
    update = {}
    work_error = None
    if (answers or reply_text) and state.get("selection", {}).get("confirmed") is False:
        candidates = state.get("candidates", [])
        if "work" in answers:
            chosen_options = [item for item in candidates
                              if answers["work"] in (item["section"], item["section_no"])]
            chosen = chosen_options[0] if len(chosen_options) == 1 else None
            if chosen is None:
                work_error = "선택한 공종을 후보에서 찾을 수 없습니다"
        else:
            chosen = _work_choice(reply_text, candidates)
        if chosen:
            selection = {**state.get("selection", {}), "decision": "chosen", "confirmed": True,
                         "section_no": chosen["section_no"], "section": chosen["section"]}
            update["selection"] = selection
            available = next((item for item in load_specs().values()
                              if (item["division"], item["section_no"]) ==
                              (chosen.get("division", "공통"), chosen["section_no"])), None)
            if available is None:
                return {**update, "spec_id": "", "inputs": {}, "input_sources": {},
                        "questions": [], "status": "EVIDENCE_ONLY",
                        "reason": f"{chosen['section_no']} 절의 계산 명세가 없습니다"}
            if available["id"] != spec_id:
                inputs, sources = _compatible_inputs(inputs, sources, available)
                # 처음 질문에 적은 조건 중 새 공종에만 있는 값도 다시 읽는다.
                for name, value in extract_inputs(state.get("query", ""), available)[0].items():
                    if name not in inputs:
                        inputs[name], sources[name] = value, "질문"
                spec = available
                update["spec_id"] = available["id"]
    text = reply_text if (answers or reply_text) else state.get("query", "")
    values, ambiguities = extract_inputs(text, spec) if spec else ({}, {})
    common_values = _extract_common_inputs(text)
    origin = "답변" if (answers or reply_text or previous) else "질문"
    inputs.update(values)
    inputs.update(common_values)
    sources.update({name: origin for name in values})
    sources.update({name: origin for name in common_values})
    dict_errors = {}
    if spec:
        for name, value in field_answers.items():
            if re.fullmatch(r"apply_adj_\d+", name):
                if value in ("예", "아니오"):
                    inputs[name] = value
                    sources[name] = "선택"
                else:
                    dict_errors[name] = "예 또는 아니오를 선택해 주세요"
        for field in spec["inputs"]:
            name = field["name"]
            if name not in field_answers:
                continue
            value = field_answers[name]
            if field.get("labels") and value not in field["allowed_values"]:
                label_matches = [raw for raw, label in field["labels"].items() if label == value]
                if len(label_matches) == 1:
                    value = label_matches[0]
            if _valid_for_field(value, field):
                if field["type"] in ("positive_rational", "positive_currency") and value != "모름":
                    inputs[name] = _format_rational(Fraction(str(value).replace(",", "")))
                else:
                    inputs[name] = value
                sources[name] = "선택"
            else:
                dict_errors[name] = "허용값이 아닙니다"
    common_fields = _common_fields()
    for field in common_fields:
        name = field["name"]
        if name not in field_answers:
            continue
        value = field_answers[name]
        if _valid_for_field(value, field):
            inputs[name] = str(value) if field["type"] == "project_scale" and value != "이 견적만" else value
            sources[name] = "선택"
        else:
            dict_errors[name] = "허용값이 아닙니다"
    for field in common_fields:
        if field["name"] not in inputs:
            if field["name"] == "work_category" and spec:
                inputs[field["name"]] = ("주택 외 건축" if spec["division"] in ("건축", "기계설비")
                                          else "기타 토목공사")
                sources[field["name"]] = "기본값(부문)"
            else:
                inputs[field["name"]] = field["default"]
                sources[field["name"]] = "기본값"
    ambiguities = {**ambiguities, **dict_errors}
    questions = []
    work_pending = update.get("selection", state.get("selection", {})).get("confirmed") is False
    if work_pending:
        candidates = state.get("candidates", [])
        work_question = {"name": "work", "ask": "어느 공종으로 계산할까요?",
                          "choices": [item["section"] for item in candidates],
                          "default": candidates[0]["section"] if candidates and
                                     sum(item["section_no"] == candidates[0]["section_no"]
                                         for item in candidates) > 1 else
                                     (candidates[0]["section_no"] if candidates else "")}
        if work_error:
            work_question["reason"] = work_error
        questions.append(work_question)
    # 공종(타설 방식)이 정해지기 전에는 잠정 공종의 조건을 묻지 않는다.
    if spec and not work_pending:
        tables = {table["id"]: table for table in spec["tables"]}
        for field in spec["inputs"]:
            name = field["name"]
            if not field["required"] or (name in inputs and name not in ambiguities):
                continue
            condition = field.get("when")
            if condition and inputs.get(condition["input"]) != condition["equals"]:
                continue
            question = {"name": name, "ask": field["ask"],
                        "choices": field["allowed_values"]}
            if field.get("labels"):
                question["labels"] = field["labels"]
            if "decision_table" in field:
                table = tables[field["decision_table"]]
                question["decision_table"] = table["values"]
                hint = _hint(state.get("query", ""), field, tables)
                if hint:
                    question["hint"] = hint
            if name in ambiguities:
                question["reason"] = ambiguities[name]
            questions.append(question)
        for question in adjustment_questions(spec, inputs):
            if question["name"] in dict_errors:
                question["reason"] = dict_errors[question["name"]]
            questions.append(question)
    for field in common_fields:
        name = field["name"]
        if name in dict_errors:
            questions.append({"name": name, "ask": field["ask"], "choices": field.get("allowed_values"),
                              "reason": dict_errors[name]})
    update.update(inputs=inputs, input_sources=sources, questions=questions)
    if questions:
        update.update(status="MISSING_INFO", reason="견적을 계산하려면 아래 조건을 확인해 주세요.")
    return update
