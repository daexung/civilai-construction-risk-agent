"""로컬 개발 백엔드(127.0.0.1:8001). dev 브랜치를 운영과 같은 방식으로 띄워 화면으로 확인할 때 쓴다.

기본: 운영과 같은 경로 — Gemini 켜짐(AGENT_LLM=on), 품셈 지식 검색 v1.
  - 품셈 지식 DB는 .env의 CHAT_DATABASE_URL을 **읽기 전용 연결로만** 쓴다(runtime.Engine이 read_only로 연다).
  - 대화 저장·사용량 DB는 끈다. 로컬 대화가 운영 DB에 쌓이지 않게 하려는 것이라, 회원 대화 저장은 동작하지 않는다(비회원으로 시험).
  - 사용량은 항상 0회로 보여 준다.
--offline: 외부 호출 없이(Gemini 끔, BM25 검색) 화면 배치만 볼 때.

사용(저장소 루트): .venv/Scripts/python.exe scripts/dev_server.py [--offline]
프론트: .claude/launch.json의 frontend(3001, CIVILAI_API_PROXY=http://127.0.0.1:8001)
"""
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))

if "--offline" in sys.argv:
    os.environ.update({"AGENT_OFFLINE": "1", "AGENT_LLM": "off", "KNOWLEDGE_RETRIEVAL": "legacy"})
else:
    os.environ.update({"AGENT_LLM": "on", "KNOWLEDGE_RETRIEVAL": "v1", "AGENT_MODE": "tools",
                       "LLM_PROVIDER": os.environ.get("LLM_PROVIDER", "studio")})
    os.environ.setdefault("KNOWLEDGE_DATABASE_URL", os.environ.get("CHAT_DATABASE_URL", ""))
os.environ["APP_ENV"] = "development"
os.environ.pop("CHAT_DATABASE_URL", None)  # 대화·사용량 저장을 끈다(운영 DB에 쓰지 않음)

import uvicorn  # noqa: E402
from backend.api import usage_limits  # noqa: E402

fake = usage_limits._summary(usage_limits.now(), 0, 0, False)
with patch("backend.api.usage_limits.processing", return_value=nullcontext((None, "local", False))), \
        patch("backend.api.usage_limits.consume", return_value=fake), \
        patch("backend.api.usage_limits.status", return_value=fake), \
        patch("backend.api.usage_limits.read", return_value=fake):
    from backend.api.main import app  # noqa: E402
    uvicorn.run(app, host="127.0.0.1", port=8001)
