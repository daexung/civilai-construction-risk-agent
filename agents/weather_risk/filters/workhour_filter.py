"""T6: 작업시간 필터 — 08:00 이상 16:00 미만, 예정 구간 내 HourlyForecast만 반환."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from weather_risk.models import normalize_to_kst
from weather_risk.parsers.hourly_forecast import HourlyForecast

WORK_HOUR_START = 8   # inclusive (08:00 <= hour)
WORK_HOUR_END = 16    # exclusive (hour < 16:00)


def filter_work_hours(
    forecasts: list[HourlyForecast],
    scheduled_start: datetime,
    scheduled_end: datetime,
) -> list[HourlyForecast]:
    """work hour(08~15시) AND 예정 구간 [scheduled_start, scheduled_end)에 속하는 슬롯만 반환.

    Args:
        forecasts: HourlyForecast 목록 (정렬 불필요, 순서 유지)
        scheduled_start: 작업 시작 (tz-aware, naive → ValueError)
        scheduled_end: 작업 종료 (tz-aware, naive → ValueError)
    """
    start_kst = normalize_to_kst(scheduled_start)
    end_kst = normalize_to_kst(scheduled_end)

    return [
        f for f in forecasts
        if (
            start_kst <= f.forecast_at < end_kst
            and WORK_HOUR_START <= f.forecast_at.hour < WORK_HOUR_END
        )
    ]


def group_by_date(
    forecasts: list[HourlyForecast],
) -> dict[date, list[HourlyForecast]]:
    """forecast_at의 KST date를 키로 그룹화.

    반환 dict는 날짜 오름차순으로 정렬됨.
    T8 DelayCalculator가 날짜별 affected_hours를 집계할 때 사용.
    """
    groups: dict[date, list[HourlyForecast]] = defaultdict(list)
    for f in forecasts:
        groups[f.forecast_at.date()].append(f)
    return dict(sorted(groups.items()))
