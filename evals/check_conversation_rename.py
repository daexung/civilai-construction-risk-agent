"""Verify rename persistence and ownership in local Supabase without model calls."""
import os
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

if '127.0.0.1:54322' not in os.environ.get('CHAT_DATABASE_URL', ''):
    raise SystemExit('Use local Supabase port 54322 only')
os.environ['AGENT_OFFLINE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from backend.api import chat_storage
from backend.api.main import app

a, b, conversation_id = str(uuid4()), str(uuid4()), str(uuid4())
client = TestClient(app)
try:
    with chat_storage.connection() as conn:
        for user_id in [a, b]:
            conn.execute("INSERT INTO auth.users(id,aud,role,email) VALUES (%s,'authenticated','authenticated',%s)",
                         (user_id, f'rename-{user_id}@example.invalid'))
        conn.execute('INSERT INTO public.conversations(id,user_id,title) VALUES (%s,%s,%s)', (conversation_id, a, '기존 이름'))
    with patch.object(chat_storage, 'identity', side_effect=lambda token: a if token == 'Bearer a' else b if token == 'Bearer b' else None):
        path = f'/api/conversations/{conversation_id}'
        assert client.patch(path, json={'title': '침입'}).status_code == 401
        assert client.patch(path, headers={'Authorization': 'Bearer b'}, json={'title': '침입'}).status_code == 404
        for title in ['', '   ', 'a' * 201, 'bad\x00title', 'bad\ntitle']:
            assert client.patch(path, headers={'Authorization': 'Bearer a'}, json={'title': title}).status_code == 422
        result = client.patch(path, headers={'Authorization': 'Bearer a'}, json={'title': '  현장 A   견적  '})
        assert result.status_code == 200, result.text
        assert result.json()['title'] == '현장 A 견적'
        assert client.get(path, headers={'Authorization': 'Bearer a'}).json()['title'] == '현장 A 견적'
        assert client.get('/api/conversations', headers={'Authorization': 'Bearer a'}).json()[0]['title'] == '현장 A 견적'
    print('PASS rename ownership, validation and database persistence; no model requests')
finally:
    with chat_storage.connection() as conn:
        conn.execute('DELETE FROM auth.users WHERE id IN (%s,%s)', (a, b))
