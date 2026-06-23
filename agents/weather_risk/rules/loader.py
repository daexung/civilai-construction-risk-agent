"""
construction_rules.yaml 로더 (T1)

load_construction_rules()는 다음을 보장한다:
- 각 work_type 그룹이 WorkTypeRuleSet 스키마를 통과
- rule_id가 전체 YAML에서 유일
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .schema import WorkTypeRuleSet


def load_construction_rules(path: str | Path) -> dict[str, WorkTypeRuleSet]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("construction_rules.yaml must be a mapping at the top level")

    rule_sets: dict[str, WorkTypeRuleSet] = {}
    for key, value in raw.items():
        try:
            rule_sets[key] = WorkTypeRuleSet.model_validate(value)
        except Exception as exc:  # re-raise with which top-level key failed
            raise ValueError(f"Invalid rule set '{key}': {exc}") from exc

    all_ids: list[str] = []
    for rs in rule_sets.values():
        all_ids.extend(r.rule_id for r in rs.rules)
    dupes = {i for i in all_ids if all_ids.count(i) > 1}
    if dupes:
        raise ValueError(f"Duplicate rule_id across construction_rules.yaml: {dupes}")

    return rule_sets
