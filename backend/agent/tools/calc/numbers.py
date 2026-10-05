"""품셈 표와 숫자 조건의 값을 정확한 분수로 읽는다."""

from __future__ import annotations

import re
import math
import unicodedata
from fractions import Fraction


def parse_fraction(value: str | int | float | Fraction) -> Fraction:
    if isinstance(value, Fraction):
        return value
    if type(value) is int:
        return Fraction(value)
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"숫자 형식 아님: {value!r}")
        value = str(value)
    if not isinstance(value, str):
        raise ValueError(f"숫자 형식 아님: {value!r}")
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", "", normalized).replace(",", "")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:/\d+)?", normalized):
        raise ValueError(f"숫자 형식 아님: {value!r}")
    return Fraction(normalized)


def parse_table_number(value: str | int | float | Fraction) -> Fraction:
    """표의 퍼센트와 `1대(규격)` 수량을 읽되 다른 문장은 숫자로 오인하지 않는다."""
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFKC", value).strip()
        percent = re.fullmatch(r"([+-]?)\s*(\d+(?:\.\d+)?)\s*%", normalized)
        if percent:
            sign = -1 if percent.group(1) == "-" else 1
            return sign * Fraction(percent.group(2)) / 100
        machine = re.fullmatch(r"(\d+)\s*대\s*\([^)]*\)", normalized)
        if machine:
            return Fraction(int(machine.group(1)))
    return parse_fraction(value)
