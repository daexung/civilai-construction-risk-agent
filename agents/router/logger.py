"""
디버깅용 실행 로그 — logs/ 폴더에 하루 1개 파일(날짜별)로 누적 기록.
라우터 분류 근거, 노드 흐름, 툴 호출, 에러(스택트레이스)를 기록한다.
같은 날 여러 번 실행해도 같은 파일에 이어서 기록(append)된다.

루트 로거에 핸들러를 부착하므로 equipment_standby/tools.py 등에서 쓰는
`import logging; logging.info(...)` 호출도 같은 파일에 함께 기록된다.

사용: from logger import get_logger
      log = get_logger(__name__)
      log.debug("...")  # 흐름 추적용
      log.info("...")   # 주요 이벤트
      log.exception("...")  # 에러 + 스택트레이스
"""
import logging
import os
from datetime import datetime

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

# 날짜 기준 로그 파일 1개 — 하루 동안의 모든 실행이 이 파일에 누적됨
_LOG_FILE = os.path.join(_LOG_DIR, f"{datetime.now():%Y%m%d}.log")

_configured = False


def _configure_root() -> None:
    """루트 로거에 파일 핸들러를 1회만 부착. 모든 하위 모듈 로그가 같은 파일로 모인다."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)

    # boto3/botocore/urllib3 등 외부 라이브러리 DEBUG 로그는 너무 방대하므로 WARNING 이상만 통과
    for noisy in ("boto3", "botocore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """이름별 로거 반환. 핸들러는 루트에만 부착되어 있으므로 propagate로 같은 파일에 모인다."""
    _configure_root()
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    return logger
