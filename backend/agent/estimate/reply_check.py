"""응답 문장의 숫자가 도구 결과의 항목·값·단위와 대응하는지 서버가 직접 검증한다(설계 §7).

facts: 서버가 도구 결과로 만든 [{id, item, value, unit, kind, item_optional?, rounded?}]. value는 정확한 문자열.
  rounded: 서버가 정한 표시용 반올림 결과(작업일수 '2.31'). 정확값 또는 이 값만 허용하고 다른 근삿값은 거부한다.
kind: "per_unit"(1단위당 품·일당 시공량·단가) | "total"(물량·작업일수·원가계산서 금액).
literals: 숫자가 들어 있지만 사실값이 아닌 서버 문자열(공종 '6-1-4', 조건 '32m' 등). 그대로 쓰면 허용한다.
quoted: 근거 설명 턴의 원문 인용. 인용 속 숫자(할증률 등)는 허용한다.
refused: 이번 턴에 서버가 거부한 요청 값('25m' 등). 같은 문장이 '적용하지 않음·유지'로 설명할 때만 허용한다.

LLM에게 대응표를 받지 않는다. 문장 속 숫자마다 아래를 모두 만족하는 사실이 있어야 통과한다.
- 값이 같다(천 단위 쉼표 무시, '9만원'처럼 만·억 단위는 환산한 값이 같을 때만).
- 숫자 바로 뒤가 그 사실의 단위로 시작한다.
- 같은 문장에서 숫자 앞에 가장 가까운 항목명이 그 사실의 항목이다(물량·단가처럼 생략 가능한 항목은 없어도 됨).
- 총액을 '단가·㎥당'으로, 단위당 값을 '총·합계'로 설명하지 않는다.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from backend.agent.tools.calc.format import won
from backend.agent.tools.calc.quantity import decimal_text

# 영문자 바로 뒤 숫자(m3·m2 등 단위 표기의 일부)는 값으로 보지 않는다.
_NUMBER = re.compile(r"(?<![A-Za-z\d.,/])\d[\d,]*(?:\.\d*\(\d+\)|\.\d+)?(?:/\d+)?")
_REPEATING = re.compile(r"(\d+)\.(\d*)\((\d+)\)")
_PER_UNIT = re.compile(r"단가|단위당|\d*\s*(?:m3|m2|개소|개|m|t)\s*당|당\s*(?:금액|비용)")
_TOTAL = re.compile(r"총|합계|전체|모두")
_SCALE = {"만": 10_000, "억": 100_000_000}
_NOT_APPLIED = re.compile(r"지원하지\s*않|지원되지\s*않|없어|없습니다|없는|반영하지\s*(?:않|못)|적용하지\s*(?:않|못)"
                          r"|바꾸지\s*(?:않|못)|변경하지\s*(?:않|못)|유지|불가|안\s*돼|할\s*수\s*없")
_APPLIED_AFTER = re.compile(r"\s*(?:으)?로\s*(?:계산|바꿨|바꾸었|변경|적용|반영|설정|했)")
_SENTENCE = ".!?\n。"
_CLAUSE = _SENTENCE + ",，;·"


def _nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def _value(raw: str) -> Fraction | None:
    repeating = _REPEATING.fullmatch(raw.replace(",", ""))
    if repeating:  # 순환소수 괄호 표기 2.(307692) = 30/13
        whole, fixed, cycle = repeating.groups()
        return (int(whole) + Fraction(int(fixed or 0), 10 ** len(fixed))
                + Fraction(int(cycle), (10 ** len(cycle) - 1) * 10 ** len(fixed)))
    try:
        return Fraction(raw.replace(",", ""))
    except (ValueError, ZeroDivisionError):
        return None


def display(value: str) -> str:
    """사실값의 화면 표기. 기존 규칙: 끝나는 소수는 format.won(천 단위 쉼표), 분수는 quantity.decimal_text
    (끝나는 소수 그대로, 순환소수는 반복 구간 괄호). 반올림하지 않는다."""
    try:
        return won(Decimal(value))
    except (InvalidOperation, ValueError):
        pass
    try:
        exact = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return value
    return decimal_text(exact) if exact > 0 else value


def _nearest_item(before: str, items: list[str]) -> str | None:
    """앞 문장에서 끝 위치가 가장 뒤인 항목명(같으면 긴 것)."""
    best = None
    for item in set(items):
        end = before.rfind(item)
        if end >= 0:
            key = (end + len(item), len(item))
            if best is None or key > best[0]:
                best = (key, item)
    return best[1] if best else None


def _start(body: str, end: int, marks: str) -> int:
    return max(body.rfind(mark, 0, end) for mark in marks) + 1


def _sentence(body: str, start: int, end: int) -> str:
    stop = min([i for i in (body.find(mark, end) for mark in _SENTENCE) if i >= 0], default=len(body))
    return body[_start(body, start, _SENTENCE):stop]


def verify(text: str, facts: list[dict], literals: list[str], quoted: list[str] = (),
           refused: list[str] = ()) -> str | None:
    """문제가 없으면 None, 있으면 거부 이유."""
    if not isinstance(text, str) or not text.strip():
        return "빈 답변"
    body = _nfkc(text)
    items = [_nfkc(fact["item"]) for fact in facts]
    covered = [match.span() for literal in map(_nfkc, literals) if literal and re.search(r"\D", literal)
               for match in re.finditer(re.escape(literal), body)]
    # 거부된 요청 값은 '적용하지 않음'을 말하는 문장에서만, 바로 뒤에 '…로 계산/변경'이 붙지 않을 때만 허용한다.
    covered += [match.span() for value in map(_nfkc, refused) if value and re.search(r"\D", value)
                for match in re.finditer(re.escape(value), body)
                if _NOT_APPLIED.search(_sentence(body, *match.span())) and not _APPLIED_AFTER.match(body[match.end():])]
    allowed = {_value(raw) for quote in quoted for raw in _NUMBER.findall(_nfkc(quote))}
    for match in _NUMBER.finditer(body):
        if any(start <= match.start() and match.end() <= end for start, end in covered):
            continue
        value, after = _value(match.group()), body[match.end():].lstrip()
        nearest = _nearest_item(body[_start(body, match.start(), _SENTENCE):match.start()], items)
        clause = body[_start(body, match.start(), _CLAUSE):match.start()]
        if any(_matches(fact, value, after, nearest, clause) for fact in facts):
            continue
        if value in allowed:
            continue
        if nearest:
            return f"값 불일치: {nearest} {match.group()}{after[:4]}"
        return f"근거 없는 숫자: {match.group()}"
    return None


def _matches(fact: dict, value: Fraction | None, after: str, nearest: str | None, clause: str) -> bool:
    if value is None:
        return False
    if fact["unit"] == "원" and after[:1] in _SCALE:
        value, after = value * _SCALE[after[0]], after[1:].lstrip()
    if value not in (_value(fact["value"]), _value(fact.get("rounded") or ""))             or (fact["unit"] and not after.startswith(_nfkc(fact["unit"]))):
        return False
    if nearest != _nfkc(fact["item"]) and not (fact.get("item_optional") and nearest is None):
        return False
    if fact.get("kind") == "total" and _PER_UNIT.search(clause):
        return False
    return not (fact.get("kind") == "per_unit" and _TOTAL.search(clause))
