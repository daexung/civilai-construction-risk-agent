"""Private, bounded server-side answer execution persistence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import cache
from hashlib import sha256
import logging
import os
from pathlib import Path

from psycopg.types.json import Jsonb
from backend.paths import ROOT
from backend.shared import answer_trace

logger = logging.getLogger(__name__)
RETENTION_DAYS = 90


def file_hash(path):
    path = Path(path)
    if not path.is_file():
        return None
    digest = sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


@cache
def versions():
    from backend.agent.tools.search.vector import load_index_config
    from backend.agent.tools.source import citation
    from backend.agent.tools.search import hybrid
    config = load_index_config()
    assets = {name: file_hash(config[name]) for name in ('chunks', 'vectors')}
    assets.update({'citation_chunks': file_hash(citation.CHUNKS), 'pdf': file_hash(citation.PDF),
                   'page_map': file_hash(citation.PAGE_MAP)})
    code = {str(p.relative_to(ROOT)): file_hash(p) for p in sorted((ROOT / 'backend').rglob('*'))
            if p.is_file() and p.suffix in ('.py', '.md', '.json') and '__pycache__' not in p.parts}
    specs = {str(p.relative_to(ROOT)): file_hash(p) for p in sorted((ROOT / 'data/drafts').rglob('*.json'))
             if 'raw' not in p.parts}
    rates = {str(p.relative_to(ROOT)): file_hash(p) for p in sorted((ROOT / 'data/rates').rglob('*')) if p.is_file()}
    return {'code_version': os.getenv('APP_CODE_VERSION') or 'sha256:' + answer_trace.digest(code),
            'code_files_sha256': answer_trace.digest(code), 'asset_hashes': assets,
            'chunk_set_id': 'sha256:' + assets['chunks'] if assets['chunks'] else None,
            'specs_sha256': answer_trace.digest(specs), 'rates_sha256': answer_trace.digest(rates),
            'retrieval_config': {'config_sha256': file_hash(config['config_path']),
                                 'divisions': config.get('divisions'), 'rrf_k': hybrid.K,
                                 'candidates': hybrid.CANDIDATES,
                                 'embed_provider': os.getenv('EMBED_PROVIDER') or config['embed_provider'],
                                 'embed_model': os.getenv('EMBED_MODEL') or config.get('embed_model')},
            'configured_model': os.getenv('LLM_MODEL') or _configured_model(),
            'agent_mode': os.getenv('AGENT_MODE') or 'graph'}


def _configured_model():
    try:
        from backend.agent.tools.llm.client import model_name
        return model_name()
    except Exception:
        return None


def begin_payload(state):
    version = versions()
    return {'id': state['id'], 'request_id': state.get('request_id'), 'thread_id': state.get('thread_id'),
            'user_id': state.get('user_id'), 'conversation_id': state.get('conversation_id'),
            'environment': state.get('environment'), 'agent_mode': state.get('agent_mode'),
            'started_at': state['started_at'], 'status': 'running', 'capture_status': 'complete',
            'expires_at': state['started_at'] + timedelta(days=RETENTION_DAYS),
            'versions': version}


def persist_start(state):
    try:
        from backend.api import chat_storage
        run = begin_payload(state)
        with chat_storage.connection() as conn, conn.transaction():
            conn.execute('INSERT INTO public.answer_runs(id,request_id,thread_id,user_id,environment,agent_mode,started_at,status,versions,capture_status,expires_at) '
                         'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                         (run['id'], run['request_id'], run['thread_id'], run['user_id'], run['environment'], run['agent_mode'],
                          run['started_at'], run['status'], Jsonb(run['versions']), run['capture_status'], run['expires_at']))
        return True
    except Exception as exc:
        logger.warning('answer_run_write_failed run_id=%s phase=start error_type=%s', state.get('id'), type(exc).__name__)
        return False


def _step_row(run_id, entry):
    return (entry['id'], run_id, entry.get('parent_step_id'), entry['step_kind'], entry['name'], entry['sequence'],
            entry.get('started_at'), entry.get('finished_at'), entry.get('duration_ms'), entry.get('status', 'incomplete'),
            Jsonb(entry['input_summary']) if entry.get('input_summary') is not None else None,
            Jsonb(entry['output_summary']) if entry.get('output_summary') is not None else None,
            entry.get('error_code'), entry.get('error_type'), Jsonb(entry.get('metadata') or {}))


def persist_finish(state, response=None, *, failed=False):
    try:
        from backend.api import chat_storage
        if not state.get('started_persisted'):
            state['started_persisted'] = persist_start(state)
        finished = datetime.now(timezone.utc)
        version = versions()
        answer_id = (response or {}).get('answer_id')
        if answer_id:
            state['answer_id'] = answer_id
        status = 'failed' if failed else 'completed'
        summary = _final_summary(response or {})
        with chat_storage.connection() as conn, conn.transaction():
            conversation_id = (response or {}).get('thread_id') or state.get('conversation_id')
            if conversation_id and not conn.execute('SELECT 1 FROM public.conversations WHERE id=%s', (conversation_id,)).fetchone():
                conversation_id = None
            conn.execute('UPDATE public.answer_runs SET answer_id=%s,thread_id=COALESCE(%s,thread_id),conversation_id=COALESCE(%s,conversation_id),finished_at=%s,status=%s,answer_status=%s,versions=%s,capture_status=%s '
                         'WHERE id=%s', (answer_id, (response or {}).get('thread_id'), conversation_id, finished, status, (response or {}).get('status'), Jsonb(version),
                                          state.get('capture_status', 'complete'), state['id']))
            for entry in state['steps']:
                conn.execute('INSERT INTO public.answer_run_steps(id,run_id,parent_step_id,step_kind,name,sequence,started_at,finished_at,duration_ms,status,input_summary,output_summary,error_code,error_type,metadata) '
                             'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) '
                             'ON CONFLICT (id) DO NOTHING', _step_row(state['id'], entry))
            if summary:
                conn.execute('INSERT INTO public.answer_run_steps(run_id,step_kind,name,sequence,started_at,finished_at,duration_ms,status,output_summary,metadata) '
                             'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id,sequence) DO NOTHING',
                             (state['id'], 'answer', 'answer_summary', len(state['steps']) + 1,
                              state['started_at'], finished, round((finished-state['started_at']).total_seconds()*1000, 2),
                              'failed' if failed else 'completed', Jsonb(summary), Jsonb({'answer_status': (response or {}).get('status')})))
        return True
    except Exception as exc:
        logger.warning('answer_run_write_failed run_id=%s phase=finish error_type=%s', state.get('id'), type(exc).__name__)
        return False


def _final_summary(response):
    """Allowlisted response facts only. Never copy answer text, questions, or full state."""
    keep_evidence = []
    for item in response.get('evidence') or []:
        if isinstance(item, dict):
            keys = ('internal_id', 'chunk_id', 'division', 'section_no', 'pdf_page', 'printed_page', 'row', 'column', 'value')
            keep_evidence.append({key: item[key] for key in keys if key in item})
    citations = []
    qa = response.get('qa') or {}
    def collect_citations(value):
        if isinstance(value, dict):
            for cite in value.get('citations') or []:
                if isinstance(cite, dict):
                    item = {key: cite[key] for key in ('internal_id', 'chunk_id', 'division', 'section_no', 'pdf_page',
                                                        'printed_page', 'page', 'row', 'column', 'value', 'quote_match') if key in cite}
                    if isinstance(cite.get('quote'), str):
                        item['quote'] = cite['quote'][:600]
                    citations.append(item)
            for child in value.values():
                collect_citations(child)
        elif isinstance(value, list):
            for child in value[:100]:
                collect_citations(child)
    collect_citations(response.get('result') or {})
    collect_citations(response.get('priced') or {})
    for cite in qa.get('citations') or []:
        if isinstance(cite, dict):
            item = {key: cite[key] for key in ('chunk_id', 'division', 'section_no', 'pdf_page', 'printed_page',
                                                'row', 'column', 'value', 'quote_match') if key in cite}
            if isinstance(cite.get('quote'), str):
                item['quote'] = cite['quote'][:600]
            citations.append(item)
    citations = list({answer_trace.digest(cite): cite for cite in citations[:100]}.values())
    result = response.get('result') or {}
    calc = {key: result[key] for key in ('daily_volume', 'work_days', 'unit_basis', 'per_unit_only', 'review_status') if key in result}
    for key in ('daily_volume', 'work_days'):
        if isinstance(calc.get(key), dict):
            calc[key] = {k: calc[key][k] for k in ('value', 'unit', 'formula', 'source') if k in calc[key]}
    for key in ('lines', 'unit_lines'):
        calc[key] = [{k: line[k] for k in ('kind', 'name', 'value', 'unit', 'crew', 'source') if k in line}
                     for line in result.get(key) or [] if isinstance(line, dict)]
    search = response.get('search') or {}
    info = response.get('llm_info') or {}
    error = info.get('error')
    safe_errors = {'숫자 불일치', '금액 기준 누락', '미산정 누락', 'citations_missing', 'chunk_id', 'quote', 'money', 'numbers'}
    verification = {'answer_source': response.get('answer_source'),
                    'numeric_check': 'failed' if error == '숫자 불일치' else ('passed' if response.get('answer_source') == 'llm' else 'not_applicable'),
                    'citation_check': 'failed' if error in {'citations_missing', 'chunk_id', 'quote', 'money'} else
                                     ('passed' if citations else 'not_applicable'),
                    'fallback_reason': error if error in safe_errors else ('generation_unavailable' if error else None)}
    priced = response.get('priced') or {}
    price_summary = {'rate_version': priced.get('rate_version'), 'status': priced.get('status')}
    for key in ('lines', 'equipment_lines', 'cost_lines', 'supply_lines'):
        price_summary[key] = [{k: line[k] for k in ('kind', 'name', 'quantity', 'unit', 'rate', 'unit_price', 'amount', 'formula', 'source') if k in line}
                              for line in priced.get(key) or [] if isinstance(line, dict)]
    statement = response.get('statement') or {}
    totals = statement.get('totals') or {}
    statement_summary = {k: v for k, v in totals.items() if isinstance(v, (int, float))}
    return {'route': response.get('route'), 'answer_source': response.get('answer_source'),
            'evidence': keep_evidence, 'citations': citations, 'verification': verification, 'calculation': calc,
            'pricing': price_summary, 'statement_totals': statement_summary,
            'numeric_inputs': [{k: x[k] for k in ('name', 'value', 'unit', 'source') if k in x}
                               for x in response.get('inputs') or [] if isinstance(x, dict) and isinstance(x.get('value'), (int, float))],
            'retrieval': {k: search[k] for k in ('method', 'fallback_reason') if k in search},
            'model_attempts': info.get('attempts') if isinstance(info.get('attempts'), int) else None}


def persist_guest(response, run_id=None):
    """Compatibility shim: runs now persist in request-finally; guest transcript stays memory-only."""
    return None


def attach_feedback_run(conn, answer_id):
    return conn.execute('SELECT id FROM public.answer_runs WHERE answer_id=%s ORDER BY started_at DESC LIMIT 1',
                        (answer_id,)).fetchone()


def import_guest_thread(conn, source_thread, conversation_id, user_id):
    conn.execute('UPDATE public.answer_runs SET user_id=%s,conversation_id=%s,thread_id=%s '
                 'WHERE thread_id=%s AND user_id IS NULL',
                 (user_id, conversation_id, conversation_id, source_thread))


def delete_guest_thread(thread_id):
    """Called only after the ephemeral session secret has been verified."""
    if not os.getenv('CHAT_DATABASE_URL'):
        return True  # This process cannot have persisted a guest trace without the database.
    try:
        from backend.api import chat_storage
        with chat_storage.connection() as conn, conn.transaction():
            conn.execute('DELETE FROM public.answer_feedback WHERE thread_id=%s AND user_id IS NULL', (thread_id,))
            conn.execute('DELETE FROM public.answer_runs WHERE thread_id=%s AND user_id IS NULL', (thread_id,))
        return True
    except Exception as exc:
        logger.warning('answer_run_write_failed thread_id=%s phase=guest_delete error_type=%s',
                       thread_id, type(exc).__name__)
        return False
