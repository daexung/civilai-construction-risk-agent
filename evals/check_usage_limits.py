"""Local PostgreSQL quota/API checks. No paid API calls; fixture days only."""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
os.environ['AGENT_OFFLINE'] = '1'
os.environ['AGENT_LLM'] = 'off'
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.api import main as api, chat_storage, usage_limits as limits


def main():
    if '127.0.0.1:54322' not in os.getenv('CHAT_DATABASE_URL', ''):
        raise SystemExit('Local Supabase required')
    today = datetime(2099, 10, 6, 23, 59, 59, tzinfo=limits.KST)
    member = str(uuid4())
    conversation = str(uuid4())
    client = TestClient(api.app)
    guest_headers = {'X-Guest-Session': 'quota-fixture-' + str(uuid4())}
    member_headers = {'Authorization': 'Bearer fixture'}

    def fake_response(payload, *args, **kwargs):
        return {'thread_id': payload.thread_id or uuid4().hex, 'answer': 'fixture', 'status': 'OUT_OF_SCOPE'}

    def seed(key, used):
        with chat_storage.connection() as conn:
            conn.execute('INSERT INTO agent_state.daily_chat_usage(usage_day,subject,used) VALUES (%s,%s,%s) '
                         'ON CONFLICT (usage_day,subject) DO UPDATE SET used=EXCLUDED.used', (today.date(), key, used))

    try:
        with chat_storage.connection() as conn:
            conn.execute("INSERT INTO auth.users(id,aud,role,email) VALUES (%s,'authenticated','authenticated',%s)",
                         (member, f'quota-{member}@example.invalid'))
        with patch.object(limits, 'now', return_value=today), \
                patch.object(chat_storage, 'identity', side_effect=lambda auth: member if auth else None), \
                patch.object(api, '_chat_response', side_effect=fake_response) as agent:
            assert client.post('/api/chat', json={'message': ''}, headers=guest_headers).status_code == 422
            for _ in range(5):
                assert client.post('/api/chat', json={'message': 'fixture'}, headers=guest_headers).status_code == 200
            blocked = client.post('/api/chat', json={'message': 'fixture'}, headers={**guest_headers, 'X-Forwarded-For': '8.8.8.8', 'X-Guest-Session': 'new-session-' + str(uuid4())})
            assert blocked.status_code == 429 and blocked.json()['detail']['code'] == 'PERSONAL_DAILY_LIMIT'
            assert blocked.json()['detail']['usage']['remaining'] == 0 and agent.call_count == 5
            assert client.get('/api/usage').json()['used'] == 5
            print('PASS guest 5, new-session/header bypass blocked, rejected work never invokes agent')

            body = {'message': 'member fixture', 'conversation_id': conversation, 'request_id': str(uuid4())}
            first = client.post('/api/chat', json=body, headers=member_headers)
            assert first.status_code == 200 and first.json()['usage']['limit'] == 20
            assert client.post('/api/chat', json=body, headers=member_headers).json()['usage']['used'] == 1
            assert agent.call_count == 6
            seed(limits.subject(member, None), 19)
            body['request_id'] = str(uuid4())
            assert client.post('/api/chat', json=body, headers=member_headers).json()['usage']['remaining'] == 0
            body['request_id'] = str(uuid4())
            assert client.post('/api/chat', json=body, headers=member_headers).status_code == 429
            assert client.get('/api/usage', headers=member_headers).json()['used'] == 20
            print('PASS member 20, guest/member isolation, committed duplicate not charged')

            with patch.object(limits, 'now', return_value=today + timedelta(seconds=1)):
                fresh = client.get('/api/usage', headers=member_headers).json()
                assert fresh['used'] == 0 and fresh['remaining'] == 20 and fresh['service_remaining'] == 500
            assert datetime.fromisoformat(first.json()['usage']['resets_at']).hour == 0
            print('PASS KST midnight resets both personal and global counters')

            seed('service', 499)
            def reserve(index):
                try:
                    with limits.processing(str(uuid4()), None) as context:
                        return limits.consume(context)['service_remaining']
                except HTTPException as error:
                    return error.status_code
            with ThreadPoolExecutor(max_workers=8) as pool:
                outcomes = list(pool.map(reserve, range(8)))
            assert outcomes.count(0) == 1 and outcomes.count(429) == 7
            with limits.processing(member, None):
                try:
                    with limits.processing(member, None):
                        raise AssertionError('parallel request accepted')
                except HTTPException as error:
                    assert error.status_code == 429 and error.detail['code'] == 'REQUEST_IN_PROGRESS'
            with limits.processing(member, None):
                pass
            print('PASS atomic global 500 across connections; per-identity concurrent request rejected and lock released')

            with chat_storage.connection() as conn:
                assert limits.status(conn, limits.subject(member, None), True)['service_remaining'] == 0
            print('PASS usage survives separate DB connections; no server-memory counter')

            seed('service', 0)
            failing_user = str(uuid4())
            try:
                with limits.processing(failing_user, None) as context:
                    limits.consume(context)
                    raise RuntimeError('simulated provider failure')
            except RuntimeError:
                pass
            assert limits.read(failing_user, None)['used'] == 1
            print('PASS reservation persists after failure, preventing free repeated paid work')
    finally:
        with chat_storage.connection() as conn:
            conn.execute('DELETE FROM auth.users WHERE id=%s', (member,))
            conn.execute('DELETE FROM agent_state.daily_chat_usage WHERE usage_day IN (%s,%s)',
                         (today.date(), today.date() + timedelta(days=1)))
        for thread_id in list(api._GUESTS):
            api.GRAPH.checkpointer.delete_thread(thread_id)
        api._GUESTS.clear()
    print('All quota checks passed')


if __name__ == '__main__':
    main()
