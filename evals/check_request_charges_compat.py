"""배포 호환: 요청별 차감 테이블(chat_request_charges)은 AGENT_MODE=tools에서만 쓴다.

로컬 Supabase(127.0.0.1:54322)에서 테이블 이름을 잠시 바꿔 '마이그레이션 전 DB'를 만들고, 끝나면 되돌린다.
- K1 기존 모드: 테이블 없이도 채팅·같은 request_id 재전송 정상
- K2 tools 모드: 테이블 없으면 /api/ready 503, 채팅 503
- K3 tools 모드: 테이블 있으면 /api/ready 200
유료 호출 없음. 사용량은 2099년 픽스처 날짜에만 쌓고 지운다.

사용: CHAT_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres python evals/check_request_charges_compat.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ.update(AGENT_OFFLINE="1", AGENT_LLM="off")
os.environ.pop("AGENT_MODE", None)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.api import chat_storage, main as api, usage_limits as limits  # noqa: E402

TABLE, HIDDEN = "chat_request_charges", "chat_request_charges_compat_hidden"
DAY = datetime(2099, 10, 8, 12, tzinfo=limits.KST)


def rename(src: str, dst: str) -> None:
    with chat_storage.connection() as conn:
        conn.execute(f"ALTER TABLE agent_state.{src} RENAME TO {dst}")  # 고정 상수 이름만 쓴다


def exists(name: str) -> bool:
    with chat_storage.connection() as conn:
        return conn.execute("SELECT to_regclass(%s) AS t", (f"agent_state.{name}",)).fetchone()["t"] is not None


def fake_response(payload, *args, **kwargs):
    return {"thread_id": payload.thread_id or uuid4().hex, "answer": "fixture", "status": "OUT_OF_SCOPE"}


def main() -> int:
    if "127.0.0.1:54322" not in os.environ.get("CHAT_DATABASE_URL", ""):
        raise SystemExit("Set CHAT_DATABASE_URL to local Supabase port 54322 only")
    if not exists(TABLE) or exists(HIDDEN):
        raise SystemExit(f"로컬 DB에 agent_state.{TABLE}가 있어야 하고 {HIDDEN}는 없어야 합니다")
    checks = []
    rename(TABLE, HIDDEN)
    try:
        with patch.object(limits, "now", return_value=DAY), patch.object(api, "_chat_response", side_effect=fake_response):
            guest = {"X-Guest-Session": "compat-" + str(uuid4())}
            body = {"message": "콘크리트 품셈", "request_id": str(uuid4())}
            with TestClient(api.app) as http:
                first = http.post("/api/chat", headers=guest, json=body)
                again = http.post("/api/chat", headers=guest, json=body)
            checks.append(("K1 기존 모드: 테이블 없이 채팅·재전송 정상(재전송은 차감 없음)",
                           first.status_code == 200 and again.status_code == 200
                           and again.json()["usage"]["used"] == first.json()["usage"]["used"]))
            with patch.dict(os.environ, {"AGENT_MODE": "tools"}), TestClient(api.app) as http:
                chat = http.post("/api/chat", headers=guest, json={"message": "콘크리트 품셈", "request_id": str(uuid4())})
                ready = http.get("/api/ready")
            checks.append(("K2 tools 모드·테이블 없음: /api/ready 503, 채팅 503",
                           ready.status_code == 503 and chat.status_code == 503))
    finally:
        rename(HIDDEN, TABLE)
        with chat_storage.connection() as conn:
            conn.execute("DELETE FROM agent_state.daily_chat_usage WHERE usage_day=%s", (DAY.date(),))
    with patch.dict(os.environ, {"AGENT_MODE": "tools"}), TestClient(api.app) as http:
        api._READY_EVENT.wait(300)
        checks.append(("K3 tools 모드·테이블 있음: /api/ready 200", http.get("/api/ready").status_code == 200))
    checks.append(("K4 테이블 이름 복구", exists(TABLE) and not exists(HIDDEN)))
    for name, ok in checks:
        print(("PASS " if ok else "FAIL ") + name)
    passed = sum(ok for _, ok in checks)
    print(f"통과 {passed} / 전체 {len(checks)}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
