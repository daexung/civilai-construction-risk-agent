"""Durable KST daily limits; atomic reservations precede any agent work."""
from __future__ import annotations

import hashlib
import hmac
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg
from fastapi import HTTPException
from backend.api import chat_storage

GUEST_LIMIT = 5
MEMBER_LIMIT = 20
SERVICE_LIMIT = 500
KST = timezone(timedelta(hours=9))


def now():
    return datetime.now(KST)


def subject(user_id: str | None, ip: str | None) -> str:
    secret = os.getenv("QUOTA_HASH_SECRET") or os.getenv("CHAT_DATABASE_URL")
    if not secret or (not user_id and not ip):
        raise HTTPException(503, "사용량 확인이 준비되지 않았습니다.")
    def hashed(value):
        return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()
    if not user_id:
        return 'guest:' + hashed(ip)
    legacy = 'member:' + hashed(user_id)
    try:
        with chat_storage.connection() as conn, conn.transaction():
            # Google provider IDs survive deleting and recreating a Supabase user.
            row = conn.execute("SELECT provider_id FROM auth.identities WHERE user_id=%s AND provider='google'", (user_id,)).fetchone()
            if not row:
                return legacy
            stable = 'member:' + hashed('google:' + row['provider_id'])
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('quota-upgrade:' + legacy,))
            for table, prefix in [('daily_chat_usage', ''), ('daily_feedback_usage', 'feedback:'), ('daily_answer_feedback_usage', '')]:
                # Table names and prefixes are fixed constants, never request input.
                rows = conn.execute(f'DELETE FROM agent_state.{table} WHERE subject=%s RETURNING usage_day,used', (prefix + legacy,)).fetchall()
                for item in rows:
                    conn.execute(f'INSERT INTO agent_state.{table}(usage_day,subject,used) VALUES (%s,%s,%s) '
                                 f'ON CONFLICT (usage_day,subject) DO UPDATE SET used={table}.used+EXCLUDED.used',
                                 (item['usage_day'], prefix + stable, item['used']))
            return stable
    except psycopg.Error:
        raise HTTPException(503, '사용량 확인에 실패했습니다. 잠시 후 다시 시도해 주세요.') from None


def _summary(current, personal: int, total: int, member: bool):
    reset = datetime.combine(current.date() + timedelta(days=1), datetime.min.time(), KST)
    limit = MEMBER_LIMIT if member else GUEST_LIMIT
    return {"limit": limit, "used": personal, "remaining": max(0, limit - personal),
            "service_limit": SERVICE_LIMIT, "service_remaining": max(0, SERVICE_LIMIT - total),
            "resets_at": reset.isoformat(), "timezone": "Asia/Seoul"}


def status(conn, key: str, member: bool):
    current = now()
    rows = conn.execute("SELECT subject, used FROM agent_state.daily_chat_usage "
                        "WHERE usage_day=%s AND subject IN (%s, 'service')", (current.date(), key)).fetchall()
    counts = {row["subject"]: row["used"] for row in rows}
    return _summary(current, counts.get(key, 0), counts.get("service", 0), member)


@contextmanager
def processing(user_id: str | None, ip: str | None):
    key = subject(user_id, ip)
    try:
        with chat_storage.connection() as conn:
            lock = "chat-processing:" + key
            acquired = conn.execute("SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS acquired", (lock,)).fetchone()["acquired"]
            if not acquired:
                raise HTTPException(429, {"code": "REQUEST_IN_PROGRESS", "message": "이전 요청을 처리 중입니다. 완료 후 다시 보내 주세요."},
                                    headers={"Retry-After": "2"})
            try:
                yield conn, key, bool(user_id)
            finally:
                conn.execute("SELECT pg_advisory_unlock(hashtextextended(%s,0))", (lock,))
    except psycopg.Error:
        # A unavailable quota DB must never allow unlimited paid calls.
        raise HTTPException(503, "사용량 확인에 실패했습니다. 잠시 후 다시 시도해 주세요.") from None


def require_request_charges() -> None:
    """AGENT_MODE=tools 준비 검사: 요청별 차감 기록 테이블(마이그레이션 20261008000100)이 없으면 시작 실패."""
    if not os.getenv("CHAT_DATABASE_URL"):
        return
    with chat_storage.connection() as conn:
        if conn.execute("SELECT to_regclass('agent_state.chat_request_charges') AS t").fetchone()["t"] is None:
            raise RuntimeError("agent_state.chat_request_charges가 없습니다. 마이그레이션 20261008000100을 적용하세요.")


