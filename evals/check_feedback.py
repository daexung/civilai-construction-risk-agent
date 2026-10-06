"""Local-only real PostgreSQL checks. Never runs against hosted user data."""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.api import feedback, chat_storage, usage_limits
from fastapi import HTTPException
from pydantic import ValidationError


def main():
    if '127.0.0.1:54322' not in os.getenv('CHAT_DATABASE_URL', ''):
        raise SystemExit('Set local Supabase CHAT_DATABASE_URL explicitly')
    current = datetime(2099, 10, 8, 12, tzinfo=usage_limits.KST)
    ids = []
    member = str(uuid4())
    def payload(message='feedback fixture', category='bug'):
        item = feedback.FeedbackRequest(request_id=uuid4(), category=category, message=message)
        ids.append(item.request_id)
        return item
    def attempt(item, ip):
        try:
            return feedback.submit(item, None, ip)
        except HTTPException as error:
            return error.status_code
    try:
        with chat_storage.connection() as conn:
            conn.execute("INSERT INTO auth.users(id,aud,role,email) VALUES (%s,'authenticated','authenticated',%s)", (member, f'feedback-{member}@example.invalid'))
        for message in ['   ', '1234', 'x' * 2001, 'hello\x00']:
            try:
                payload(message)
                raise AssertionError('invalid message accepted')
            except ValidationError:
                pass
        try:
            payload(category='invalid')
            raise AssertionError('invalid category accepted')
        except ValidationError:
            pass
        with patch.object(usage_limits, 'now', return_value=current):
            item = payload()
            assert feedback.submit(item, member, None)['id'] == str(item.request_id)
            assert feedback.submit(item, member, None)['id'] == str(item.request_id)
            assert attempt(item, 'other-owner') == 409
            changed = item.model_copy(update={'message': 'changed fixture'})
            try:
                feedback.submit(changed, member, None)
                raise AssertionError('changed duplicate accepted')
            except HTTPException as error:
                assert error.status_code == 409
            with chat_storage.connection() as conn:
                assert conn.execute('SELECT used FROM agent_state.daily_feedback_usage WHERE usage_day=%s AND subject=%s', (current.date(), 'feedback:' + usage_limits.subject(member, None))).fetchone()['used'] == 1
                assert str(conn.execute('SELECT user_id FROM public.feedback WHERE id=%s', (item.request_id,)).fetchone()['user_id']) == member
                for role in ('anon', 'authenticated'):
                    assert not conn.execute("SELECT has_table_privilege(%s,'public.feedback','SELECT') AS allowed", (role,)).fetchone()['allowed']
                    assert not conn.execute("SELECT has_table_privilege(%s,'public.feedback','INSERT') AS allowed", (role,)).fetchone()['allowed']
                assert conn.execute("SELECT relrowsecurity FROM pg_class WHERE oid='public.feedback'::regclass").fetchone()['relrowsecurity']
            assert attempt(payload(), 'guest-fixture') != 429
            assert attempt(payload(), 'guest-fixture') == 429
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda entry: attempt(entry, 'concurrent-fixture'), [payload() for _ in range(4)]))
            assert sum(isinstance(value, dict) for value in results) == 1 and results.count(429) == 3
            with chat_storage.connection() as conn:
                conn.execute("UPDATE agent_state.daily_feedback_usage SET used=99 WHERE usage_day=%s AND subject='service'", (current.date(),))
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(lambda pair: attempt(*pair), [(payload(), f'global-fixture-{index}') for index in range(4)]))
            assert sum(isinstance(value, dict) for value in results) == 1 and results.count(429) == 3
            assert feedback.submit(item, member, None)['id'] == str(item.request_id)
        for index in range(5):
            with patch.object(usage_limits, 'now', return_value=current + timedelta(days=1, minutes=index)):
                assert isinstance(attempt(payload(), 'personal-fixture'), dict)
        with patch.object(usage_limits, 'now', return_value=current + timedelta(days=1, minutes=6)):
            assert attempt(payload(), 'personal-fixture') == 429
        with patch.object(chat_storage, 'connection', side_effect=__import__('psycopg').OperationalError('fixture unavailable')):
            assert attempt(payload(), 'db-down') == 503
        print('PASS validation, member/guest, private permissions, idempotency, ownership, minute/daily limits, atomic global limit and database failure')
    finally:
        with chat_storage.connection() as conn:
            conn.execute('DELETE FROM public.feedback WHERE id=ANY(%s)', (ids,))
            conn.execute('DELETE FROM agent_state.daily_feedback_usage WHERE usage_day IN (%s,%s)', (current.date(), (current + timedelta(days=1)).date()))
            conn.execute('DELETE FROM auth.users WHERE id=%s', (member,))


if __name__ == '__main__':
    main()
