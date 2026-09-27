"""명세 입력을 규칙으로 읽고 확인할 조건을 한 번에 모은다."""

from __future__ import annotations

import re
import unicodedata
from fractions import Fraction

from agent.rules.specs import load_specs
from agent.state import AgentState


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
        for spelling in [value, *field.get("synonyms", {}).get(value, [])]:
            needle = _norm(spelling)
            if needle in query:
                matches.add(value)
    return matches


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
    wrong_unit = re.search(r"(?<![0-9a-z.])-?\d[\d,]*(?:\.\d+)?\s*(?:m2|m|톤)(?![a-z0-9])", query, re.I)
    if wrong_unit:
        return None, "물량 단위가 ㎥/m3/루베가 아닙니다"
    without_options = re.sub(r"\d+-\d+-\d+|타입\d+|\d+유형|\d+(?:~|-)\d+cm|\d+cm", "", query)
    bare = re.search(r"(?<![0-9a-z.])-?\d[\d,]*(?:\.\d+)?(?![0-9a-z.]|cm|유형)", without_options)
    if bare:
        return None, "물량 단위가 없습니다"
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
    for field in spec["inputs"]:
        name = field["name"]
        if field["type"] == "positive_rational":
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
            negative = any(term in normalized for term in ("진동기없이", "진동기미사용", "진동기안씀"))
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
    if kind == "nonnegative_integer":
        return type(value) is int and value >= 0
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
            chosen = next((item for item in candidates if item["section_no"] == answers["work"]), None)
            if chosen is None:
                work_error = "선택한 공종을 후보에서 찾을 수 없습니다"
        else:
            chosen = _work_choice(reply_text, candidates)
        if chosen:
            selection = {**state.get("selection", {}), "decision": "chosen", "confirmed": True,
                         "section_no": chosen["section_no"], "section": chosen["section"]}
            update["selection"] = selection
            available = next((item for item in load_specs().values()
                              if item["section_no"] == chosen["section_no"]), None)
            if available is None:
                return {**update, "spec_id": "", "inputs": {}, "input_sources": {},
                        "questions": [], "status": "EVIDENCE_ONLY",
                        "reason": f"{chosen['section_no']} 절의 계산 명세가 없습니다"}
            if available["id"] != spec_id:
                inputs, sources = _compatible_inputs(inputs, sources, available)
                spec = available
                update["spec_id"] = available["id"]
    text = reply_text if (answers or reply_text) else state.get("query", "")
    values, ambiguities = extract_inputs(text, spec) if spec else ({}, {})
    origin = "답변" if (answers or reply_text or previous) else "질문"
    inputs.update(values)
    sources.update({name: origin for name in values})
    dict_errors = {}
    if spec:
        for field in spec["inputs"]:
            name = field["name"]
            if name not in field_answers:
                continue
            value = field_answers[name]
            if _valid_for_field(value, field):
                inputs[name] = value if field["type"] != "positive_rational" else _format_rational(Fraction(str(value)))
                sources[name] = "선택"
            else:
                dict_errors[name] = "허용값이 아닙니다"
    ambiguities = {**ambiguities, **dict_errors}
    questions = []
    if update.get("selection", state.get("selection", {})).get("confirmed") is False:
        candidates = state.get("candidates", [])
        work_question = {"name": "work", "ask": "어느 공종으로 계산할까요?",
                          "choices": [item["section"] for item in candidates],
                          "default": candidates[0]["section_no"] if candidates else ""}
        if work_error:
            work_question["reason"] = work_error
        questions.append(work_question)
    if spec:
        tables = {table["id"]: table for table in spec["tables"]}
        for field in spec["inputs"]:
            name = field["name"]
            if not field["required"] or (name in inputs and name not in ambiguities):
                continue
            question = {"name": name, "ask": field["ask"],
                        "choices": field["allowed_values"]}
            if "decision_table" in field:
                table = tables[field["decision_table"]]
                question["decision_table"] = table["values"]
                hint = _hint(state.get("query", ""), field, tables)
                if hint:
                    question["hint"] = hint
            if name in ambiguities:
                question["reason"] = ambiguities[name]
            questions.append(question)
    update.update(inputs=inputs, input_sources=sources, questions=questions)
    if questions:
        update.update(status="MISSING_INFO", reason="계산에 필요한 조건을 확인해 주세요")
    return update
