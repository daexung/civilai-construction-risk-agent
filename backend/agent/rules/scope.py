"""Service division scope shared by search and draft specs."""

import json
from pathlib import Path

CONFIG = Path(__file__).with_name("scope_config.json")


def enabled_divisions() -> tuple[str, ...]:
    divisions = json.loads(CONFIG.read_text(encoding="utf-8"))["divisions"]
    if not isinstance(divisions, list) or not divisions or any(
            not isinstance(value, str) or not value for value in divisions):
        raise ValueError("서비스 부문 설정이 비었거나 잘못되었습니다")
    if len(divisions) != len(set(divisions)):
        raise ValueError("서비스 부문 설정에 중복이 있습니다")
    return tuple(divisions)