def request_key(kind: str, owner: str, conversation: str, request_id: str) -> str:
    """같은 요청을 가리키는 키. 원래 ID·식별자는 HMAC으로만 남긴다."""
    secret = os.getenv("QUOTA_HASH_SECRET") or os.getenv("CHAT_DATABASE_URL")
    if not secret:
        raise HTTPException(503, "사용량 확인이 준비되지 않았습니다.")
    return hmac.new(secret.encode(), "\x1f".join((kind, owner, conversation, request_id)).encode(),
                    hashlib.sha256).hexdigest()


def consume(context, request: tuple[str, str, str, str] | str | None = None):
    """한 요청을 차감한다. request((회원/비회원, 소유자, 대화, request_id) 또는 request_key)를 주면
    같은 요청은 재시작·다른 인스턴스에서도 한 번만 차감한다."""
    conn, key, member = context
    if isinstance(request, tuple):
        request = request_key(*request)
    current = now()
    day = current.date()
    with conn.transaction():
        conn.execute("INSERT INTO agent_state.daily_chat_usage(usage_day,subject) VALUES (%s,'service') ON CONFLICT DO NOTHING", (day,))
        total = conn.execute("SELECT used FROM agent_state.daily_chat_usage WHERE usage_day=%s AND subject='service' FOR UPDATE", (day,)).fetchone()["used"]
        row = conn.execute("SELECT used FROM agent_state.daily_chat_usage WHERE usage_day=%s AND subject=%s", (day, key)).fetchone()
        personal = row["used"] if row else 0
        if request is not None and not conn.execute(
                "INSERT INTO agent_state.chat_request_charges(request_key,usage_day) VALUES (%s,%s) "
                "ON CONFLICT DO NOTHING RETURNING request_key", (request, day)).fetchone():
            # 이미 차감한 요청(실패 후 재시도 등): 한도 검사·차감 없이 현재 사용량만 돌려준다.
            return _summary(current, personal, total, member)
        usage = _summary(current, personal, total, member)
        if usage["remaining"] == 0 or usage["service_remaining"] == 0:
            service = usage["service_remaining"] == 0
            message = ("오늘 서비스 전체 사용량 500회에 도달했습니다. 한국 시간 자정 이후 다시 이용해 주세요." if service else
                       f"오늘 사용 가능한 {usage['limit']}회를 모두 사용했습니다. 한국 시간 자정 이후 다시 이용해 주세요.")
            raise HTTPException(429, {"code": "SERVICE_DAILY_LIMIT" if service else "PERSONAL_DAILY_LIMIT",
                                     "message": message, "usage": usage},
                                headers={"Retry-After": str(max(1, int((datetime.fromisoformat(usage['resets_at']) - current).total_seconds())))})
        conn.execute("UPDATE agent_state.daily_chat_usage SET used=used+1 WHERE usage_day=%s AND subject='service'", (day,))
        conn.execute("INSERT INTO agent_state.daily_chat_usage(usage_day,subject,used) VALUES (%s,%s,1) "
                     "ON CONFLICT (usage_day,subject) DO UPDATE SET used=daily_chat_usage.used+1", (day, key))
        conn.execute("DELETE FROM agent_state.daily_chat_usage WHERE usage_day < "
                     "((now() AT TIME ZONE 'Asia/Seoul')::date - 7)")
        if request is not None:  # 기존 모드는 이 테이블이 없는 DB에서도 동작한다
            conn.execute("DELETE FROM agent_state.chat_request_charges WHERE usage_day < "
                         "((now() AT TIME ZONE 'Asia/Seoul')::date - 7)")
    # This commits independently of transcript/checkpoints: failed paid work also counts.
    return _summary(current, personal + 1, total + 1, member)


def read(user_id: str | None, ip: str | None):
    key = subject(user_id, ip)
    try:
        with chat_storage.connection() as conn:
            return status(conn, key, bool(user_id))
    except psycopg.Error:
        raise HTTPException(503, "사용량 확인에 실패했습니다. 잠시 후 다시 시도해 주세요.") from None
