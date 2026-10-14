"""Apply additive answer-run migrations in order; never reset or rewrite data."""
import argparse
import json
import os
from pathlib import Path
import sys

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    ('20261014000100', ROOT / 'supabase/migrations/20261014000100_answer_runs.sql'),
    ('20261014000200', ROOT / 'supabase/migrations/20261014000200_answer_run_steps.sql'),
]


def _columns(conn, table):
    return {row[0] for row in conn.execute('SELECT column_name FROM information_schema.columns '
                                           'WHERE table_schema=%s AND table_name=%s', ('public', table))}


def _is_applied(conn, version):
    if version == '20261014000100':
        runs = _columns(conn, 'answer_runs')
        feedback = _columns(conn, 'answer_feedback')
        if not runs:
            return False
        required = {'run_id', 'review_status', 'error_type', 'review_note', 'expected_evidence', 'reviewed_at'}
        if not required <= feedback:
            raise RuntimeError('Initial migration has partial state; no changes applied')
        return True
    if version == '20261014000200':
        runs, steps, feedback = (_columns(conn, table) for table in ('answer_runs', 'answer_run_steps', 'answer_feedback'))
        if not runs:
            if steps:
                raise RuntimeError('Trace schema has partial state; no changes applied')
            return False  # A fresh database needs both migrations, in MIGRATIONS order.
        if not steps:
            return False
        required = {'id', 'request_id', 'environment', 'agent_mode', 'started_at', 'finished_at',
                    'status', 'versions', 'capture_status', 'expires_at'}
        feedback_required = {'reviewed_by', 'eval_question', 'expected_result', 'eval_approved_by', 'eval_approved_at'}
        if not required <= runs or not feedback_required <= feedback:
            raise RuntimeError('Trace schema has partial state; no changes applied')
        return True
    raise ValueError('unknown migration')


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', required=True, choices=['local', 'supabase'])
    parser.add_argument('--apply', action='store_true', help='Apply pending migrations after showing their order')
    args = parser.parse_args()
    load_dotenv(ROOT / '.env', override=False)
    dsn = ('postgresql://postgres:postgres@127.0.0.1:54322/postgres' if args.target == 'local'
           else os.environ['CHAT_DATABASE_URL'])
    host = conninfo_to_dict(dsn).get('host', '')
    if args.target == 'local' and host not in ('127.0.0.1', 'localhost'):
        raise ValueError('Local target must point to localhost')
    if args.target == 'supabase' and not host.endswith(('.supabase.com', '.supabase.co')):
        raise ValueError('Expected the configured Supabase database')
    with psycopg.connect(dsn, connect_timeout=10, options='-c lock_timeout=5000 -c statement_timeout=30000') as conn:
        conn.execute('SELECT pg_advisory_xact_lock(78006114)')
        pending = [(version, path) for version, path in MIGRATIONS if not _is_applied(conn, version)]
        print(json.dumps({'target': args.target, 'pending_in_order': [version for version, _ in pending],
                          'mode': 'apply' if args.apply else 'plan'}, ensure_ascii=False))
        if not args.apply:
            return
        before = conn.execute('SELECT (SELECT count(*) FROM public.answer_feedback), '
                              '(SELECT count(*) FROM public.messages)').fetchone()
        for version, path in pending:
            sql = path.read_text(encoding='utf-8')
            conn.execute(sql, prepare=False)
            history = conn.execute("SELECT to_regclass('supabase_migrations.schema_migrations')").fetchone()[0]
            if history:
                name = path.stem.removeprefix(version + '_')
                conn.execute('INSERT INTO supabase_migrations.schema_migrations(version,name,statements) VALUES (%s,%s,%s) '
                             'ON CONFLICT (version) DO NOTHING', (version, name, [sql]))
        after = conn.execute('SELECT (SELECT count(*) FROM public.answer_feedback), '
                             '(SELECT count(*) FROM public.messages)').fetchone()
        if args.target == 'local' and before != after:
            raise RuntimeError('Existing feedback or message rows changed during migration')
        print(json.dumps({'target': args.target, 'status': 'applied',
                          'versions': [version for version, _ in pending],
                          'historical_answers_backfilled': False}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        # No DSN, host, SQL values, or database contents in deployment output.
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__,
                          'sqlstate': getattr(exc, 'sqlstate', None)}))
        sys.exit(1)
