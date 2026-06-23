"""T9: WeatherRiskService — 기상 리스크 분석 통합 파이프라인 (T2→T5→T6→T7→T8)."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from weather_risk.calculators.delay_calculator import calculate_delay
from weather_risk.clients.exceptions import KmaApiError
from weather_risk.clients.kma_client import KmaClient, KmaFetchResult
from weather_risk.converters.grid_converter import latlon_to_grid
from weather_risk.filters.workhour_filter import filter_work_hours
from weather_risk.models import (
    KST,
    DelayPolicy,
    ForecastMeta,
    ForecastSource,
    RiskLevel,
    RiskResult,
    ServiceStatus,
    Site,
    WeatherRiskRequest,
    WeatherRiskResponse,
    WeatherSummary,
    Work,
)
from weather_risk.parsers.hourly_forecast import HourlyForecast
from weather_risk.parsers.short_term_parser import parse_vilage_fcst
from weather_risk.parsers.ultra_short_parser import parse_ultra_srt_ncst
from weather_risk.rules.engine import evaluate_risk


class KmaClientProtocol(Protocol):
    def fetch_vilage_fcst(
        self, nx: int, ny: int, now: datetime, max_no_data_fallbacks: int = 3
    ) -> KmaFetchResult: ...

    def fetch_ultra_srt_ncst(
        self, nx: int, ny: int, now: datetime, max_no_data_fallbacks: int = 3
    ) -> KmaFetchResult: ...


def analyze_weather_risk(
    request: WeatherRiskRequest,
    now: datetime | None = None,
    kma_client: KmaClientProtocol | None = None,
) -> WeatherRiskResponse:
    """기상 리스크 분석 전체 파이프라인.

    Args:
        request: WeatherRiskRequest (tz-aware 검증 완료된 상태)
        now: 현재시각 (None이면 datetime.now(KST)). 테스트 주입용.
        kma_client: KMA API 클라이언트 (None이면 KmaClient()). 테스트 주입용.
    """
    if now is None:
        now = datetime.now(KST)
    if kma_client is None:
        kma_client = KmaClient()

    warnings: list[str] = []

    # 1. 격자 변환
    grid = latlon_to_grid(request.latitude, request.longitude)
    print(
        f'[기상 서비스] lat={request.latitude}  lon={request.longitude}'
        f' → nx={grid.nx}  ny={grid.ny}  in_bounds={grid.in_bounds}'
    )
    if not grid.in_bounds:
        warnings.append(
            f"Location ({request.latitude},{request.longitude}) is outside Korea's "
            f"forecast grid (nx={grid.nx}, ny={grid.ny})"
        )

    # 2. 예보 소스 결정
    source = (
        ForecastSource.VILAGE_FCST
        if request.query_type == "SHORT_TERM"
        else ForecastSource.ULTRA_SRT_NCST
    )

    site = Site(
        site_name=request.site_name,
        latitude=request.latitude,
        longitude=request.longitude,
        grid_x=grid.nx,
        grid_y=grid.ny,
    )
    work = Work(
        work_type=request.work_type,
        scheduled_start=request.scheduled_start,
        scheduled_end=request.scheduled_end,
    )

    # 3. KMA API 호출
    try:
        if source == ForecastSource.VILAGE_FCST:
            kma_result = kma_client.fetch_vilage_fcst(grid.nx, grid.ny, now)
        else:
            kma_result = kma_client.fetch_ultra_srt_ncst(grid.nx, grid.ny, now)
    except KmaApiError as exc:
        warnings.append(f"KMA API error: {exc}")
        # fetched_at == base_datetime 로 ForecastMeta validator(fetched_at >= base_datetime) 충족
        return WeatherRiskResponse(
            project_id=request.project_id,
            site=site,
            work=work,
            query_type=request.query_type,
            forecast=ForecastMeta(source=source, base_datetime=now, fetched_at=now),
            summary=WeatherSummary(),
            risk_periods=[],
            risk_result=RiskResult(
                risk_level=RiskLevel.LOW,
                work_stoppage_required=False,
                affected_hours=0,
                recommended_delay_hours=0,
                delay_day_equivalent=0,
                delay_policy=DelayPolicy(),
            ),
            status=ServiceStatus.FAILED,
            warnings=warnings,
        )

    # 4. 파싱 → 필터 → 룰 평가 → 지연 계산
    raw_forecasts = (
        parse_vilage_fcst(kma_result.items)
        if source == ForecastSource.VILAGE_FCST
        else parse_ultra_srt_ncst(kma_result.items)
    )
    filtered = filter_work_hours(raw_forecasts, request.scheduled_start, request.scheduled_end)
    evaluation = evaluate_risk(filtered, request.work_type)
    warnings.extend(evaluation.warnings)

    return WeatherRiskResponse(
        project_id=request.project_id,
        site=site,
        work=work,
        query_type=request.query_type,
        forecast=ForecastMeta(
            source=kma_result.source,
            base_datetime=kma_result.base_time.as_datetime(),
            fetched_at=kma_result.fetched_at,
        ),
        summary=_build_summary(filtered),
        risk_periods=evaluation.risk_periods,
        risk_result=calculate_delay(evaluation, request.work_type),
        status=ServiceStatus.SUCCESS,
        warnings=warnings,
    )


def _build_summary(filtered: list[HourlyForecast]) -> WeatherSummary:
    """작업시간 내 HourlyForecast 목록 → WeatherSummary 집계."""
    if not filtered:
        return WeatherSummary()

    pops = [f.pop for f in filtered if f.pop is not None]
    pcps = [f.pcp for f in filtered if f.pcp is not None]
    wsds = [f.wsd for f in filtered if f.wsd is not None]
    tmps = [f.tmp for f in filtered if f.tmp is not None]

    return WeatherSummary(
        max_pop_pct=int(round(max(pops))) if pops else None,
        total_pcp_mm=sum(pcps) if pcps else None,
        max_wsd_mps=max(wsds) if wsds else None,
        min_tmp_c=min(tmps) if tmps else None,
        has_precipitation=any(f.pty not in (None, "0") for f in filtered),
    )
