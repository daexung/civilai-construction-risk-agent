"""계산 도구가 함께 쓰는 입력 검증·콘솔 보조 함수. 이 저장소의 다른 모듈을 가져오지 않는다.

quantity.py와 unit_price.py가 모두 이 모듈만 가져다 쓰므로 둘 사이에 순환 참조가 생기지 않는다
(의존 방향: inputs ← quantity ← unit_price).
"""

import re
import sys
from decimal import Decimal

VOLUME_RE = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^\d+(?:\.\d+)?$")


class VolumeError(ValueError):
    """물량 입력이 계산에 쓸 수 없는 값."""


def parse_volume(value) -> Decimal:
    """사용자 물량(㎥)을 검증한다. 양의 10진수만 받는다(쉼표 자리 구분 허용, 부호·지수·NaN 거부)."""
    text = str(value).strip() if value is not None else ""
    if not VOLUME_RE.match(text):
        raise VolumeError(f"물량은 양의 숫자(㎥)여야 합니다: {value!r}")
    volume = Decimal(text.replace(",", ""))
    if volume <= 0:
        raise VolumeError(f"물량은 0보다 커야 합니다: {value!r}")
    return volume


def safe_console() -> None:
    """Windows 기본 콘솔(cp949)에 없는 글자가 원문 인용 등에 섞여도 출력 중에 멈추지 않게 한다.

    콘솔 인코딩은 바꾸지 않는다. UTF-8이 아닌 출력에서만, 인코딩할 수 없는 글자를 '?'로 대신한다.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if hasattr(stream, "reconfigure") and encoding != "utf8":
            stream.reconfigure(errors="replace")
