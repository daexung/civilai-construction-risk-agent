"""T7: RuleEngine — 시간별 HourlyForecast에 공종 룰을 적용해 RiskEvaluation을 반환한다."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import NamedTuple

from weather_risk.models import RiskLevel, RiskPeriod, WorkType
from weather_risk.parsers.hourly_forecast import HourlyForecast
from weather_risk.rules.loader import load_construction_rules
from weather_risk.rules.schema import WorkTypeRuleSet

_DEFAULT_RULES_PATH = Path(__file__).parent / "construction_rules.yaml"

_SEVERITY_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
}

_CMP_OPS = {
    "gte": lambda v, t: v >= t,
    "gt":  lambda v, t: v > t,
    "lt":  lambda v, t: v < t,
    "lte": lambda v, t: v <= t,
    "eq":  lambda v, t: v == t,
}


class RiskEvaluation(NamedTuple):
    risk_periods: list[RiskPeriod]
    risk_level: RiskLevel
    work_stoppage_required: bool
    warnings: list[str]


def evaluate_risk(
    forecasts: list[HourlyForecast],
    work_type: WorkType,
    rule_sets: dict[str, WorkTypeRuleSet] | None = None,
) -> RiskEvaluation:
    """각 HourlyForecast에 work_type 룰을 적용하고 연속 구간을 RiskPeriod로 병합한다."""
    if rule_sets is None:
        rule_sets = load_construction_rules(_DEFAULT_RULES_PATH)

    matched_rs = next(
        (rs for rs in rule_sets.values() if rs.work_type == work_type),
        None,
    )
    if matched_rs is None:
        return RiskEvaluation(
            risk_periods=[],
            risk_level=RiskLevel.LOW,
            work_stoppage_required=False,
            warnings=[f"No rules defined for work_type: {work_type}"],
        )

    if not forecasts:
        return RiskEvaluation(
            risk_periods=[],
            risk_level=RiskLevel.LOW,
            work_stoppage_required=False,
            warnings=["No forecasts to evaluate"],
        )

    # (forecast, severity, sorted_rule_ids, stop_work) for each triggered slot
    triggered_slots: list[tuple[HourlyForecast, RiskLevel, list[str], bool]] = []

    for forecast in forecasts:
        slot_ids: list[str] = []
        slot_severity: RiskLevel | None = None
        slot_stop = False

        for rule in matched_rs.rules:
            raw = getattr(forecast, rule.field, None)
            if raw is None:
                continue

            if rule.operator == "not_in":
                triggered = str(raw) not in rule.value
            else:
                try:
                    triggered = _CMP_OPS[rule.operator](float(raw), rule.value)
                except (ValueError, TypeError):
                    continue

            if triggered:
                slot_ids.append(rule.rule_id)
                if slot_severity is None or _SEVERITY_ORDER[rule.severity] > _SEVERITY_ORDER[slot_severity]:
                    slot_severity = rule.severity
                if rule.action == "STOP_WORK":
                    slot_stop = True

        if slot_ids:
            triggered_slots.append((forecast, slot_severity, sorted(slot_ids), slot_stop))  # type: ignore[arg-type]

    if not triggered_slots:
        return RiskEvaluation(
            risk_periods=[],
            risk_level=RiskLevel.LOW,
            work_stoppage_required=False,
            warnings=[],
        )

    risk_periods = _merge_slots(triggered_slots)
    overall_risk = max(
        (p.risk_level for p in risk_periods),
        key=lambda rl: _SEVERITY_ORDER[rl],
    )
    work_stoppage = any(stop for _, _, _, stop in triggered_slots)

    return RiskEvaluation(
        risk_periods=risk_periods,
        risk_level=overall_risk,
        work_stoppage_required=work_stoppage,
        warnings=[],
    )


def _merge_slots(
    slots: list[tuple[HourlyForecast, RiskLevel, list[str], bool]],
) -> list[RiskPeriod]:
    """연속(1시간 간격) + 동일 risk_level + 동일 rule_ids 슬롯을 하나의 RiskPeriod로 병합."""
    result: list[RiskPeriod] = []
    cur_fc, cur_level, cur_ids, _ = slots[0]
    cur_start = cur_fc.forecast_at
    cur_end = cur_start + timedelta(hours=1)

    for fc, level, ids, _ in slots[1:]:
        if fc.forecast_at == cur_end and level == cur_level and ids == cur_ids:
            cur_end = fc.forecast_at + timedelta(hours=1)
        else:
            result.append(RiskPeriod(start_at=cur_start, end_at=cur_end,
                                     risk_level=cur_level, triggered_rule_ids=cur_ids))
            cur_start = fc.forecast_at
            cur_end = cur_start + timedelta(hours=1)
            cur_level = level
            cur_ids = ids

    result.append(RiskPeriod(start_at=cur_start, end_at=cur_end,
                              risk_level=cur_level, triggered_rule_ids=cur_ids))
    return result
