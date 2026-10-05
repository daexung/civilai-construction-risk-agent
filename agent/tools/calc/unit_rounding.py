"""표준품셈 1-2-8 시공단위 품의 기본 자릿수와 1-2-1 반올림."""

from __future__ import annotations

from fractions import Fraction


def unit_places(daily_output: Fraction) -> int:
    """일당시공량 정수부 자릿수로 기본 자릿수를 고른다 (PDF 74~75쪽).

    원문 표의 '1단위이하' 열에는 3단위 예시도 있으므로 10 미만을 2자리로
    해석한다. 10, 100, ... 경계에서는 각각 3, 4, ... 자리다.
    """
    if daily_output <= 0:
        raise ValueError("daily_output must be positive")
    return max(2, len(str(daily_output.numerator // daily_output.denominator)) + 1)


def round_quantity(value: Fraction, places: int) -> str:
    """정확한 분수에서 지정 자리 아래 1자리를 산출해 사사오입한다."""
    if places < 0:
        raise ValueError("places must be nonnegative")
    scale = 10**places
    magnitude = abs(value) * scale
    quotient, remainder = divmod(magnitude.numerator, magnitude.denominator)
    # 다음 한 자리가 5 이상이면 올린다. 모든 연산은 정수/분수로 수행한다.
    rounded = quotient + (2 * remainder >= magnitude.denominator)
    sign = "-" if value < 0 and rounded else ""
    if places == 0:
        return f"{sign}{rounded}"
    return f"{sign}{rounded // scale}.{rounded % scale:0{places}d}"
