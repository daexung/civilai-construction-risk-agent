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
