"""Answer ratings accept only server-resolved questions and answers."""
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

from backend.api import chat_storage, usage_limits


class RatingRequest(BaseModel):
    thread_id: str = Field(pattern=r'^(?:[a-f0-9]{32}|[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$')
    answer_id: UUID
    rating: Literal['good', 'bad']
    reason: Literal['amount', 'evidence', 'understanding', 'other'] | None = None
    comment: str = Field(default='', max_length=1000)

    @model_validator(mode='after')
    def validate_details(self):
        self.comment = self.comment.strip()
        if '\x00' in self.comment or (self.rating == 'bad' and not self.reason):
            raise ValueError('A reason is required for negative feedback')
        if self.rating == 'good' and (self.reason or self.comment):
            raise ValueError('Positive feedback has no reason or comment')
        return self


def member_target(conn, payload, user_id):
    chat_storage.owned(conn, payload.thread_id, user_id)
    row = conn.execute("SELECT m.sequence,m.payload FROM public.messages m WHERE m.conversation_id=%s "
                       "AND m.role='assistant' AND (m.payload->>'answer_id'=%s OR (NOT m.payload ? 'answer_id' AND m.id=%s))",
                       (payload.thread_id, str(payload.answer_id), payload.answer_id)).fetchone()
    if not row:
        raise HTTPException(404, '평가할 답변을 찾을 수 없습니다.')
    question = conn.execute("SELECT content FROM public.messages WHERE conversation_id=%s AND sequence=%s AND role='user'",
                            (payload.thread_id, row['sequence'] - 1)).fetchone()
    return (question['content'] if question else ''), row['payload']


def submit(conn, payload, user_id, quota_subject, question, response):
    current = usage_limits.now()
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(78006106)')
        previous = conn.execute('SELECT rating,reason,comment FROM public.answer_feedback WHERE answer_id=%s',
                                (payload.answer_id,)).fetchone()
        if previous and (previous['rating'], previous['reason'], previous['comment']) == (payload.rating, payload.reason, payload.comment):
            return {'rating': payload.rating, 'status': 'received'}
        for subject, limit in [('service', 2000), (quota_subject, 40 if user_id else 10)]:
            conn.execute('INSERT INTO agent_state.daily_answer_feedback_usage(usage_day,subject) VALUES (%s,%s) ON CONFLICT DO NOTHING',
                         (current.date(), subject))
            used = conn.execute('SELECT used FROM agent_state.daily_answer_feedback_usage WHERE usage_day=%s AND subject=%s',
                                (current.date(), subject)).fetchone()['used']
            if used >= limit:
                raise HTTPException(429, {'message': '오늘 답변 평가 한도에 도달했습니다. 내일 다시 보내 주세요.'})
        qa = response.get('qa') or {}
        answer = response.get('answer') or '\n'.join(filter(None, [qa.get('conclusion'), qa.get('explanation')])) or response.get('message') or ''
        conn.execute('INSERT INTO public.answer_feedback(answer_id,user_id,conversation_id,thread_id,rating,reason,comment,question,answer,answer_status) '
                     'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(answer_id) DO UPDATE '
                     'SET rating=EXCLUDED.rating,reason=EXCLUDED.reason,comment=EXCLUDED.comment,updated_at=now()',
                     (payload.answer_id, user_id, payload.thread_id if user_id else None, payload.thread_id,
                      payload.rating, payload.reason, payload.comment, question[:10000], answer[:20000], response['status']))
        conn.execute('UPDATE agent_state.daily_answer_feedback_usage SET used=used+1 WHERE usage_day=%s AND subject IN (%s,%s)',
                     (current.date(), 'service', quota_subject))
        return {'rating': payload.rating, 'status': 'received'}


def unavailable():
    return HTTPException(503, '답변 평가를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
