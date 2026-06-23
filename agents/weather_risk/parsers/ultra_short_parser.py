"""T5: UltraSrtNcst(초단기실황) 아이템 파서."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

from weather_risk.parsers.hourly_forecast import (
    HourlyForecast,
    parse_float,
    parse_int,
    parse_precipitation,
)

KST = ZoneInfo("Asia/Seoul")

# T1H → tmp, RN1 → pcp; POP은 UltraSrtNcst에 없음
_KNOWN_CATEGORIES = {"T1H", "PTY", "WSD", "REH", "RN1"}


def parse_ultra_srt_ncst(items: list[dict]) -> list[HourlyForecast]:
    """UltraSrtNcst items → list[HourlyForecast], forecast_at 오름차순."""
    groups: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)

    for item in items:
        date = item.get("baseDate", "")
        time = item.get("baseTime", "")
        category = item.get("category", "")
        value = str(item.get("obsrValue", ""))

        if category not in _KNOWN_CATEGORIES:
            continue

        groups[(date, time)][category] = value

    result: list[HourlyForecast] = []
    for (date, time), cats in sorted(groups.items()):
        forecast_at = datetime.strptime(date + time, "%Y%m%d%H%M").replace(tzinfo=KST)
        result.append(
            HourlyForecast(
                forecast_at=forecast_at,
                pty=cats.get("PTY"),
                tmp=parse_float(cats.get("T1H")),
                wsd=parse_float(cats.get("WSD")),
                reh=parse_int(cats.get("REH")),
                pop=None,  # UltraSrtNcst는 강수확률 미제공
                pcp=parse_precipitation(cats.get("RN1")),
            )
        )

    return result
