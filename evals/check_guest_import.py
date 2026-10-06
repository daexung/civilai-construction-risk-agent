"""Local-only guest-to-member migration and interrupt recovery checks."""
import os
import sys
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

os.environ['AGENT_OFFLINE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from fastapi import HTTPException
from backend.api import chat_storage
import backend.api.main as api
from backend.agent.graph import build_graph
from langgraph.checkpoint.postgres import PostgresSaver
from evals.check_api import PUMP_ANSWERS


def main():
    if '127.0.0.1:54322' not in os.getenv('CHAT_DATABASE_URL', ''):
        raise SystemExit('Local Supabase only')
    chat_storage.setup()
    a, b = str(uuid4()), str(uuid4())
    target, occupied = str(uuid4()), str(uuid4())
    client = TestClient(api.app)
    guest_headers = {'X-Guest-Session': 'import-test-' + 's' * 40}
    auth_headers = {**guest_headers, 'Authorization': 'Bearer A'}
    source = None
    def verified(authorization):
        if authorization is None: return None
        if authorization == 'Bearer A': return a
        if authorization == 'Bearer B': return b
        raise HTTPException(401, 'invalid')
    try:
        with chat_storage.connection() as conn:
            for uid in [a, b]:
                conn.execute("INSERT INTO auth.users(id,aud,role,email) VALUES (%s,'authenticated','authenticated',%s)", (uid, f'import-{uid}@example.invalid'))
            conn.execute('INSERT INTO public.conversations(id,user_id,title) VALUES (%s,%s,%s)', (occupied,b,'other account'))
        with patch.object(chat_storage, 'identity', side_effect=verified):
            first = client.post('/api/chat', headers=guest_headers, json={'message': '철근콘크리트 벽체 100㎥ 펌프차 타설 비용'}).json()
            source = first['thread_id']
            second = client.post('/api/chat', headers=guest_headers, json={'thread_id': source, 'answers': {'work': '6-1-4'}, 'user_label': '펌프차 타설 선택'}).json()
            assert second['status'] == 'MISSING_INFO'
            body = {'thread_id': source, 'conversation_id': target}
            def migrate(headers=auth_headers, payload=body):
                return client.post('/api/conversations/import-guest', headers=headers, json=payload)
            assert migrate(guest_headers).status_code == 401
            assert migrate({'Authorization': 'Bearer A', 'X-Guest-Session': 'wrong' * 10}).status_code == 404
            assert migrate(payload={**body, 'conversation_id': occupied}).status_code == 409
            print('PASS import requires both member login and guest ownership; cannot overwrite')

            with patch.object(chat_storage, 'append_pair', side_effect=RuntimeError('fixture rollback')):
                try: migrate()
                except RuntimeError: pass
                else: raise AssertionError('expected failure')
            with chat_storage.connection() as conn:
                assert not conn.execute('SELECT id FROM public.conversations WHERE id=%s', (target,)).fetchone()
                assert not build_graph(PostgresSaver(conn)).get_state({'configurable': {'thread_id': target}}).values
            assert source in api._GUESTS and api.GRAPH.get_state({'configurable': {'thread_id': source}}).next
            print('PASS failed migration rolls back member rows/checkpoints and preserves guest')

            with patch.object(api, '_chat_response', wraps=api._chat_response) as agent:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    replies = list(executor.map(lambda _: migrate(), range(2)))
                assert all(reply.status_code == 200 and reply.json()['id'] == target for reply in replies), [r.text for r in replies]
                assert agent.call_count == 0
            history = client.get(f'/api/conversations/{target}', headers=auth_headers).json()['messages']
            assert len(history) == 4
            assert history[0]['content'] == '철근콘크리트 벽체 100㎥ 펌프차 타설 비용'
            assert history[2]['content'] == '펌프차 타설 선택'
            assert all(row['payload'].get('thread_id') == target for row in history if row['role'] == 'assistant')
            assert source not in api._GUESTS and not api.GRAPH.get_state({'configurable': {'thread_id': source}}).values
            assert client.post('/api/chat', headers=guest_headers, json={'thread_id': source,'message':'old'}).status_code == 404
            print('PASS transcript and checkpoints copied once without rerunning agent; guest disposed after commit')

            with patch.object(api, 'GRAPH', build_graph()):
                assert migrate().json()['id'] == target
                assert migrate({**guest_headers, 'Authorization': 'Bearer B'}).status_code == 404
                resumed = client.post('/api/chat', headers=auth_headers, json={'thread_id': target, 'conversation_id': target,
                    'request_id': str(uuid4()), 'answers': PUMP_ANSWERS})
                assert resumed.status_code == 200 and resumed.json()['status'] in ('OK','PARTIAL'), resumed.text
                assert next(item for item in resumed.json()['inputs'] if item['name'] == 'volume')['value'] == '100'
                assert client.get(f'/api/export/{target}.xlsx', headers=auth_headers).status_code == 200
            print('PASS durable retry receipt, other-account rejection, interrupt resume and export after restart')
            assert client.delete(f'/api/conversations/{target}', headers=auth_headers).status_code == 204
            with chat_storage.connection() as conn:
                assert not conn.execute('SELECT source_id FROM agent_state.guest_imports WHERE source_id=%s',(source,)).fetchone()
            assert migrate().status_code == 404
            print('PASS hard deletion removes receipt and retry cannot resurrect a conversation')
    finally:
        with chat_storage.connection() as conn:
            for cid in [target, occupied]: PostgresSaver(conn).delete_thread(cid)
            conn.execute('DELETE FROM auth.users WHERE id IN (%s,%s)',(a,b))
        if source:
            api._GUESTS.pop(source,None)
            api.GRAPH.checkpointer.delete_thread(source)
    print('All guest migration checks passed')


if __name__ == '__main__':
    from evals.quota_fixture import unrestricted_quota
    with unrestricted_quota():
        main()
