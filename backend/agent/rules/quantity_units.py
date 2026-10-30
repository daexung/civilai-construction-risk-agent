"""물량 입력의 단위가 작업 종류에 따라 달라지는 명세를 읽는 공통 규칙.

명세의 물량 입력에 `unit_by`를 선언한다.
    {"name": "quantity", "unit": "개/m/㎡",
     "unit_by": {"input": "work_type", "values": {"지주 설치": "개", "와이어 설치": "m", "철망 설치": "㎡"}}}
`unit`은 사람이 읽는 설명이고, 실제 단위는 선택 입력의 값으로 정해진다. 선택이 아직 없으면 단위는 None이다
(그때는 물량을 묻거나 검사하지 않는다). 계산기·상담·Excel이 모두 이 함수로 같은 단위를 읽는다.
"""
from __future__ import annotations


def quantity_unit(field: dict | None, values: dict | None) -> str | None:
    if not field:
        return None
    selector = field.get("unit_by")
    if not selector:
        return field.get("unit")
    return selector["values"].get((values or {}).get(selector["input"]))


def resolve_quantity_field(field: dict | None, values: dict | None) -> dict | None:
    """unit_by가 있으면 현재 선택에 맞는 단위를 `unit`에 넣은 사본을, 없으면 그대로 돌려준다."""
    if not field or not field.get("unit_by"):
        return field
    return {**field, "unit": quantity_unit(field, values)}
