"""명세 입력을 품 산출 조건과 가격 조건으로 나눈다.

계산기(tools/calc)가 이 모듈을 가져오므로 specs.py·계산기를 가져오지 않는다(순환 참조 방지).

- 가격 조건: supply_rules의 입력(관급/사급 등)과, when으로 그 값에 딸린 입력(사급일 때 레미콘 단가 등).
- 가격 조건 후보라도 품 계산·할증·보류·다른 품 조건의 when 어디에든 이름이 나오면 품 조건으로 둔다.
  쓰임이 불확실하면 품 조건이다.
"""

from __future__ import annotations

import json

# 가격 단계에서만 읽는 명세 키. 여기 나오는 이름은 품 계산에 쓰인 것으로 보지 않는다.
_PRICE_KEYS = {"inputs", "supply_rules", "cost_rules"}


def price_fields(spec: dict) -> frozenset[str]:
    fields = {field["name"]: field for field in spec.get("inputs", [])}
    when = {name: (field.get("when") or {}).get("input") for name, field in fields.items()}
    labor_text = json.dumps({key: value for key, value in spec.items() if key not in _PRICE_KEYS},
                            ensure_ascii=False)
    supply = {rule.get("input") for rule in spec.get("supply_rules", [])} & fields.keys()
    candidates = set(supply)
    while extra := {name for name in fields if when[name] in candidates} - candidates:
        candidates |= extra
    # 품 조건에 쓰이는 후보를 빼 나간다. 후보는 줄기만 하므로 반드시 끝난다.
    while True:
        labor_when = {when[name] for name in fields if name not in candidates}
        kept = {name for name in candidates
                if (name in supply or when[name] in candidates)
                and f'"{name}"' not in labor_text and name not in labor_when}
        if kept == candidates:
            return frozenset(candidates)
        candidates = kept
