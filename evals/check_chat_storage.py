"""Local PostgreSQL integration checks; no OAuth account or paid model is used.

CHAT_DATABASE_URL must point to LOCAL Supabase. Fixture rows are removed afterwards.
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ["AGENT_OFFLINE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.api import chat_storage
from backend.api.main import app
import backend.api.main as api
from backend.agent.graph import build_graph
from langgraph.checkpoint.postgres import PostgresSaver


def main():
    if "127.0.0.1:54322" not in os.environ.get("CHAT_DATABASE_URL", ""):
        raise SystemExit("Set CHAT_DATABASE_URL to local Supabase port 54322 only")
    chat_storage.setup()
    a, b = str(uuid4()), str(uuid4())
    ids = [str(uuid4()) for _ in range(5)]
    client = TestClient(app)
    headers = {"Authorization": "Bearer fixture-a"}
    def verified(token):
        if token == "Bearer fixture-a": return a
        if token == "Bearer fixture-b": return b
        if token is None: return None
        from fastapi import HTTPException
        raise HTTPException(401, "invalid")
    try:
        if os.environ.get('SUPABASE_TEST_SERVICE_ROLE_KEY'):
            import httpx
            fixtures = []
            for fixture in [a, b]:
                created = httpx.post(os.environ['SUPABASE_URL'] + '/auth/v1/admin/users',
                                     headers={"apikey": os.environ['SUPABASE_TEST_SERVICE_ROLE_KEY'],
                                              "Authorization": 'Bearer ' + os.environ['SUPABASE_TEST_SERVICE_ROLE_KEY']},
                                     json={"email": f"storage-{fixture}@example.invalid", "email_confirm": True})
                created.raise_for_status()
                fixtures.append(created.json()['id'])
            a, b = fixtures
        else:
            with chat_storage.connection() as conn:
                for user_id in [a, b]:
                    conn.execute("INSERT INTO auth.users(id,aud,role,email) VALUES (%s,'authenticated','authenticated',%s)",
                                 (user_id, f"storage-{user_id}@example.invalid"))
        if os.environ.get('SUPABASE_JWT_SECRET'):
            # Local test token creation only; production verification remains Auth's job.
            import base64, hashlib, hmac, json, time
            def encoded(value):
                return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b'=')
            claims = {"sub": a, "aud": "authenticated", "role": "authenticated", "iat": int(time.time()),
                      "exp": int(time.time()) + 120, "iss": os.environ['SUPABASE_URL'] + '/auth/v1'}
            signing = encoded({"alg": "HS256", "typ": "JWT"}) + b'.' + encoded(claims)
            signature = base64.urlsafe_b64encode(hmac.new(os.environ['SUPABASE_JWT_SECRET'].encode(), signing, hashlib.sha256).digest()).rstrip(b'=')
            import httpx
            fixture_token = (signing + b'.' + signature).decode()
            auth_result = httpx.get(os.environ['SUPABASE_URL'] + '/auth/v1/user',
                                   headers={"apikey": os.environ['SUPABASE_PUBLISHABLE_KEY'], "Authorization": 'Bearer ' + fixture_token})
            if auth_result.status_code != 200:
                print('Local fixture Auth error:', auth_result.json().get('error_code'), auth_result.json().get('msg'))
            assert chat_storage.identity('Bearer ' + fixture_token) == a
            assert client.get('/api/conversations', headers={"Authorization": "Bearer invalid-token"}).status_code == 401
            print('PASS real local Auth verifies signed fixture and rejects invalid JWT')
        with patch.object(chat_storage, "identity", side_effect=verified):
            def send(cid, **extra):
                return client.post('/api/chat', headers=headers,
                                   json={"conversation_id": cid, "request_id": str(uuid4()), **extra})
            first = send(ids[0], message="안녕하세요")
            assert first.status_code == 200, first.text
            assert first.json()["thread_id"] == ids[0]
            assert len(client.get('/api/conversations', headers=headers).json()) == 1
            history = client.get(f'/api/conversations/{ids[0]}', headers=headers)
            assert [m["role"] for m in history.json()["messages"]] == ["user", "assistant"]
            assert history.json()["messages"][1]["payload"]["thread_id"] == ids[0]
            print("PASS member transcript and list")

            for path in ['/api/conversations', f'/api/conversations/{ids[0]}']:
                assert client.get(path).status_code == 401
            for path in [f'/api/conversations/{ids[0]}', f'/api/export/{ids[0]}.xlsx']:
                assert client.get(path, headers={"Authorization": "Bearer fixture-b"}).status_code == 404
            forbidden = client.post('/api/chat', headers={"Authorization": "Bearer fixture-b"},
                                    json={"conversation_id": ids[0], "request_id": str(uuid4()), "message": "steal"})
            assert forbidden.status_code == 404
            assert client.get('/api/conversations', headers={"Authorization": "Bearer fixture-b"}).json() == []
            assert client.get('/api/conversations', headers={"Authorization": "Bearer expired"}).status_code == 401
            print("PASS A/B/guest/invalid authentication isolation")

            body = {"conversation_id": ids[0], "thread_id": ids[0], "request_id": str(uuid4()), "message": "감사합니다"}
            with patch.object(api, '_chat_response', wraps=api._chat_response) as invoke:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    replies = list(executor.map(lambda _: client.post('/api/chat', headers=headers, json=body), range(2)))
                assert all(r.status_code == 200 for r in replies)
                assert invoke.call_count == 1
            assert len(client.get(f'/api/conversations/{ids[0]}', headers=headers).json()["messages"]) == 4
            print("PASS concurrent retry deduplication")

            with patch.object(chat_storage, 'append_pair', side_effect=RuntimeError('fixture failure')):
                try: send(ids[1], message="안녕하세요")
                except RuntimeError: pass
                else: raise AssertionError('expected rollback')
            with chat_storage.connection() as conn:
                assert not conn.execute('SELECT id FROM public.conversations WHERE id=%s', (ids[1],)).fetchone()
                assert not build_graph(PostgresSaver(conn)).get_state({"configurable": {"thread_id": ids[1]}}).values
            print("PASS transcript failure rolls back checkpoint and conversation")

            missing = send(ids[2], message="펌프차 타설 100㎥ 비용")
            assert missing.status_code == 200 and missing.json()["status"] == 'MISSING_INFO', missing.text
            # Every request constructs a fresh graph/connection; replace process-local
            # graph entirely to prove persistent interrupt recovery after restart.
            with patch.object(api, 'GRAPH', build_graph()):
                resumed = send(ids[2], thread_id=ids[2], answers={"work": "6-1-4"})
                assert resumed.status_code == 200 and resumed.json()["thread_id"] == ids[2], resumed.text
                assert resumed.json()["work"]["section_no"] == '6-1-4'
            second = send(ids[3], message="안녕하세요")
            assert second.status_code == 200 and second.json()["status"] == 'OUT_OF_SCOPE'
            with chat_storage.connection() as conn:
                snapshot = build_graph(PostgresSaver(conn)).get_state({"configurable": {"thread_id": ids[2]}})
                assert snapshot.next
            print("PASS persistent interrupt recovery and conversation isolation")
            from evals.check_api import PUMP_ANSWERS
            completed = send(ids[2], thread_id=ids[2], answers={**PUMP_ANSWERS, "structure": "철근"})
            assert completed.status_code == 200 and completed.json()["status"] in ('OK', 'PARTIAL'), completed.text
            with patch.object(api, 'GRAPH', build_graph()):
                export = client.get(f'/api/export/{ids[2]}.xlsx', headers=headers)
                assert export.status_code == 200 and export.content[:2] == b'PK'
                changed = send(ids[2], thread_id=ids[2], conditions={"duration": "7~12개월"})
                assert changed.status_code == 200, changed.text
            print("PASS persistent completed estimate, authorized export and condition changes")

            guest_headers = {"X-Guest-Session": "guest-owner-" + 'g' * 40}
            guest = client.post('/api/chat', headers=guest_headers, json={"message": "안녕하세요"}).json()
            thread = guest['thread_id']
            assert client.post('/api/chat', json={"thread_id": thread, "message": "steal"}).status_code == 404
            assert client.get(f'/api/export/{thread}.xlsx').status_code == 404
            assert client.post('/api/chat', headers=guest_headers, json={"thread_id": thread, "message": "감사합니다"}).status_code == 200
            with chat_storage.connection() as conn:
                assert not conn.execute('SELECT id FROM public.conversations WHERE id=%s', (thread,)).fetchone()
            print("PASS guest capability isolation and no database transcript")
        if os.environ.get('SUPABASE_JWT_SECRET'):
            real_headers = {"Authorization": 'Bearer ' + fixture_token}
            real = client.post('/api/chat', headers=real_headers,
                               json={"conversation_id": ids[4], "request_id": str(uuid4()), "message": "안녕하세요"})
            assert real.status_code == 200, real.text
            assert len(client.get(f'/api/conversations/{ids[4]}', headers=real_headers).json()['messages']) == 2
            print('PASS real Auth token through chat write and transcript read')
        # Production verifier must call configured Auth and never trust token claims.
        with patch.dict(os.environ, {"SUPABASE_URL": "http://127.0.0.1:54321", "SUPABASE_PUBLISHABLE_KEY": "test"}):
            import httpx
            result = httpx.Response(401, request=httpx.Request('GET', 'http://127.0.0.1:54321/auth/v1/user'))
            with patch.object(chat_storage.httpx, 'get', return_value=result):
                assert client.get('/api/conversations', headers=headers).status_code == 401
        print("PASS production verifier rejects invalid Auth token")
    finally:
        with chat_storage.connection() as conn:
            for cid in ids:
                PostgresSaver(conn).delete_thread(cid)
            conn.execute('DELETE FROM auth.users WHERE id IN (%s,%s)', (a,b))
    print('All persistence checks passed')


if __name__ == '__main__': main()
