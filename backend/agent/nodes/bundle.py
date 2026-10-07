"""여러 공종이 담긴 질문을 항목별로 나눠 기존 단일 공종 계산을 반복하고, 원가계산서는 한 번만 만든다.

공종별 직접비(재료비·노무비·경비)만 더하고 간접비·일반관리비·이윤·부가세는 합친 직접비로
calculate_cost_statement를 한 번 호출해 중복 합산을 막는다.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date
from functools import cache

from backend.agent.nodes.fill import _common_fields, _extract_common_inputs, _norm, _reply_parts
from backend.agent.rules.specs import load_specs
from backend.agent.state import AgentState
from backend.agent.tools.calc.cost_statement import calculate_cost_statement
from backend.paths import ROOT

MAX_ITEMS = 3
SEPARATE = "별도 공종"
CONDITION = "앞 공종의 조건"
ALL_ITEMS = "모든 공종"
EACH = "각각 따로 견적"
ONE = "하나의 공종으로"
# NFKC 이후 단위(㎥→m3, ㎡→m2). '6개월'은 물량이 아니다.
_UNIT = r"(?:m3|m2|km|kg|ton|톤|루베|개소|본|ea|m|t|개(?!월))"
_QUANTITY = re.compile(r"(?<![0-9a-z.])\d[\d,]*(?:\.\d+)?\s*(" + _UNIT + r")(?![a-z0-9])", re.I)
# 치수(높이 3m 등)는 공종 물량이 아니다.
_DIMENSION = re.compile(r"(?:높이|폭|두께|깊이|지름|직경|간격|규격)(?:은|는|이|가|을|를)?\s*$|[=~]\s*$")
# 장비 규격(펌프차 32m, 크레인 50톤)은 길이·무게 단위라도 물량이 아니다.
_EQUIPMENT = ("펌프차", "펌프카", "붐", "크레인", "덤프", "굴착기", "백호", "지게차", "롤러", "브레이커", "장비")
_SPEC_UNITS = {"m", "t", "ton", "톤"}
# "도장도 같이 해줘"처럼 물량 없이 공종을 더하는 말.
_ADDITION = re.compile(r"(?:도|까지)\s*(?:같이|함께|추가|포함|해|할|견적)|추가로|별도로")
# 공종 정보가 없는 요청 문구.
_FILLER = re.compile(r"견적|얼마|비용|공사비|금액|부탁|뽑아|알려|계산|궁금|문의|주세요|드려요|입니다"
                     r"|\?|어떻게|되나요|하나요|있나요|습니까|나요|까요|가요")
# 기준값(25m일 때, 0.5ton 미만인지)은 물량이 아니다.
_THRESHOLD = re.compile(r"\s*(?:[~/]|당|에서)|\s*(?:일|이)?\s*(?:때|경우|인지|미만|초과|이상|이하|이내|마다|내외|중\s)")
# '및'·'또'는 "뒤채움 및 다짐"처럼 한 공종 안의 낱말도 잇기 때문에 나누지 않는다.
_SEPARATOR = re.compile(r",(?!\d{3}(?!\d))|;|\n|[.!?](?:\s+|$)|\s그리고\s")
_CONJUNCTION = re.compile(r"(\d\s*" + _UNIT + r")(?:와|과|하고|이랑|랑)\s", re.I)
# 물량 없는 "도장과 자동문 설치"처럼 공종 이름을 잇는 말.
_WORK_JOIN = re.compile(r"(?<=[가-힣A-Za-z])(?:이랑|하고|와|과|랑)\s+|\s+및\s+|\s*,\s*")
_PARTICLE = re.compile(r"(?:은|는|이|가|을|를|도|로|으로|의|에)$")
# 절 제목이지만 공종 이름으로 보기 어려운 일반 낱말.
_GENERIC_TITLES = {"운반", "인력", "목적", "위험", "사용료", "재료비", "소규모", "일반사항", "적용범위", "적용기준"}
# "~어떻게 하나요?" 같은 품셈 규칙 질문은 견적 요청 낱말이 없으면 나누지 않는다(기존 단일 흐름).
_QUESTION = re.compile(r"\?|나요|까요|습니까|인가요|는지|어떻게")
_COST_REQUEST = re.compile(r"견적|비용|얼마|공사비|금액|뽑아|산출해|계산해\s*(?:줘|주세요|주실)")

# 다음 항목으로 넘어갈 때 비우는 항목별 상태.
_ITEM_RESET = {"spec_id": "", "selection": {}, "candidates": [], "hits": [], "inputs": {},
               "input_sources": {}, "questions": [], "reply": "", "result": {}, "priced": None,
               "statement": None, "review_status": "", "search_query": "", "status": "RUNNING",
               "reason": ""}
_SNAPSHOT = ("query", "status", "reason", "spec_id", "selection", "inputs", "input_sources",
             "result", "priced", "review_status")


@cache
def _condition_words() -> frozenset[str]:
    """명세·공통 조건의 선택지와 동의어. 이 낱말이 있으면 공종이 아니라 조건으로 본다."""
    fields = [field for spec in load_specs().values() for field in spec["inputs"]] + _common_fields()
    words = set(_EQUIPMENT)
    for field in fields:
        words.update(value for value in field.get("allowed_values") or [] if isinstance(value, str))
        words.update((field.get("labels") or {}).values())
        for group in ("synonyms", "keywords"):
            for values in (field.get(group) or {}).values():
                words.update(values)
    return frozenset(word for word in map(_norm, words) if len(word) >= 2)


def _equipment_spec(text: str, match: re.Match) -> bool:
    """장비 이름 바로 앞뒤(6자 안)의 길이·무게, 바로 뒤의 용량(굴착기 0.6㎥)은 장비 규격이다."""
    unit = match.group(1).casefold()
    before = text[max(0, match.start() - 6):match.start()]
    near = before + text[match.end():match.end() + 6] if unit in _SPEC_UNITS else before if unit == "m3" else ""
    return any(word in near for word in _EQUIPMENT)


def _work_quantity(text: str) -> bool:
    return any(not _DIMENSION.search(text[:match.start()]) and not _equipment_spec(text, match)
               and not _THRESHOLD.match(text, match.end())
               for match in _QUANTITY.finditer(text))


@cache
def _work_names() -> frozenset[str]:
    """품셈 절 제목에서 번호·괄호를 뺀 공종 이름. 원문 검색 파일이 없으면 빈 집합."""
    names = set()
    try:
        with (ROOT / "data/processed/chunks.all.jsonl").open(encoding="utf-8") as lines:
            for line in lines:
                section = json.loads(line).get("section", "")
                names.add(_norm(re.sub(r"^\d+(?:-\d+)*\s*|\(.*?\)", "", section)))
    except OSError:
        return frozenset()
    return frozenset(name for name in names if len(name) >= 2 and name not in _GENERIC_TITLES
                     and name not in _condition_words())


def _named_works(query: str) -> list[str]:
    """물량 없이 공종 이름만 이어 쓴 경우 그 이름들. 모든 조각이 공종 이름일 때만 돌려준다."""
    phrases = [part.strip() for part in _WORK_JOIN.split(unicodedata.normalize("NFKC", query)) if part.strip()]
    names = _work_names()

    def named(phrase: str) -> bool:
        core = _norm(phrase)
        if any(word in core for word in _EQUIPMENT):  # "브레이커와 굴착기 조합"은 장비 조합이지 공종이 아니다
            return False
        return any(core.startswith(name) or (len(core) >= 2 and name.startswith(core)) for name in names)
    if len(phrases) < 2 or not all(map(named, phrases)):
        return []
    # "자동문 설치 견적 부탁해" → "자동문 설치"
    return [re.sub(r"\s*(?:견적|비용|공사비|금액|얼마|부탁).*$", "", phrase) or phrase for phrase in phrases]


def _kind(part: str) -> str:
    """work(물량 있는 공종) / added(물량 없이 더한 공종) / common(공통 공사 조건) /
    condition(특정 공종의 장비·시공 조건) / filler / unclear."""
    if _work_quantity(part):
        return "work"
    if _ADDITION.search(part):
        return "added"
    if _extract_common_inputs(part):
        return "common"
    normalized = _norm(part)
    # 숫자가 있는 조각(3시간 차단, 슬럼프 15cm)은 물량이 아니라 조건 값이다.
    if re.search(r"\d|(?:경우|때|는데|면)$", part) or any(word in normalized for word in _condition_words()):
        return "condition"
    return "filler" if _FILLER.search(part) else "unclear"


def _segments(query: str) -> list[str]:
    text = _CONJUNCTION.sub(r"\1\n", unicodedata.normalize("NFKC", query))
    return [part.strip() for part in _SEPARATOR.split(text) if part and part.strip()]


def _mentioned(condition: str, works: list[str]) -> list[int]:
    """조건에 나온 낱말(레미콘은 → 레미콘)이 들어 있는 공종 순번."""
    words = {_norm(_PARTICLE.sub("", word)) for word in re.findall(r"[가-힣A-Za-z]{2,}", condition)}
    words = {word for word in words if len(word) >= 2}
    return [index for index, text in enumerate(works) if any(word in _norm(text) for word in words)]


def plan_items(query: str, decisions: dict[str, str] | None = None) -> tuple[list[str], list[dict]]:
    """조각을 공종 항목으로 묶는다. 판단이 어려우면 (빈 목록, 확인 질문)을 돌려준다.

    공통 공사 조건(공사 종류·기간·업종·규모)과 요청 문구는 모든 공종에 붙인다.
    특정 공종 조건은 공종 사이에 있으면 앞 공종에, 맨 앞·뒤에 있으면 조건에 나온 낱말이 들어 있는
    공종에 붙이고, 그런 공종이 없으면 어느 공종의 조건인지 묻는다.
    """
    if _QUESTION.search(query) and not _COST_REQUEST.search(query):
        return [], []
    decisions = decisions or {}
    parts = _segments(query)
    kinds = [_kind(part) for part in parts]
    for name, value in decisions.items():
        if name.startswith("split_") and value in (SEPARATE, CONDITION):
            kinds[int(name[6:])] = "added" if value == SEPARATE else "previous"
    if "work" not in kinds:  # 물량 있는 공종이 없을 때
        named = _named_works(query)
        if not named:
            return [], []  # 기존 단일 흐름
        if decisions.get("named") not in (EACH, ONE):
            listed = ", ".join(f"‘{phrase}’" for phrase in named)
            return [], [{"name": "named", "choices": [EACH, ONE], "ask": f"{listed}을(를) 각각 따로 견적할까요?"}]
        return (named if decisions["named"] == EACH else []), []
    unclear = [index for index, kind in enumerate(kinds) if kind == "unclear"]
    if unclear:
        return [], [{"name": f"split_{index}", "choices": [SEPARATE, CONDITION],
                     "ask": f"‘{parts[index]}’은(는) 따로 견적할 공종인가요, 앞 공종의 조건인가요?"}
                    for index in unclear]
    works = [index for index, kind in enumerate(kinds) if kind in ("work", "added")]
    if len(works) < 2:
        return [" ".join(parts)], []
    labels = [f"{number}번({parts[work]})" for number, work in enumerate(works, 1)]
    groups = {work: [work] for work in works}
    questions = []
    for index, kind in enumerate(kinds):
        if index in groups:
            continue
        if kind in ("common", "filler"):
            targets = works
        elif kind == "previous" or works[0] < index < works[-1]:
            targets = [max((work for work in works if work < index), default=works[0])]
        elif decisions.get(f"attach_{index}") in (*labels, ALL_ITEMS):
            chosen = decisions[f"attach_{index}"]
            targets = works if chosen == ALL_ITEMS else [works[labels.index(chosen)]]
        else:
            targets = [works[hit] for hit in _mentioned(parts[index], [parts[work] for work in works])]
            if not targets:
                questions.append({"name": f"attach_{index}", "choices": [*labels, ALL_ITEMS],
                                  "ask": f"‘{parts[index]}’은(는) 어느 공종의 조건인가요?"})
        for target in targets:
            groups[target].append(index)
    if questions:
        return [], questions
    return [" ".join(parts[index] for index in sorted(groups[work])) for work in works], []


def split_items(query: str) -> list[str]:
    return plan_items(query)[0]


def split(state: AgentState) -> dict:
    if state.get("route") != "estimate":
        return {}
    pending = state.get("split_pending") or []
    decisions = dict(state.get("split_decisions") or {})
    retry: dict[str, str] = {}
    if pending:  # 확인 질문에 답한 뒤 다시 들어온다. 선택지에서 고른 답만 저장한다.
        answers, text = _reply_parts(state.get("reply"))
        for question in plan_items(state["query"], decisions)[1]:
            value = answers.get(question["name"])
            if value in question["choices"]:
                decisions[question["name"]] = value
            elif value is not None:
                retry[question["name"]] = "선택지에 없는 값이에요. 아래에서 골라 주세요."
            elif text.strip():
                retry[question["name"]] = "입력한 내용으로는 판단하지 못했어요. 아래에서 골라 주세요."
            else:
                retry[question["name"]] = "아직 답하지 않은 질문이에요."
    items, questions = plan_items(state["query"], decisions)
    for question in questions:
        if question["name"] in retry:
            question["reason"] = retry[question["name"]]
    if questions:
        return {"status": "MISSING_INFO", "split_pending": [question["name"] for question in questions],
                "split_decisions": decisions, "reply": "",
                "reason": "여러 공종으로 나눌지 확인이 필요해요.", "questions": questions}
    resumed = {"split_pending": [], "reply": "", "questions": [], "status": "RUNNING", "reason": ""} if pending else {}
    if len(items) < 2:
        return resumed
    if len(items) > MAX_ITEMS:
        return {**resumed, "status": "BLOCKED",
                "reason": f"한 번에 {MAX_ITEMS}개 공종까지 묶어 계산할 수 있어요. 공종을 나눠서 질문해 주세요."}
    return {**resumed, "bundle_query": state["query"], "items": [{"query": item} for item in items],
            "item_index": 0, "query": items[0], "search_query": ""}


def item_label(state: AgentState) -> str:
    index = state.get("item_index", 0)
    return f"{index + 1}번 항목({state['items'][index]['query']})"


def collect(state: AgentState) -> dict:
    """현재 항목 결과를 저장하고 다음 항목을 준비한다. 마지막이면 공통 조건을 합친다."""
    index = state.get("item_index", 0)
    items = list(state["items"])
    # fill 전에 끝난 항목(명세 없음 등)도 빈 값으로 남겨 응답·설명이 깨지지 않게 한다.
    items[index] = {key: state.get(key) if state.get(key) is not None else _ITEM_RESET.get(key)
                    for key in _SNAPSHOT}
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
    direct_total = 0  # 단일 공종처럼 항목별 물량 기준 합계(버림 후)를 더한다
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
        direct_total += int(reference["total"])
        priced = item["priced"]
        rate_version = rate_version or priced.get("rate_version") or {}
        for target, source in ((unpriced, priced.get("unpriced", [])), (excluded, priced.get("excluded", []))):
            target.extend(entry for entry in source
                          if not any(seen["name"] == entry["name"] for seen in target))
    if rate_version is None:  # 금액을 낸 항목이 하나도 없다
        return {"status": "BLOCKED", "statement": None,
                "reason": "묶을 수 있는 공종 계산 결과가 없어요. " +
                          "; ".join(f"{entry['name']}: {entry['reason']}" for entry in unpriced)}
    combined = {"reference_amounts": {"subtotals": subtotals, "total": direct_total, "volume": None},
                "rate_version": rate_version, "unpriced": unpriced, "excluded": excluded}
    result = calculate_cost_statement(combined, state.get("inputs", {}),
                                      state.get("basis_date") or date.today().isoformat())
    status = "PARTIAL" if result["status"] in ("PARTIAL", "UNCALCULATED") else "OK"
    return {"statement": result, "status": status, "reason": result.get("reason", "")}
