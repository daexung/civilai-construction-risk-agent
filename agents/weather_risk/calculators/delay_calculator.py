"""T8: DelayCalculator — RiskEvaluation → RiskResult 변환.

affected_hours / work_hours_per_day = delay_day_equivalent.
RiskResult Pydantic validator가 affected_hours/8 일치를 검증하므로,
work_hours_per_day != 8이면 ValidationError — 의도된 가드레일.
"""

from __future__ import annotations

from weather_risk.models import (
    DelayPolicy,
    DelayPolicyType,
    RiskResult,
    WorkType,
)
from weather_risk.rules.engine import RiskEvaluation

# PROJECT_ASSUMPTION: 콘크리트 타설만 FULL_DAY 정책, 나머지는 비례 산정.
# 실제 기준은 RAG(표준시방서) 확보 후 재검토.
WORK_TYPE_DELAY_POLICY: dict[WorkType, dict] = {
    WorkType.CONCRETE_POURING: {
        "type": DelayPolicyType.FULL_DAY,
        "minimum_delay_days": 1,
        "reason": "콘크리트 타설 개시 후 작업 중단 시 품질 위험 (PROJECT_ASSUMPTION)",
    },
    WorkType.STEEL_ERECTION: {
        "type": DelayPolicyType.PROPORTIONAL,
    },
    WorkType.WATERPROOFING: {
        "type": DelayPolicyType.PROPORTIONAL,
    },
}


def calculate_delay(
    evaluation: RiskEvaluation,
    work_type: WorkType,
    work_hours_per_day: int = 8,
) -> RiskResult:
    """RiskEvaluation → RiskResult.

    work_hours_per_day 기본값은 8 고정.
    RiskResult validator: delay_day_equivalent == affected_hours / 8 (1e-6 tolerance).
    다른 값을 넘기면 ValidationError — 이는 의도된 가드레일이다.
    """
    affected_hours = sum(
        (p.end_at - p.start_at).total_seconds() / 3600
        for p in evaluation.risk_periods
    )
    recommended_delay_hours = affected_hours
    delay_day_equivalent = affected_hours / work_hours_per_day

    if not evaluation.work_stoppage_required:
        delay_policy = DelayPolicy(type=DelayPolicyType.PROPORTIONAL)
    else:
        policy_cfg = WORK_TYPE_DELAY_POLICY.get(
            work_type, {"type": DelayPolicyType.PROPORTIONAL}
        )
        delay_policy = DelayPolicy(**policy_cfg)

    return RiskResult(
        risk_level=evaluation.risk_level,
        work_stoppage_required=evaluation.work_stoppage_required,
        affected_hours=affected_hours,
        recommended_delay_hours=recommended_delay_hours,
        delay_day_equivalent=delay_day_equivalent,
        delay_policy=delay_policy,
    )
