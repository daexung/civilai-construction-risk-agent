"""
BaseTimeResolver — KMA API 발표 기준시각 결정 (T3)

현재 시각 기준으로 조회 가능한 가장 최신 발표 시각(base_date, base_time)을 반환한다.
발표 주기:
  - VilageFcst   : 0200, 0500, 0800, 1100, 1400, 1700, 2000, 2300 (3시간 간격)
  - UltraSrtNcst : 매 정시 (0000~2300, 1시간 간격)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import NamedTuple

from weather_risk.models import ForecastSource, KST, normalize_to_kst

VILAGE_FCST_BASE_HOURS = [2, 5, 8, 11, 14, 17, 20, 23]

DEFAULT_PUBLISH_DELAY_MINUTES = 10
# PROJECT_ASSUMPTION — 실제 KMA 응답 딜레이 미확인.
# T4에서 NO_DATA 빈도 확인 후 조정 필요.

DAYS_BACK_RANGE = range(2)  # [0=오늘, 1=어제]
# publish_delay_minutes < 24h이면 오늘+어제 안에 항상 유효 후보가 존재한다.


class BaseTime(NamedTuple):
    base_date: str  # "YYYYMMDD" — KMA API base_date 파라미터 그대로 사용
    base_time: str  # "HHMM"    — KMA API base_time 파라미터 그대로 사용

    def as_datetime(self) -> datetime:
        """base_date + base_time을 KST datetime으로 복원."""
        return datetime.strptime(
            self.base_date + self.base_time, "%Y%m%d%H%M"
        ).replace(tzinfo=KST)


class BaseTimeResolver:
    """현재 시각 기준 KMA API에서 실제로 조회 가능한 가장 최신 발표 기준시각을 반환한다."""

    def __init__(self, publish_delay_minutes: int = DEFAULT_PUBLISH_DELAY_MINUTES):
        assert publish_delay_minutes < 24 * 60, (
            f"publish_delay_minutes must be < 1440 (24 hours), got {publish_delay_minutes}"
        )
        self._delay = timedelta(minutes=publish_delay_minutes)

    def resolve(self, source: ForecastSource, now: datetime) -> BaseTime:
        """
        now: timezone-aware 필수. naive datetime → ValueError.
        UltraSrtFcst → NotImplementedError (MVP 제외).
        """
        now_kst = normalize_to_kst(now)
        if source == ForecastSource.VILAGE_FCST:
            return self._resolve_vilage_fcst(now_kst)
        if source == ForecastSource.ULTRA_SRT_NCST:
            return self._resolve_ultra_srt_ncst(now_kst)
        raise NotImplementedError(f"{source} is out of MVP scope")

    def _resolve_vilage_fcst(self, now_kst: datetime) -> BaseTime:
        cutoff = now_kst - self._delay
        for days_back in DAYS_BACK_RANGE:
            d = (now_kst - timedelta(days=days_back)).date()
            for h in reversed(VILAGE_FCST_BASE_HOURS):
                candidate = datetime(d.year, d.month, d.day, h, 0, tzinfo=KST)
                if candidate <= cutoff:
                    return BaseTime(d.strftime("%Y%m%d"), f"{h:02d}00")
        raise RuntimeError("No valid VilageFcst base time found")  # unreachable

    def _resolve_ultra_srt_ncst(self, now_kst: datetime) -> BaseTime:
        cutoff = now_kst - self._delay
        for days_back in DAYS_BACK_RANGE:
            d = (now_kst - timedelta(days=days_back)).date()
            for h in range(23, -1, -1):
                candidate = datetime(d.year, d.month, d.day, h, 0, tzinfo=KST)
                if candidate <= cutoff:
                    return BaseTime(d.strftime("%Y%m%d"), f"{h:02d}00")
        raise RuntimeError("No valid UltraSrtNcst base time found")  # unreachable
