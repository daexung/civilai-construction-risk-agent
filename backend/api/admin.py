"""Read-only owner dashboard API. Identity is verified by Supabase, then allowlisted server-side."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import os
from uuid import UUID

import psycopg
from fastapi import APIRouter, Header, HTTPException, Query

from backend.api import chat_storage

router = APIRouter(prefix="/api/admin", tags=["admin"])
KST = timezone(timedelta(hours=9))
PAGE_SIZE = 50
MAX_PAGE = 10000


def _admin_user(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(401, "로그인이 필요합니다.")
    user_id = chat_storage.identity(authorization)
    raw = os.getenv("ADMIN_USER_IDS", "").strip()
    if not raw:
        raise HTTPException(403, "운영자 접근이 설정되지 않았습니다.")
    try:
        parts = [part.strip() for part in raw.split(",")]
        if any(not part for part in parts):
            raise ValueError("empty allowlist entry")
        allowed = {str(UUID(part)) for part in parts}
        if not allowed or len(allowed) != len(parts):
            raise ValueError("invalid allowlist")
    except (ValueError, TypeError):
        raise HTTPException(503, "운영자 접근 설정을 확인할 수 없습니다.") from None
    if user_id not in allowed:
        raise HTTPException(403, "운영자 권한이 없습니다.")
    return user_id


def _window(period: str) -> tuple[datetime, datetime, datetime]:
    now = datetime.now(KST)
    today = datetime.combine(now.date(), time.min, KST)
    days = {"today": 1, "7d": 7, "30d": 30}[period]
    return today - timedelta(days=days - 1), now, today


def _run_detail(conn, run_id: UUID):
    run = conn.execute(
        "SELECT id,answer_id,request_id,conversation_id,thread_id,environment,agent_mode,started_at,finished_at,status,answer_status,versions,capture_status,expires_at "
        "FROM public.answer_runs WHERE id=%s", (run_id,)).fetchone()
    if not run:
        raise HTTPException(404, "실행 기록을 찾을 수 없습니다.")
    run["steps"] = conn.execute(
        "SELECT id,parent_step_id,step_kind,name,sequence,started_at,finished_at,duration_ms,status,input_summary,output_summary,error_code,error_type,metadata "
        "FROM public.answer_run_steps WHERE run_id=%s ORDER BY sequence", (run_id,)).fetchall()
    run["feedback"] = conn.execute(
        "SELECT answer_id,rating,reason,review_status,error_type,review_note,expected_evidence,reviewed_at "
        "FROM public.answer_feedback WHERE run_id=%s ORDER BY created_at", (run_id,)).fetchall()
    return run


@router.get("/summary")
def summary(period: str = Query("7d", pattern="^(today|7d|30d)$"), authorization: str | None = Header(default=None)):
    _admin_user(authorization)
    start, end, today = _window(period)
    try:
        with chat_storage.connection() as conn:
            accounts = conn.execute(
                "SELECT count(*) FILTER (WHERE NOT is_anonymous) AS current, "
                "count(*) FILTER (WHERE NOT is_anonymous AND created_at >= %s AND created_at < %s) AS new "
                "FROM auth.users", (start, end)).fetchone()
            runs = conn.execute(
                "SELECT count(*) FILTER (WHERE status='completed') AS completed, "
                "count(*) FILTER (WHERE status='failed') AS failed, "
                "count(*) FILTER (WHERE status='running') AS running, "
                "count(*) FILTER (WHERE status='incomplete') AS incomplete, count(*) AS total "
                "FROM public.answer_runs WHERE environment='production' AND started_at >= %s AND started_at < %s",
                (start, end)).fetchone()
            latency = conn.execute(
                "SELECT count(*) AS sample_count, percentile_cont(0.5) WITHIN GROUP (ORDER BY s.duration_ms) AS p50_ms, "
                "percentile_cont(0.95) WITHIN GROUP (ORDER BY s.duration_ms) AS p95_ms "
                "FROM public.answer_runs r JOIN public.answer_run_steps s ON s.run_id=r.id AND s.step_kind='answer' AND s.name='answer_summary' "
                "WHERE r.environment='production' AND r.status='completed' AND r.started_at >= %s AND r.started_at < %s AND s.duration_ms IS NOT NULL",
                (start, end)).fetchone()
            ratings = conn.execute(
                "SELECT count(*) FILTER (WHERE rating='good') AS positive, count(*) FILTER (WHERE rating='bad') AS negative, "
                "count(*) FILTER (WHERE review_status <> 'resolved') AS pending, count(*) AS total "
                "FROM public.answer_feedback WHERE created_at >= %s AND created_at < %s", (start, end)).fetchone()
            opinions = conn.execute("SELECT count(*) AS total FROM public.feedback WHERE created_at >= %s AND created_at < %s",
                                    (start, end)).fetchone()
            trend = conn.execute(
                "SELECT (started_at AT TIME ZONE 'Asia/Seoul')::date AS day, "
                "count(*) AS total, count(*) FILTER (WHERE status='completed') AS completed, count(*) FILTER (WHERE status='failed') AS failed "
                "FROM public.answer_runs WHERE environment='production' AND started_at >= %s AND started_at < %s "
                "GROUP BY day ORDER BY day", (start, end)).fetchall()
            failures = conn.execute(
                "SELECT id,answer_id,agent_mode,started_at,finished_at,status,answer_status,capture_status "
                "FROM public.answer_runs WHERE environment='production' AND status='failed' AND started_at >= %s AND started_at < %s "
                "ORDER BY started_at DESC,id DESC LIMIT 10", (start, end)).fetchall()
        return {"period": period, "timezone": "Asia/Seoul", "as_of": end, "start": start,
                "accounts": accounts, "runs": runs, "latency": latency, "feedback": ratings,
                "general_feedback": opinions, "trend": trend, "recent_failures": failures,
                "unavailable": {"visits": "PostHog 서버 조회 미연결"}}
    except HTTPException:
        raise
    except psycopg.Error:
        raise HTTPException(503, "대시보드 자료를 조회할 수 없습니다.") from None


@router.get("/answer-feedback")
def answer_feedback_list(period: str = Query("30d", pattern="^(today|7d|30d)$"), rating: str | None = Query(None, pattern="^(good|bad)$"),
                        reason: str | None = Query(None, pattern="^(amount|evidence|understanding|other)$"),
                        review_status: str | None = Query(None, pattern="^(new|reviewed|resolved)$"),
                        page: int = Query(1, ge=1, le=MAX_PAGE), authorization: str | None = Header(default=None)):
    _admin_user(authorization)
    start, end, _ = _window(period)
    clauses, args = ["created_at >= %s", "created_at < %s"], [start, end]
    for field, value in (("rating", rating), ("reason", reason), ("review_status", review_status)):
        if value:
            clauses.append(f"{field}=%s"); args.append(value)
    where = " AND ".join(clauses)
    try:
        with chat_storage.connection() as conn:
            total = conn.execute(f"SELECT count(*) AS n FROM public.answer_feedback WHERE {where}", args).fetchone()["n"]
            rows = conn.execute(
                f"SELECT answer_id,rating,reason,review_status,error_type,created_at,updated_at,run_id FROM public.answer_feedback WHERE {where} "
                "ORDER BY created_at DESC,answer_id DESC LIMIT %s OFFSET %s", [*args, PAGE_SIZE, (page-1)*PAGE_SIZE]).fetchall()
        return {"items": rows, "page": page, "page_size": PAGE_SIZE, "total": total}
    except psycopg.Error:
        raise HTTPException(503, "평가 자료를 조회할 수 없습니다.") from None


@router.get("/answer-feedback/{answer_id}")
def answer_feedback_detail(answer_id: UUID, authorization: str | None = Header(default=None)):
    _admin_user(authorization)
    try:
        with chat_storage.connection() as conn:
            row = conn.execute(
                "SELECT answer_id,rating,reason,comment,question,answer,answer_status,review_status,error_type,review_note,expected_evidence,reviewed_by,reviewed_at,eval_question,expected_result,eval_approved_by,eval_approved_at,created_at,run_id "
                "FROM public.answer_feedback WHERE answer_id=%s", (answer_id,)).fetchone()
            if not row:
                raise HTTPException(404, "평가를 찾을 수 없습니다.")
            row["run"] = _run_detail(conn, row["run_id"]) if row["run_id"] else None
            return row
    except HTTPException:
        raise
    except psycopg.Error:
        raise HTTPException(503, "평가 자료를 조회할 수 없습니다.") from None


@router.get("/feedback")
def feedback_list(period: str = Query("30d", pattern="^(today|7d|30d)$"), category: str | None = Query(None, pattern="^(bug|suggestion|other)$"),
                 status: str | None = Query(None, pattern="^(new|reviewed|resolved)$"), page: int = Query(1, ge=1, le=MAX_PAGE),
                 authorization: str | None = Header(default=None)):
    _admin_user(authorization)
    start, end, _ = _window(period)
    clauses, args = ["created_at >= %s", "created_at < %s"], [start, end]
    for field, value in (("category", category), ("status", status)):
        if value:
            clauses.append(f"{field}=%s"); args.append(value)
    where = " AND ".join(clauses)
    try:
        with chat_storage.connection() as conn:
            total = conn.execute(f"SELECT count(*) AS n FROM public.feedback WHERE {where}", args).fetchone()["n"]
            items = conn.execute(f"SELECT id,category,status,created_at FROM public.feedback WHERE {where} ORDER BY created_at DESC,id DESC LIMIT %s OFFSET %s",
                                 [*args, PAGE_SIZE, (page-1)*PAGE_SIZE]).fetchall()
        return {"items": items, "page": page, "page_size": PAGE_SIZE, "total": total}
    except psycopg.Error:
        raise HTTPException(503, "일반 의견을 조회할 수 없습니다.") from None


@router.get("/feedback/{feedback_id}")
def feedback_detail(feedback_id: UUID, authorization: str | None = Header(default=None)):
    _admin_user(authorization)
    try:
        with chat_storage.connection() as conn:
            row = conn.execute("SELECT id,category,status,message,created_at FROM public.feedback WHERE id=%s", (feedback_id,)).fetchone()
            if not row:
                raise HTTPException(404, "일반 의견을 찾을 수 없습니다.")
            return row
    except HTTPException:
        raise
    except psycopg.Error:
        raise HTTPException(503, "일반 의견을 조회할 수 없습니다.") from None


@router.get("/runs")
def runs_list(period: str = Query("30d", pattern="^(today|7d|30d)$"), status: str | None = Query(None, pattern="^(running|completed|failed|incomplete)$"),
              agent_mode: str | None = Query(None, max_length=50), page: int = Query(1, ge=1, le=MAX_PAGE),
              authorization: str | None = Header(default=None)):
    _admin_user(authorization)
    start, end, _ = _window(period)
    clauses, args = ["environment='production'", "started_at >= %s", "started_at < %s"], [start, end]
    if status: clauses.append("status=%s"); args.append(status)
    if agent_mode: clauses.append("agent_mode=%s"); args.append(agent_mode)
    where = " AND ".join(clauses)
    try:
        with chat_storage.connection() as conn:
            total = conn.execute(f"SELECT count(*) AS n FROM public.answer_runs WHERE {where}", args).fetchone()["n"]
            items = conn.execute(f"SELECT id,answer_id,agent_mode,started_at,finished_at,status,answer_status,capture_status FROM public.answer_runs WHERE {where} ORDER BY started_at DESC,id DESC LIMIT %s OFFSET %s",
                                 [*args, PAGE_SIZE, (page-1)*PAGE_SIZE]).fetchall()
        return {"items": items, "page": page, "page_size": PAGE_SIZE, "total": total}
    except psycopg.Error:
        raise HTTPException(503, "실행 자료를 조회할 수 없습니다.") from None


@router.get("/runs/{run_id}")
def run_detail(run_id: UUID, authorization: str | None = Header(default=None)):
    _admin_user(authorization)
    try:
        with chat_storage.connection() as conn:
            return _run_detail(conn, run_id)
    except HTTPException:
        raise
    except psycopg.Error:
        raise HTTPException(503, "실행 자료를 조회할 수 없습니다.") from None
