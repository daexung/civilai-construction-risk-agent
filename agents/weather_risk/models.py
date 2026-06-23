"""
Weather Risk Service - Request/Response Schemas (T0)

이 파일이 팀 통합의 "계약(contract)"이다.
필드명을 바꾸려면 schema test 갱신 + 팀에 공유 필수.

Timezone policy:
- 입력은 timezone-aware이면 어떤 offset이든 허용한다.
- 내부적으로는 모두 Asia/Seoul(KST)로 정규화한다.
- naive datetime은 거부한다.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator, field_validator

KST = ZoneInfo("Asia/Seoul")


def normalize_to_kst(value: datetime) -> datetime:
    """timezone-aware datetime을 KST(Asia/Seoul)로 정규화한다.

    naive datetime(tzinfo=None 또는 utcoffset()=None)은 거부한다.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware (got naive datetime)")
    return value.astimezone(KST)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class WorkType(str, Enum):
    """공종 코드 (construction_rules.yaml의 work_type과 1:1 매칭되어야 함)"""
    CONCRETE_POURING = "CONCRETE_POURING"   # 콘크리트 타설
    STEEL_ERECTION = "STEEL_ERECTION"       # 철골 세우기
    WATERPROOFING = "WATERPROOFING"         # 방수공사


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DelayPolicyType(str, Enum):
    PROPORTIONAL = "PROPORTIONAL"  # affected_hours 기반 비례 산정 (minimum_delay_days 없음)
    FULL_DAY = "FULL_DAY"          # 작업 중단 시 최소 N일 적용 (minimum_delay_days 필수)


class ForecastSource(str, Enum):
    VILAGE_FCST = "VilageFcst"        # 단기예보 (1시간 단위)
    ULTRA_SRT_NCST = "UltraSrtNcst"   # 초단기실황
    ULTRA_SRT_FCST = "UltraSrtFcst"   # 초단기예보 (확장 범위, MVP 제외 가능)


class ServiceStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"   # 일부 API 실패했지만 fallback으로 결과 생성
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

class WeatherRiskRequest(BaseModel):
    project_id: str = Field(..., description="현장/프로젝트 식별자, 예: PJT-001")
    site_name: str = Field(..., description="현장명, 예: 서울 A현장")

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)

    work_type: WorkType
    scheduled_start: datetime = Field(..., description="timezone-aware (내부적으로 KST 정규화됨)")
    scheduled_end: datetime = Field(..., description="timezone-aware (내부적으로 KST 정규화됨)")

    # MidFcst 제외이므로 WEEKLY는 아직 미지원. 추후 확장 시 추가.
    query_type: Literal["IMMEDIATE", "SHORT_TERM"] = "SHORT_TERM"

    @field_validator("scheduled_start", "scheduled_end", mode="after")
    @classmethod
    def _to_kst(cls, v: datetime) -> datetime:
        return normalize_to_kst(v)

    @model_validator(mode="after")
    def _check_order(self) -> "WeatherRiskRequest":
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


# ---------------------------------------------------------------------------
# Response - sub objects
# ---------------------------------------------------------------------------

class Site(BaseModel):
    site_name: str
    latitude: float
    longitude: float
    grid_x: int = Field(..., description="기상청 격자 nx")
    grid_y: int = Field(..., description="기상청 격자 ny")


class Work(BaseModel):
    work_type: WorkType
    scheduled_start: datetime
    scheduled_end: datetime

    @field_validator("scheduled_start", "scheduled_end", mode="after")
    @classmethod
    def _to_kst(cls, v: datetime) -> datetime:
        return normalize_to_kst(v)

    @model_validator(mode="after")
    def _check_order(self) -> "Work":
        if self.scheduled_end <= self.scheduled_start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


class ForecastMeta(BaseModel):
    source: ForecastSource
    base_datetime: datetime = Field(..., description="API 발표시각 (fallback 적용 후 실제 사용된 값)")
    fetched_at: datetime = Field(..., description="실제 호출 시각")

    @field_validator("base_datetime", "fetched_at", mode="after")
    @classmethod
    def _to_kst(cls, v: datetime) -> datetime:
        return normalize_to_kst(v)

    @model_validator(mode="after")
    def _check_order(self) -> "ForecastMeta":
        if self.fetched_at < self.base_datetime:
            raise ValueError("fetched_at must not be earlier than base_datetime")
        return self


