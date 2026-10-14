"""Export only operator-approved, sanitized evaluation cases; never export feedback text."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

import psycopg
from dotenv import load_dotenv
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', choices=('local', 'supabase'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if ROOT == output or ROOT in output.parents:
        parser.error('Choose an output path outside the repository; user feedback must not be exported into Git.')
    load_dotenv(ROOT / '.env', override=False)
    dsn = 'postgresql://postgres:postgres@127.0.0.1:54322/postgres' if args.target == 'local' else os.environ['CHAT_DATABASE_URL']
    host = conninfo_to_dict(dsn).get('host', '')
    if args.target == 'local' and host not in ('127.0.0.1', 'localhost'):
        parser.error('Local target must point to localhost')
    if args.target == 'supabase' and not host.endswith(('.supabase.com', '.supabase.co')):
        parser.error('Expected the configured Supabase database')
    with psycopg.connect(dsn, connect_timeout=10, row_factory=dict_row) as conn:
        rows = conn.execute("SELECT answer_id,eval_question,expected_result,expected_evidence "
                            "FROM public.answer_feedback WHERE review_status='resolved' "
                            "AND eval_approved_by IS NOT NULL AND eval_approved_at IS NOT NULL "
                            "AND eval_question IS NOT NULL ORDER BY reviewed_at,answer_id").fetchall()
    cases = []
    for row in rows:
        expected = row['expected_result']
        sources = row['expected_evidence']
        if (not isinstance(expected, dict) or expected.get('task') not in ('qa', 'estimate')
                or not isinstance(expected.get('status'), str) or not expected['status'].strip()
                or not isinstance(expected.get('numbers'), dict) or 'unit' not in expected
                or not isinstance(sources, list) or not sources):
            raise ValueError('An approved row is missing the required expected status, numbers, unit, or evidence')
        task = expected['task']
        if task == 'qa' and (not expected.get('division') or not expected.get('section_no')):
            raise ValueError('A QA case needs reviewed division and section_no')
        if task == 'estimate' and (not expected.get('spec_id') or not isinstance(expected.get('input'), dict)):
            raise ValueError('An estimate case needs spec_id and reviewed input conditions')
        opaque_id = hashlib.sha256(str(row['answer_id']).encode()).hexdigest()[:16]
        case = {'id': f'reviewed-{opaque_id}', 'label': task, 'question': row['eval_question'],
                'sources': sources}
        if task == 'qa':
            case.update(expected={k: expected[k] for k in ('status', 'numbers', 'unit', 'division', 'section_no')},
                        division=expected['division'], section_no=expected['section_no'])
        else:
            case.update(spec_id=expected['spec_id'], input=expected['input'],
                        expected={'status': expected['status'], **expected['numbers'], 'unit': expected['unit']})
        cases.append(case)
    output.parent.mkdir(parents=True, exist_ok=True)
    content = ''.join(json.dumps(case, ensure_ascii=False, separators=(',', ':')) + '\n' for case in cases)
    output.write_text(content, encoding='utf-8')
    print(json.dumps({'status': 'exported', 'case_count': len(cases), 'output': str(output)}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error_type': type(exc).__name__}, ensure_ascii=False))
        sys.exit(1)
