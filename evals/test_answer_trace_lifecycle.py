"""Local-only runtime checks for private trace restoration, transfer and deletion.

Auth identity/provider responses are fixtures. API handlers and PostgreSQL are real.
No model provider or hosted database is used.
"""
import base64
import json
import os
from uuid import uuid4
from unittest.mock import patch

import pytest
import httpx
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from backend.api import accounts, answer_runs, chat_storage
from backend.api import main as api
from backend.shared import answer_trace
from evals.quota_fixture import unrestricted_quota


@pytest.fixture
def local_member():
    config = conninfo_to_dict(os.environ.get('CHAT_DATABASE_URL', ''))
    if config.get('host') != '127.0.0.1' or config.get('port') != '54322':
        pytest.skip('Requires explicit local Supabase on 127.0.0.1:54322')
    chat_storage.setup()
    member = str(uuid4())
    with chat_storage.connection() as conn:
        conn.execute("INSERT INTO auth.users(id,aud,role) VALUES (%s,'authenticated','authenticated')", (member,))
    try:
        yield member
    finally:
        with chat_storage.connection() as conn:
            conn.execute('DELETE FROM auth.users WHERE id=%s', (member,))


def seed_trace(thread, *, member=None, conversation=None, answer_id=None):
    with answer_trace.capture(thread_id=thread, user_id=member, conversation_id=conversation) as state:
        with patch.object(answer_runs, 'versions', return_value={'code_version': 'local-lifecycle-fixture'}):
            state['started_persisted'] = answer_runs.persist_start(state)
            with answer_trace.step('lifecycle_fixture', 'node'):
                pass
            response = {'thread_id': thread, 'status': 'OK', 'answer_id': answer_id or str(uuid4())}
            assert state['started_persisted'] and answer_runs.persist_finish(state, response)
    return state['id']


def assert_removed(run):
    with chat_storage.connection() as conn:
        assert not conn.execute('SELECT 1 FROM public.answer_runs WHERE id=%s', (run,)).fetchone()
        assert not conn.execute('SELECT 1 FROM public.answer_run_steps WHERE run_id=%s', (run,)).fetchone()


def test_member_history_and_duplicate_hide_legacy_execution(local_member):
    member, conversation, request, answer = local_member, str(uuid4()), str(uuid4()), str(uuid4())
    response = {'thread_id': conversation, 'answer_id': answer, 'status': 'OK', 'answer': 'fixture',
                'execution': {'private_marker': 'operator-only'}}
    with chat_storage.connection() as conn:
        conn.execute('INSERT INTO public.conversations(id,user_id,title) VALUES (%s,%s,%s)',
                     (conversation, member, 'local fixture'))
        chat_storage.append_pair(conn, conversation, request, 'fixture', response)
    run = seed_trace(conversation, member=member, conversation=conversation, answer_id=answer)
    client = TestClient(api.app)
    with patch.object(chat_storage, 'identity', return_value=member), unrestricted_quota():
        restored = client.get(f'/api/conversations/{conversation}').json()
        assert 'execution' not in restored['messages'][1]['payload']
        with patch.object(api, '_chat_response', side_effect=AssertionError('Duplicate reran agent')):
            replay = client.post('/api/chat', json={'conversation_id': conversation, 'request_id': request,
                                                   'message': 'fixture'})
        assert replay.status_code == 200 and replay.json()['answer_id'] == answer
        assert 'execution' not in replay.json() and 'operator-only' not in replay.text
        with chat_storage.connection() as conn:
            assert conn.execute('SELECT count(*) AS n FROM public.answer_runs WHERE answer_id=%s',
                                (answer,)).fetchone()['n'] == 1
            # Filtering must not erase stored historical data as a side effect of reading it.
            assert conn.execute("SELECT payload FROM public.messages WHERE conversation_id=%s AND role='assistant'",
                                (conversation,)).fetchone()['payload']['execution']
        assert client.delete(f'/api/conversations/{conversation}').status_code == 204
    assert_removed(run)


