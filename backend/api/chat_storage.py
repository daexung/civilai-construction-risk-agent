"""Verified identity and transactional member transcripts/checkpoints."""
from __future__ import annotations

import os
from contextlib import contextmanager
from uuid import UUID

import httpx
import psycopg
from fastapi import HTTPException
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def identity(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 16384:
        raise HTTPException(401, "로그인이 만료되었습니다. 다시 로그인해 주세요.")
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_PUBLISHABLE_KEY")
    if not url or not key:
        raise HTTPException(503, "로그인 검증 설정이 준비되지 않았습니다.")
    try:
        result = httpx.get(f"{url.rstrip('/')}/auth/v1/user", headers={"apikey": key,
                           "Authorization": f"Bearer {token}"}, timeout=10)
        if result.status_code in (400, 401, 403):
            raise HTTPException(401, "로그인이 만료되었습니다. 다시 로그인해 주세요.")
        result.raise_for_status()
        user = result.json()
        if user.get("is_anonymous") or user.get("role") != "authenticated":
            raise HTTPException(401, "회원 로그인이 필요합니다.")
        return str(UUID(user["id"]))
    except (httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(503, "로그인 확인에 실패했습니다. 잠시 후 다시 시도해 주세요.") from None


def require_member(authorization: str | None) -> str:
    user_id = identity(authorization)
    if not user_id:
        raise HTTPException(401, "로그인이 필요합니다.")
    return user_id


@contextmanager
def connection():
    dsn = os.getenv("CHAT_DATABASE_URL")
    if not dsn:
        raise HTTPException(503, "대화 저장소가 준비되지 않았습니다.")
    # Never interpolate a user-controlled identifier into SQL or DSN options.
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row,
                         options="-c search_path=agent_state", connect_timeout=10) as conn:
        yield conn


def setup():
    if not os.getenv("CHAT_DATABASE_URL"):
        return
    with connection() as conn:
        conn.execute("SELECT pg_advisory_lock(78006100)")
        try:
            PostgresSaver(conn).setup()
            conn.execute("REVOKE ALL ON ALL TABLES IN SCHEMA agent_state FROM public, anon, authenticated")
        finally:
            conn.execute("SELECT pg_advisory_unlock(78006100)")


def owned(conn, conversation_id: str, user_id: str):
    row = conn.execute("SELECT id, title FROM public.conversations WHERE id=%s AND user_id=%s",
                       (conversation_id, user_id)).fetchone()
    if not row:
        raise HTTPException(404, "대화를 찾을 수 없습니다.")
    return row


def list_conversations(user_id: str) -> list[dict]:
    with connection() as conn:
        return conn.execute("SELECT id::text, title, updated_at FROM public.conversations "
                            "WHERE user_id=%s ORDER BY updated_at DESC, id LIMIT 200", (user_id,)).fetchall()


def read_conversation(conversation_id: str, user_id: str) -> dict:
    with connection() as conn, conn.transaction():
        row = owned(conn, conversation_id, user_id)
        messages = conn.execute("SELECT id::text, role, content, payload, created_at FROM public.messages "
                                "WHERE conversation_id=%s ORDER BY sequence", (conversation_id,)).fetchall()
        return {"id": conversation_id, "title": row["title"], "messages": messages}


def append_pair(conn, conversation_id: str, request_id: str, label: str, response: dict):
    sequence = conn.execute("SELECT COALESCE(MAX(sequence),0) AS n FROM public.messages "
                            "WHERE conversation_id=%s", (conversation_id,)).fetchone()["n"]
    for offset, role, content, payload in [(1, "user", label, {}),
                                          (2, "assistant", response.get("answer") or response.get("message") or "", response)]:
        conn.execute("INSERT INTO public.messages(conversation_id, sequence, request_id, role, content, payload) "
                     "VALUES (%s,%s,%s,%s,%s,%s)",
                     (conversation_id, sequence + offset, request_id, role, content, Jsonb(payload)))
    conn.execute("UPDATE public.conversations SET updated_at=now() WHERE id=%s", (conversation_id,))
