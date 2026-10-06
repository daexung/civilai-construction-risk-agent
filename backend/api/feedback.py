"""Private feedback inbox with durable limits and idempotent submissions."""
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.api import chat_storage, usage_limits


class FeedbackRequest(BaseModel):
    request_id: UUID
    category: Literal['bug', 'suggestion', 'other']
    message: str = Field(min_length=5, max_length=2000)

    @field_validator('message')
    @classmethod
    def clean_message(cls, value):
        value = value.strip()
        if len(value) < 5 or '\x00' in value:
            raise ValueError('Please provide 5–2000 characters without null bytes')
        return value


def submit(payload: FeedbackRequest, user_id: str | None, ip: str | None):
    key = 'feedback:' + usage_limits.subject(user_id, ip)
    current = usage_limits.now()
    try:
        with chat_storage.connection() as conn, conn.transaction():
            conn.execute('SELECT pg_advisory_xact_lock(78006104)')
            previous = conn.execute('SELECT subject, category, message FROM public.feedback WHERE id=%s',
                                    (payload.request_id,)).fetchone()
            if previous:
                if (previous['subject'], previous['category'], previous['message']) != (key, payload.category, payload.message):
                    raise HTTPException(409, '접수 요청이 변경되었습니다. 창을 다시 열어 보내 주세요.')
                return {'id': str(payload.request_id), 'status': 'received'}
            conn.execute("INSERT INTO agent_state.daily_feedback_usage(usage_day,subject) VALUES (%s,'service') ON CONFLICT DO NOTHING", (current.date(),))
            total = conn.execute("SELECT used FROM agent_state.daily_feedback_usage WHERE usage_day=%s AND subject='service' FOR UPDATE", (current.date(),)).fetchone()['used']
            row = conn.execute('SELECT used,last_at FROM agent_state.daily_feedback_usage WHERE usage_day=%s AND subject=%s', (current.date(), key)).fetchone()
            if total >= 100 or (row and row['used'] >= 5):
                raise HTTPException(429, {'message': '오늘 피드백 접수 한도에 도달했습니다. 내일 다시 보내 주세요.'}, headers={'Retry-After': '3600'})
            if row and row['last_at'] and (current - row['last_at']).total_seconds() < 60:
                raise HTTPException(429, {'message': '피드백은 1분 간격으로 보낼 수 있습니다. 잠시 후 다시 보내 주세요.'}, headers={'Retry-After': '60'})
            conn.execute('INSERT INTO public.feedback(id,user_id,subject,category,message) VALUES (%s,%s,%s,%s,%s)',
                         (payload.request_id, user_id, key, payload.category, payload.message))
            conn.execute("UPDATE agent_state.daily_feedback_usage SET used=used+1 WHERE usage_day=%s AND subject='service'", (current.date(),))
            conn.execute('INSERT INTO agent_state.daily_feedback_usage(usage_day,subject,used,last_at) VALUES (%s,%s,1,%s) '
                         'ON CONFLICT (usage_day,subject) DO UPDATE SET used=daily_feedback_usage.used+1,last_at=EXCLUDED.last_at', (current.date(), key, current))
            conn.execute("DELETE FROM public.feedback WHERE created_at < now() - interval '90 days'")
            conn.execute("DELETE FROM agent_state.daily_feedback_usage WHERE usage_day < ((now() AT TIME ZONE 'Asia/Seoul')::date - 7)")
            return {'id': str(payload.request_id), 'status': 'received'}
    except psycopg.Error:
        raise HTTPException(503, '피드백을 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.') from None
