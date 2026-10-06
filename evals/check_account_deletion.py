"""Local fixture accounts only. Auth HTTP is mocked; no hosted accounts deleted."""
import base64
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.postgres import PostgresSaver
from fastapi import HTTPException
from backend.api import accounts, chat_storage, usage_limits


def main():
    if '127.0.0.1:54322' not in os.getenv('CHAT_DATABASE_URL', ''):
        raise SystemExit('Local Supabase required')
    os.environ['SUPABASE_SECRET_KEY'] = 'local-fixture-secret'
    os.environ['SUPABASE_URL'] = 'http://127.0.0.1:54321'
    members = [str(uuid4()), str(uuid4())]
    provider = 'local-fixture-' + str(uuid4())
    original, fresh = str(uuid4()), str(uuid4())
    conversation, opinion = str(uuid4()), str(uuid4())
    current = datetime(2099, 10, 10, 12, tzinfo=usage_limits.KST)
    keys = []
    def auth(session):
        claims = base64.urlsafe_b64encode(json.dumps({'session_id': session}).encode()).decode().rstrip('=')
        return 'Bearer fixture.' + claims + '.signature'
    def create_member(member):
        with chat_storage.connection() as conn:
            conn.execute("INSERT INTO auth.users(id,aud,role,email) VALUES (%s,'authenticated','authenticated',%s)", (member, f'account-{member}@example.invalid'))
            conn.execute("INSERT INTO auth.identities(id,user_id,provider_id,provider,identity_data) VALUES (%s,%s,%s,'google',%s)", (uuid4(), member, provider, json.dumps({'sub': provider})))
    def admin_delete(method, url, **kwargs):
        assert method == 'DELETE' and kwargs['json']['should_soft_delete'] is False
        target = url.rsplit('/', 1)[1]
        assert target in members
        with chat_storage.connection() as conn:
            conn.execute('DELETE FROM auth.users WHERE id=%s', (target,))
        return httpx.Response(200, request=httpx.Request(method, url), json={})
    try:
        chat_storage.setup()
        create_member(members[0])
        with chat_storage.connection() as conn:
            conn.execute('INSERT INTO auth.sessions(id,user_id,created_at) VALUES (%s,%s,now()-interval \'1 hour\')', (original, members[0]))
            conn.execute('INSERT INTO public.conversations(id,user_id,title) VALUES (%s,%s,%s)', (conversation, members[0], 'fixture'))
            conn.execute("INSERT INTO public.feedback(id,user_id,subject,category,message) VALUES (%s,%s,'fixture','bug','local fixture')", (opinion, members[0]))
            checkpoint = empty_checkpoint()
            saved = PostgresSaver(conn).put({'configurable': {'thread_id': conversation, 'checkpoint_ns': ''}}, checkpoint, {'source': 'input', 'step': -1, 'writes': {}}, {})
            PostgresSaver(conn).put_writes(saved, [('fixture', 'private calculation')], 'fixture-task')
        legacy = 'member:' + hmac.new(os.environ['QUOTA_HASH_SECRET'].encode(), members[0].encode(), hashlib.sha256).hexdigest()
        keys.append(legacy)
        with chat_storage.connection() as conn:
            conn.execute('INSERT INTO agent_state.daily_chat_usage(usage_day,subject,used) VALUES (%s,%s,20)', (current.date(), legacy))
        with patch.object(chat_storage, 'require_member', return_value=members[0]), patch.object(chat_storage, 'verified_user', return_value={'id': members[0]}), patch.object(httpx, 'request', side_effect=admin_delete) as admin:
            challenge = accounts.begin(auth(original))['challenge_id']
            try:
                accounts.remove(auth(original), challenge)
                raise AssertionError('old session accepted')
            except HTTPException as error:
                assert error.status_code == 403
            assert not admin.called
            with chat_storage.connection() as conn:
                conn.execute('INSERT INTO auth.sessions(id,user_id,created_at) VALUES (%s,%s,now())', (fresh, members[0]))
            with accounts.guard(members[0]):
                try:
                    accounts.remove(auth(fresh), challenge)
                    raise AssertionError('active request ignored')
                except HTTPException as error:
                    assert error.status_code == 409
            stable = usage_limits.subject(members[0], None); keys.extend([legacy, stable])
            with patch.object(httpx, 'request', side_effect=httpx.ConnectError('fixture')):
                try:
                    accounts.remove(auth(fresh), challenge)
                    raise AssertionError('network failure reported as success')
                except HTTPException as error:
                    assert error.status_code == 503
            try:
                with accounts.guard(members[0]):
                    raise AssertionError('pending account allowed writes')
            except HTTPException as error:
                assert error.status_code == 403
            accounts.recover()
            assert admin.call_count == 1
        with chat_storage.connection() as conn:
            for table, column, value in [('auth.users','id',members[0]), ('public.conversations','id',conversation), ('public.feedback','id',opinion), ('agent_state.account_deletions','user_id',members[0])]:
                assert not conn.execute(f'SELECT 1 FROM {table} WHERE {column}=%s', (value,)).fetchone()
            for table in ('checkpoints', 'checkpoint_blobs', 'checkpoint_writes'):
                assert not conn.execute(f'SELECT 1 FROM agent_state.{table} WHERE thread_id=%s', (conversation,)).fetchone()
        create_member(members[1])
        with patch.object(usage_limits, 'now', return_value=current):
            assert usage_limits.subject(members[1], None) == stable
            assert usage_limits.read(members[1], None)['remaining'] == 0
            try:
                with usage_limits.processing(members[1], None) as context:
                    usage_limits.consume(context)
                    raise AssertionError('rejoin reset quota')
            except HTTPException as error:
                assert error.status_code == 429
        with chat_storage.connection() as conn:
            for role in ('anon', 'authenticated'):
                assert not conn.execute("SELECT has_schema_privilege(%s,'agent_state','USAGE') AS ok", (role,)).fetchone()['ok']
        print('PASS fresh login proof, active-request lock, failure recovery, data deletion, immediate rejoin preserves 20/20 usage and private storage')
    finally:
        with chat_storage.connection() as conn:
            PostgresSaver(conn).delete_thread(conversation)
            conn.execute('DELETE FROM public.feedback WHERE id=%s', (opinion,))
            conn.execute('DELETE FROM agent_state.account_deletions WHERE user_id=ANY(%s::uuid[])', (members,))
            conn.execute('DELETE FROM auth.users WHERE id=ANY(%s::uuid[])', (members,))
            conn.execute('DELETE FROM agent_state.daily_chat_usage WHERE usage_day=%s AND (subject=ANY(%s) OR subject=\'service\')', (current.date(), keys))


if __name__ == '__main__':
    main()
