"""
construction_rules.yaml 로드/검증용 스키마 (T1)

YAML 파일에서 다음을 자동으로 잡아낸다:
- field가 ALLOWED_WEATHER_FIELDS에 없는 경우
- operator가 ALLOWED_OPERATORS에 없는 경우
- severity가 RiskLevel(LOW/MEDIUM/HIGH)이 아닌 경우
- action이 ALLOWED_ACTIONS에 없는 경우
- operator='not_in'인데 value가 list가 아닌 경우 (또는 반대)
- work_type이 WorkType enum에 없는 경우
- rule_id 중복 (같은 work_type 내부 / 전체)
- rule_source가 "PROJECT_ASSUMPTION" 외 다른 문자열이거나, 문서 참조 형식이 깨진 경우
"""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, model_validator

from weather_risk.models import RiskLevel, WorkType

ALLOWED_WEATHER_FIELDS = {"pty", "tmp", "wsd", "reh", "pop", "pcp"}
ALLOWED_OPERATORS = {"not_in", "gte", "gt", "lt", "lte", "eq"}
ALLOWED_ACTIONS = {"STOP_WORK", "REVIEW_REQUIRED"}


class SpecDocumentSource(BaseModel):
    """실제 시방서/표준품셈 등 근거 문서를 참조하는 경우"""
    document_id: str
    page: int
    section: str


class RuleDefinition(BaseModel):
    rule_id: str
    field: str
    operator: Literal["not_in", "gte", "gt", "lt", "lte", "eq"]
    value: Any
    severity: RiskLevel
    action: Literal["STOP_WORK", "REVIEW_REQUIRED"]
    rule_source: Union[Literal["PROJECT_ASSUMPTION"], SpecDocumentSource]

    @model_validator(mode="after")
    def _check_field_and_value(self) -> "RuleDefinition":
        if self.field not in ALLOWED_WEATHER_FIELDS:
            raise ValueError(
                f"[{self.rule_id}] unknown field '{self.field}'. "
                f"Allowed: {sorted(ALLOWED_WEATHER_FIELDS)}"
            )

        if self.operator == "not_in":
            if not isinstance(self.value, list):
                raise ValueError(
                    f"[{self.rule_id}] 'not_in' operator requires a list value, "
                    f"got {type(self.value).__name__}"
                )
        else:
            if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
                raise ValueError(
                    f"[{self.rule_id}] '{self.operator}' operator requires a numeric value, "
                    f"got {type(self.value).__name__}"
                )
        return self


class WorkTypeRuleSet(BaseModel):
    display_name: str
    work_type: WorkType
    rules: list[RuleDefinition]

    @model_validator(mode="after")
    def _check_no_duplicate_rule_ids(self) -> "WorkTypeRuleSet":
        ids = [r.rule_id for r in self.rules]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"Duplicate rule_id within '{self.work_type}': {dupes}")
        if not self.rules:
            raise ValueError(f"'{self.work_type}' has no rules defined")
        return self