def test_guest_transfer_and_guest_delete_include_steps(local_member):
    client = TestClient(api.app)
    secret = 'local-lifecycle-' + 's' * 40
    headers = {'X-Guest-Session': secret}
    threads, runs = [], []
    try:
        with patch.object(chat_storage, 'identity', return_value=None), unrestricted_quota():
            for _ in range(2):
                reply = client.post('/api/chat', headers=headers, json={'message': '안녕하세요'})
                assert reply.status_code == 200
                body = reply.json()
                threads.append(body['thread_id'])
                with chat_storage.connection() as conn:
                    row = conn.execute('SELECT id::text FROM public.answer_runs WHERE answer_id=%s',
                                       (body['answer_id'],)).fetchone()
                    assert row
                    runs.append(row['id'])
        assert client.delete(f'/api/guest/conversations/{threads[0]}',
                             headers={'X-Guest-Session': 'wrong-' + 'x' * 40}).status_code == 404
        with chat_storage.connection() as conn:
            assert conn.execute('SELECT 1 FROM public.answer_runs WHERE id=%s', (runs[0],)).fetchone()
        assert client.delete(f'/api/guest/conversations/{threads[0]}', headers=headers).status_code == 204
        assert_removed(runs[0])
        target = str(uuid4())
        with patch.object(chat_storage, 'identity', return_value=local_member):
            imported = client.post('/api/conversations/import-guest', headers=headers,
                                   json={'thread_id': threads[1], 'conversation_id': target})
            assert imported.status_code == 200
            with chat_storage.connection() as conn:
                row = conn.execute('SELECT user_id::text,conversation_id::text,thread_id FROM public.answer_runs WHERE id=%s',
                                   (runs[1],)).fetchone()
                assert row == {'user_id': local_member, 'conversation_id': target, 'thread_id': target}
                assert conn.execute('SELECT count(*) AS n FROM public.answer_run_steps WHERE run_id=%s',
                                    (runs[1],)).fetchone()['n'] > 0
            assert client.delete(f'/api/conversations/{target}').status_code == 204
        assert_removed(runs[1])
    finally:
        with chat_storage.connection() as conn:
            for run in runs:
                conn.execute('DELETE FROM public.answer_runs WHERE id=%s', (run,))
        for thread in threads:
            api._GUESTS.pop(thread, None)
            api.GRAPH.checkpointer.delete_thread(thread)


def test_account_removal_cascades_owned_and_failed_runs(local_member):
    member, conversation = local_member, str(uuid4())
    original, fresh = str(uuid4()), str(uuid4())
    with chat_storage.connection() as conn:
        conn.execute("INSERT INTO auth.identities(id,user_id,provider_id,provider,identity_data) VALUES (%s,%s,%s,'google',%s)",
                     (uuid4(), member, member, Jsonb({'sub': member})))
        conn.execute("INSERT INTO auth.sessions(id,user_id,created_at) VALUES (%s,%s,now()-interval '1 hour')", (original, member))
        conn.execute('INSERT INTO public.conversations(id,user_id,title) VALUES (%s,%s,%s)',
                     (conversation, member, 'local fixture'))
    run = seed_trace(conversation, member=member, conversation=conversation)
    # A failed member request may have no conversation or answer yet.
    with answer_trace.capture(thread_id=str(uuid4()), user_id=member) as state:
        with patch.object(answer_runs, 'versions', return_value={'code_version': 'local-lifecycle-fixture'}):
            assert answer_runs.persist_finish(state, failed=True)
    failed_run = state['id']

    def authorization(session):
        segment = base64.urlsafe_b64encode(json.dumps({'session_id': session}).encode()).decode().rstrip('=')
        return 'Bearer fixture.' + segment + '.signature'

    def local_auth_delete(method, url, **kwargs):
        assert method == 'DELETE' and url == f'http://127.0.0.1:54321/auth/v1/admin/users/{member}'
        assert kwargs['json'] == {'should_soft_delete': False}
        with chat_storage.connection() as conn:
            conn.execute('DELETE FROM auth.users WHERE id=%s', (member,))
        return httpx.Response(200, request=httpx.Request(method, url), json={})

    with patch.dict(os.environ, {'SUPABASE_URL': 'http://127.0.0.1:54321', 'SUPABASE_SECRET_KEY': 'local-fixture',
                                 'QUOTA_HASH_SECRET': 'local-lifecycle-fixture'}), \
            patch.object(chat_storage, 'require_member', return_value=member), \
            patch.object(chat_storage, 'verified_user', return_value={'id': member}), \
            patch.object(httpx, 'request', side_effect=local_auth_delete):
        challenge = accounts.begin(authorization(original))['challenge_id']
        with chat_storage.connection() as conn:
            conn.execute('INSERT INTO auth.sessions(id,user_id,created_at) VALUES (%s,%s,now())', (fresh, member))
        assert accounts.remove(authorization(fresh), challenge) == {'status': 'deleted'}
    assert_removed(run)
    assert_removed(failed_run)
