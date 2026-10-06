"""Local-only DB/API checks. No agent/LLM or real user accounts are used."""
import os
os.environ.setdefault('AGENT_OFFLINE', '1')
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from time import monotonic
import threading
from uuid import uuid4
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from backend.api import main, chat_storage, usage_limits


def run():
    target = urlsplit(os.environ.get('CHAT_DATABASE_URL', ''))
    assert target.hostname in ('localhost', '127.0.0.1') and target.port == 54322, 'Local Supabase only'
    users = [str(uuid4()), str(uuid4())]
    conversation, answer_id, request_id = [str(uuid4()) for _ in range(3)]
    guest_thread, guest_answer = uuid4().hex, str(uuid4())
    secret = uuid4().hex + uuid4().hex
    response = {'answer_id': answer_id, 'status': 'ANSWERED', 'answer': '검증용 답변', 'thread_id': conversation}
    day = datetime(2095, 10, 6, tzinfo=timezone.utc)
    client = TestClient(main.app)
    payload = {'thread_id': conversation, 'answer_id': answer_id, 'rating': 'bad', 'reason': 'evidence', 'comment': '검증용 의견'}
    try:
        with chat_storage.connection() as conn:
            for user in users:
                conn.execute("INSERT INTO auth.users(id,aud,role) VALUES (%s,'authenticated','authenticated')", (user,))
            conn.execute('INSERT INTO public.conversations(id,user_id,title) VALUES (%s,%s,%s)', (conversation, users[0], '평가 검증'))
            chat_storage.append_pair(conn, conversation, request_id, '검증용 질문', response)
        with patch.object(chat_storage, 'identity', return_value=users[0]), patch.object(usage_limits, 'now', return_value=day):
            assert client.post('/api/answer-feedback', json=payload).status_code == 200
            assert client.post('/api/answer-feedback', json=payload).status_code == 200
            restored = chat_storage.read_conversation(conversation, users[0])['messages'][1]['payload']
            assert restored['answer_rating']['rating'] == 'bad'
            with chat_storage.connection() as conn:
                row = conn.execute('SELECT question,answer FROM public.answer_feedback WHERE answer_id=%s', (answer_id,)).fetchone()
                assert row == {'question': '검증용 질문', 'answer': '검증용 답변'}
                subject = usage_limits.subject(users[0], None)
                assert conn.execute('SELECT used FROM agent_state.daily_answer_feedback_usage WHERE usage_day=%s AND subject=%s', (day.date(), subject)).fetchone()['used'] == 1
                assert not conn.execute('SELECT 1 FROM agent_state.daily_chat_usage WHERE usage_day=%s AND subject=%s', (day.date(), subject)).fetchone()
                for role in ('anon', 'authenticated'):
                    assert not conn.execute("SELECT has_table_privilege(%s,'public.answer_feedback','SELECT') AS ok", (role,)).fetchone()['ok']
                    assert not conn.execute("SELECT has_table_privilege(%s,'public.answer_feedback','INSERT') AS ok", (role,)).fetchone()['ok']
            assert client.post('/api/answer-feedback', json={**payload, 'rating': 'good', 'reason': None, 'comment': ''}).status_code == 200
            assert client.post('/api/answer-feedback', json={**payload, 'answer_id': str(uuid4())}).status_code == 404
            assert client.post('/api/answer-feedback', json={**payload, 'reason': None}).status_code == 422
        with patch.object(chat_storage, 'identity', return_value=users[1]):
            assert client.post('/api/answer-feedback', json=payload).status_code == 404
        main._GUESTS[guest_thread] = {'secret': secret, 'used': monotonic(), 'lock': threading.Lock(),
                                   'turns': [('비회원 검증 질문', {**response, 'answer_id': guest_answer, 'thread_id': guest_thread})]}
        guest_payload = {'thread_id': guest_thread, 'answer_id': guest_answer, 'rating': 'good'}
        with patch.object(chat_storage, 'identity', return_value=None), patch.object(usage_limits, 'now', return_value=day):
            assert client.post('/api/answer-feedback', json=guest_payload).status_code == 404
            assert client.post('/api/answer-feedback', json=guest_payload, headers={'X-Guest-Session': 'wrong-secret'}).status_code == 404
            assert client.post('/api/answer-feedback', json=guest_payload, headers={'X-Guest-Session': secret}).status_code == 200
            with chat_storage.connection() as conn:
                conn.execute("UPDATE agent_state.daily_answer_feedback_usage SET used=2000 WHERE usage_day=%s AND subject='service'", (day.date(),))
            assert client.post('/api/answer-feedback', json={**guest_payload, 'rating': 'bad', 'reason': 'other'}, headers={'X-Guest-Session': secret}).status_code == 429
            assert client.post('/api/answer-feedback', json=guest_payload, headers={'X-Guest-Session': secret}).status_code == 200
            with patch.object(chat_storage, 'connection', side_effect=__import__('psycopg').OperationalError('fixture')):
                assert client.post('/api/answer-feedback', json=guest_payload, headers={'X-Guest-Session': secret}).status_code == 503
        with chat_storage.connection() as conn:
            conn.execute('DELETE FROM public.conversations WHERE id=%s', (conversation,))
            assert not conn.execute('SELECT 1 FROM public.answer_feedback WHERE answer_id=%s', (answer_id,)).fetchone()
        print('PASS: verified member/guest ownership, validation, retry deduplication, edit, restored rating, quotas, RLS, DB failure and deletion cascade; no AI calls')
    finally:
        main._GUESTS.pop(guest_thread, None)
        with chat_storage.connection() as conn:
            conn.execute('DELETE FROM public.answer_feedback WHERE answer_id IN (%s,%s)', (answer_id, guest_answer))
            conn.execute('DELETE FROM auth.users WHERE id=ANY(%s::uuid[])', (users,))
            conn.execute('DELETE FROM agent_state.daily_answer_feedback_usage WHERE usage_day=%s', (day.date(),))


if __name__ == '__main__':
    run()