class WeatherSummary(BaseModel):
    """작업시간(08~16시) 구간 전체에 대한 집계값. 단일 시점 값이 아님."""
    max_pop_pct: Optional[int] = Field(None, ge=0, le=100, description="강수확률 최대값 (%)")
    total_pcp_mm: Optional[float] = Field(None, ge=0, description="강수량 합계 (mm)")
    max_wsd_mps: Optional[float] = Field(None, ge=0, description="풍속 최대값 (m/s)")
    min_tmp_c: Optional[float] = Field(None, description="기온 최소값 (℃)")
    has_precipitation: bool = False


class RiskPeriod(BaseModel):
    """룰이 발동된 시간 구간 (감사 추적용 근거)"""
    start_at: datetime
    end_at: datetime
    risk_level: RiskLevel
    triggered_rule_ids: list[str] = Field(default_factory=list)

    @field_validator("start_at", "end_at", mode="after")
    @classmethod
    def _to_kst(cls, v: datetime) -> datetime:
        return normalize_to_kst(v)

    @model_validator(mode="after")
    def _check_order(self) -> "RiskPeriod":
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class DelayPolicy(BaseModel):
    """
    delay_day_equivalent (RiskResult)는 항상 affected_hours / 8 의 순수 시간 환산값이다.
    FULL_DAY 정책이라도 delay_day_equivalent 자체는 바뀌지 않는다 -
    "최소 N일을 적용해야 한다"는 권고는 이 객체의 minimum_delay_days로만 표현하고,
    실제 최종 지연일 확정은 공정 지연 계산기(다른 에이전트)의 책임이다.
    """
    type: DelayPolicyType = DelayPolicyType.PROPORTIONAL
    minimum_delay_days: Optional[int] = Field(
        None, description="FULL_DAY일 때만 사용. PROPORTIONAL이면 반드시 null."
    )
    reason: Optional[str] = Field(
        None, description="FULL_DAY일 때 필수 - 왜 최소 N일인지 설명 (발표 시 근거)"
    )

    @model_validator(mode="after")
    def _check_policy_consistency(self) -> "DelayPolicy":
        if self.type == DelayPolicyType.FULL_DAY:
            if self.minimum_delay_days is None:
                raise ValueError("minimum_delay_days is required for FULL_DAY")
            if self.minimum_delay_days < 1:
                raise ValueError("minimum_delay_days must be at least 1 for FULL_DAY")
            if not self.reason:
                raise ValueError("reason is required for FULL_DAY")
        elif self.type == DelayPolicyType.PROPORTIONAL:
            if self.minimum_delay_days is not None:
                raise ValueError("minimum_delay_days must be null for PROPORTIONAL")
        return self


class RiskResult(BaseModel):
    """
    이 서비스의 최종 산출물. '확정 지연일'은 포함하지 않는다.
    공정 지연 계산기(다른 에이전트)가 이 값을 받아 최종 지연일/비용을 산정한다.
    """
    risk_level: RiskLevel
    work_stoppage_required: bool
    affected_hours: float = Field(..., ge=0, description="작업시간 내 위험 시간 합계")
    recommended_delay_hours: float = Field(..., ge=0)
    delay_day_equivalent: float = Field(
        ..., ge=0, description="affected_hours / 8 (1일=8시간 가정) - 서버가 채우는 계약값"
    )
    delay_policy: DelayPolicy = Field(default_factory=DelayPolicy)

    @model_validator(mode="after")
    def _check_delay_day_equivalent(self) -> "RiskResult":
        expected = self.affected_hours / 8
        if abs(self.delay_day_equivalent - expected) > 1e-6:
            raise ValueError(
                "delay_day_equivalent must equal affected_hours / 8 "
                f"(expected {expected}, got {self.delay_day_equivalent})"
            )
        return self


# ---------------------------------------------------------------------------
# Response - top level
# ---------------------------------------------------------------------------

class WeatherRiskResponse(BaseModel):
    project_id: str
    site: Site
    work: Work
    query_type: Literal["IMMEDIATE", "SHORT_TERM"]
    forecast: ForecastMeta
    summary: WeatherSummary
    risk_periods: list[RiskPeriod] = Field(default_factory=list)
    risk_result: RiskResult
    status: ServiceStatus = ServiceStatus.SUCCESS
    warnings: list[str] = Field(default_factory=list)
