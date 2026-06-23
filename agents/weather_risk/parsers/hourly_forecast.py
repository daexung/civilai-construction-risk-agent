"""T5: HourlyForecast 타입 및 공용 파싱 헬퍼.

short_term_parser.py / ultra_short_parser.py 양쪽이 여기서 import한다.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


class HourlyForecast(NamedTuple):
    forecast_at: datetime   # KST, timezone-aware
    pty: str | None         # 강수형태 코드 (string 그대로, 리매핑 없음)
    tmp: float | None       # 기온 ℃
    wsd: float | None       # 풍속 m/s
    reh: int | None         # 습도 %
    pop: int | None         # 강수확률 % (VilageFcst only; UltraSrtNcst는 None)
    pcp: float | None       # 강수량 mm


def parse_float(value: str | None) -> float | None:
    """문자열 → float. |value| >= 900 이면 KMA 결측치로 간주해 None 반환."""
    if not value or value == "-":
        return None
    try:
        f = float(value)
        return None if abs(f) >= 900 else f
    except ValueError:
        return None


def parse_int(raw: str | None) -> int | None:
    """parse_float 후 int 변환. 결측치(-999 등)는 None."""
    f = parse_float(raw)
    return None if f is None else int(f)


def parse_precipitation(value: str | None) -> float | None:
    """강수량 문자열 → mm (float).

    # PROJECT_ASSUMPTION: 범위 강수량은 하한값을 사용. 평균/상한이 더 적절하다고
    # 판단되면 T7 리스크 룰 검토 시 재논의.
    """
    if not value or value == "강수없음":
        return 0.0
    if "미만" in value:
        return 0.0
    # "X~Ymm" 범위 → 하한값
    range_match = re.match(r"^([0-9.]+)~[0-9.]+mm$", value)
    if range_match:
        return float(range_match.group(1))
    # "X.Xmm"
    simple_match = re.match(r"^([0-9.]+)mm$", value)
    if simple_match:
        return float(simple_match.group(1))
    return None
