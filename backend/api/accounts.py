"""Google reauthentication and recoverable, private account deletion jobs."""
import base64
import json
import os
from contextlib import contextmanager
from uuid import UUID, uuid4

import httpx
import psycopg
from fastapi import HTTPException
from langgraph.checkpoint.postgres import PostgresSaver
from backend.api import chat_storage, usage_limits


def admin_key():
    key = os.getenv('SUPABASE_SECRET_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')
    if not key:
        raise HTTPException(503, '회원탈퇴 연결을 준비 중입니다. 문의 이메일로 요청해 주세요.')
    return key


def session_id(authorization):
    # Called only after Supabase has verified this exact bearer token via /user.
    try:
        token = authorization.split(' ', 1)[1]
        segment = token.split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4)))
        return str(UUID(claims['session_id']))
    except (ValueError, KeyError, IndexError, TypeError):
        raise HTTPException(401, '로그인을 다시 확인해 주세요.') from None


@contextmanager
def guard(user_id):
    if not user_id:
        yield
        return
    with chat_storage.connection() as conn:
        lock = 'account:' + user_id
        acquired = conn.execute('SELECT pg_try_advisory_lock_shared(hashtextextended(%s,0)) AS ok', (lock,)).fetchone()['ok']
        if not acquired:
            raise HTTPException(409, '계정 변경을 처리 중입니다. 잠시 후 다시 시도해 주세요.')
        try:
            if conn.execute('SELECT 1 FROM agent_state.account_deletions WHERE user_id=%s', (user_id,)).fetchone():
                raise HTTPException(403, '회원탈퇴 처리 중인 계정입니다.')
            yield
        finally:
            conn.execute('SELECT pg_advisory_unlock_shared(hashtextextended(%s,0))', (lock,))


def begin(authorization):
    admin_key()
    user_id = chat_storage.require_member(authorization)
    original = session_id(authorization)
    with guard(user_id), chat_storage.connection() as conn, conn.transaction():
        if not conn.execute("SELECT 1 FROM auth.identities WHERE user_id=%s AND provider='google'", (user_id,)).fetchone():
            raise HTTPException(400, 'Google 계정 확인이 필요합니다.')
        challenge = str(uuid4())
        conn.execute('DELETE FROM agent_state.account_deletion_challenges WHERE expires_at < now()')
        conn.execute('INSERT INTO agent_state.account_deletion_challenges(id,user_id,original_session_id) VALUES (%s,%s,%s) '
                     "ON CONFLICT (user_id) DO UPDATE SET id=EXCLUDED.id,original_session_id=EXCLUDED.original_session_id,created_at=now(),expires_at=now()+interval '10 minutes'",
                     (challenge, user_id, original))
        return {'challenge_id': challenge}


def _finish(conn, job):
    key = admin_key()
    url = os.getenv('SUPABASE_URL', '').rstrip('/')
    try:
        response = httpx.request('DELETE', f"{url}/auth/v1/admin/users/{job['user_id']}",
                                headers={'apikey': key, 'Authorization': f'Bearer {key}'},
                                json={'should_soft_delete': False}, timeout=15)
        if response.status_code != 404:
            response.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(503, '탈퇴 처리를 완료하지 못했습니다. 재시도하거나 문의 이메일로 연락해 주세요.') from None
    if conn.execute('SELECT 1 FROM auth.users WHERE id=%s', (job['user_id'],)).fetchone():
        raise HTTPException(503, '계정 삭제 결과를 확인하지 못했습니다. 문의 이메일로 연락해 주세요.')
    # Auth FK cascades remove profiles, conversations, messages and import receipts.
    with conn.transaction():
        saver = PostgresSaver(conn)
        for conversation_id in job['conversation_ids']:
            saver.delete_thread(str(conversation_id))
            saver.delete_thread(f"dlg:{conversation_id}")  # AGENT_MODE=tools 대화 상태
        conn.execute('DELETE FROM public.feedback WHERE id=ANY(%s)', (job['feedback_ids'],))
        conn.execute('DELETE FROM agent_state.account_deletions WHERE user_id=%s', (job['user_id'],))


def remove(authorization, challenge_id):
    admin_key()
    user = chat_storage.verified_user(authorization)
    if not user:
        raise HTTPException(401, '로그인이 필요합니다.')
    user_id = user['id']
    fresh_session = session_id(authorization)
    with chat_storage.connection() as conn:
        lock = 'account:' + user_id
        if not conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok', (lock,)).fetchone()['ok']:
            raise HTTPException(409, '진행 중인 요청이 있습니다. 완료 후 다시 탈퇴해 주세요.')
        try:
            job = conn.execute('SELECT * FROM agent_state.account_deletions WHERE user_id=%s', (user_id,)).fetchone()
            if not job:
                with conn.transaction():
                    verified = conn.execute('SELECT 1 FROM agent_state.account_deletion_challenges c '
                        'JOIN auth.sessions s ON s.user_id=c.user_id AND s.id=%s '
                        'WHERE c.id=%s AND c.user_id=%s AND c.expires_at>now() '
                        'AND s.id<>c.original_session_id AND s.created_at>=c.created_at',
                        (fresh_session, challenge_id, user_id)).fetchone()
                    if not verified:
                        raise HTTPException(403, '현재 계정으로 Google 로그인을 다시 확인해 주세요.')
                    # Upgrade legacy counters before the provider identity is erased.
                    usage_limits.subject(user_id, None)
                    conversations = conn.execute('SELECT id FROM public.conversations WHERE user_id=%s', (user_id,)).fetchall()
                    opinions = conn.execute('SELECT id FROM public.feedback WHERE user_id=%s', (user_id,)).fetchall()
                    job = conn.execute('INSERT INTO agent_state.account_deletions(user_id,conversation_ids,feedback_ids) VALUES (%s,%s,%s) RETURNING *',
                                       (user_id, [r['id'] for r in conversations], [r['id'] for r in opinions])).fetchone()
            _finish(conn, job)
            return {'status': 'deleted'}
        finally:
            conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (lock,))


def recover():
    try:
        with chat_storage.connection() as conn:
            conn.execute('DELETE FROM agent_state.account_deletion_challenges WHERE expires_at < now()')
            for table in ('daily_chat_usage', 'daily_feedback_usage', 'daily_answer_feedback_usage'):
                conn.execute(f"DELETE FROM agent_state.{table} WHERE usage_day < ((now() AT TIME ZONE 'Asia/Seoul')::date - 7)")
            conn.execute("DELETE FROM public.answer_feedback WHERE created_at < now() - interval '90 days'")
            if not (os.getenv('SUPABASE_SECRET_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')):
                return
            jobs = conn.execute('SELECT * FROM agent_state.account_deletions ORDER BY created_at LIMIT 20').fetchall()
            for job in jobs:
                lock = 'account:' + str(job['user_id'])
                if conn.execute('SELECT pg_try_advisory_lock(hashtextextended(%s,0)) AS ok', (lock,)).fetchone()['ok']:
                    try:
                        _finish(conn, job)
                    except HTTPException:
                        pass
                    finally:
                        conn.execute('SELECT pg_advisory_unlock(hashtextextended(%s,0))', (lock,))
    except (psycopg.Error, HTTPException):
        # Keep the durable job for the next recovery cycle.
        pass
