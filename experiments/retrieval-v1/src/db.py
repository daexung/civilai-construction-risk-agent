"""로컬 PostgreSQL 적재. 원격 접속은 거부한다.

  python -B experiments/retrieval-v1/src/db.py createdb   # 검증 전용 DB 생성(있으면 그대로)
  python -B experiments/retrieval-v1/src/db.py migrate
  python -B experiments/retrieval-v1/src/db.py load       # 장부 작성 + 한 트랜잭션 적재

연결: 환경 변수 RAG_DATABASE_URL. 없으면 로컬 Supabase 기본값의 검증 전용 DB를 쓴다.
같은 release_id를 다시 적재하면 같은 트랜잭션 안에서 그 릴리스 행을 지우고 다시 넣는다. 실패하면 전부 되돌린다.
활성 릴리스(release_channels)는 바꾸지 않는다.
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_index as bi  # noqa: E402

DEFAULT_DSN = 'postgresql://postgres:postgres@127.0.0.1:54322/civilai_rag_verify'
MIGRATIONS = [bi.WORK / 'sql/20261011000100_rag_knowledge.sql', bi.WORK / 'sql/20261011000200_rag_search_records.sql']
OUT = bi.WORK / 'out'
TABLES = ['documents', 'nodes', 'sections', 'toc_entries', 'source_records', 'record_cells', 'corrections', 'search_records',
          'source_relations',
          'edges', 'edge_candidates']


def dsn():
    url = os.environ.get('RAG_DATABASE_URL', DEFAULT_DSN)
    u = urlparse(url)
    if u.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise SystemExit('로컬 PostgreSQL만 허용한다(원격 Supabase 접속 금지).')
    if (u.path or '/').lstrip('/') in ('', 'postgres'):
        raise SystemExit('회원·대화 자료가 있는 postgres DB 대신 검증 전용 DB를 쓴다.')
    return url


def dump(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding='utf-8')


def rows_of(b):
    """테이블별 적재 행(열 순서 고정). JSON 열은 문자열로."""
    rid = b['manifest']['release_id']
    d = b['document']
    edges = b['edges'] + b['scan']
    return {
        'documents': (['release_id', 'document_id', 'title', 'year', 'version_label', 'pdf_path', 'pdf_sha256', 'raw_sha256',
                       'generation_id', 'pages'],
                      [(rid, d['document_id'], d['title'], d['year'], d['version_label'], d['pdf_path'], d['pdf_sha256'],
                        d['raw_sha256'], d['generation_id'], d['pages'])]),
        'nodes': (['release_id', 'node_id', 'document_id', 'kind', 'page', 'doc_order', 'odl_id', 'bbox', 'text',
                   'parent_node_id', 'division', 'region', 'structure'],
                  [(rid, n['node_id'], bi.DOCUMENT_ID, n['kind'], n['page'], n['doc_order'], n['odl_id'],
                    None if n['bbox'] is None else dump(n['bbox']), n['text'], n['parent_node_id'], n['division'],
                    n['region'], dump(n['structure'])) for n in b['nodes']]),
        'sections': (['release_id', 'section_id', 'document_id', 'division', 'level', 'number', 'title', 'title_raw',
                      'heading_node_id', 'parent_section_id', 'start_order', 'end_order', 'first_page', 'last_page',
                      'status', 'evidence'],
                     [(rid, s['section_id'], s['document_id'], s['division'], s['level'], s['number'], s['title'],
                       s['title_raw'], s['heading_node_id'], s['parent_section_id'], s['start_order'], s['end_order'],
                       s['first_page'], s['last_page'], s['status'], dump(s['evidence'])) for s in b['sections']]),
        'toc_entries': (['release_id', 'toc_id', 'node_id', 'division', 'number', 'title', 'printed_page',
                         'matched_section_id', 'match_status'],
                        [(rid, t['toc_id'], t['node_id'], t['division'], t['number'], t['title'], t['printed_page'],
                          t['matched_section_id'], t['match_status']) for t in b['toc']]),
        'source_records': (['release_id', 'record_uid', 'record_idx', 'kind', 'page', 'text', 'source_node_id', 'section_id',
                            'record', 'link'],
                           [(rid, r['record_uid'], r['record_idx'], r['kind'], r['page'], r['text'], r['source_node_id'],
                             r['section_id'], dump(r['record']), dump(r['link'])) for r in b['records']]),
        'record_cells': (['release_id', 'record_uid', 'cell_node_id'],
                         [(rid, r['record_uid'], c) for r in b['records'] for c in r['cell_ids']]),
        'source_relations': (['release_id', 'relation_id', 'type', 'from_raw', 'to_raw', 'from_node_id', 'to_node_id',
                              'from_norm', 'to_norm', 'confirmed', 'status', 'raw'],
                             [(rid, r['relation_id'], r['type'], r['from_raw'], r['to_raw'], r['from_node_id'], r['to_node_id'],
                               r['from_norm'], r['to_norm'], r['confirmed'], r['status'], dump(r['raw']))
                              for r in b['relations']]),
        'edges': (['release_id', 'edge_id', 'origin', 'relation_id', 'from_node_id', 'expression', 'sentence', 'condition_text',
                   'target_division', 'target_number', 'target_subitem', 'target_status', 'reason', 'method',
                   'source_confirmed', 'source_status', 'evidence'],
                  [(rid, e['edge_id'], e['origin'], e['relation_id'], e['from_node_id'], e['expression'], e['sentence'],
                    e['condition_text'], e['target_division'], e['target_number'], e['target_subitem'], e['target_status'],
                    e['reason'], e['method'], e['source_confirmed'], e['source_status'], dump(e['evidence'])) for e in edges]),
        'corrections': (['release_id', 'correction_id', 'kind', 'data'],
                        [(rid, c['correction_id'], 'section_heading_and_membership', dump(c)) for c in b['corrections']]),
        'search_records': (['release_id', 'search_uid', 'search_idx', 'origin', 'record_uid', 'correction_id', 'kind', 'page',
                            'source_node_id', 'section_id', 'section_text', 'text', 'previous_section_text'],
                           [(rid, x['search_uid'], x['search_idx'], x['origin'], x['record_uid'], x['correction_id'], x['kind'],
                             x['page'], x['source_node_id'], x['section_id'], x['section_text'], x['text'],
                             x.get('previous_section_text')) for x in b['search_records']]),
        'edge_candidates': (['release_id', 'edge_id', 'rank', 'role', 'section_id', 'subitem_node_id', 'reason'],
                            [(rid, e['edge_id'], k, c['role'], c['section_id'], c['subitem_node_id'], c['reason'])
                             for e in edges for k, c in enumerate(e['candidates'])]),
    }


def content_hash(cols, rows):
    h = hashlib.sha256()
    for r in sorted(rows, key=lambda r: tuple('' if v is None else str(v) for v in r[:3])):
        h.update(dump([None if v is None else str(v) for v in r]).encode())
    return h.hexdigest()


def write_ledgers(b, rows):
    rid = b['manifest']['release_id']
    d = OUT / rid
    write(OUT / 'input_manifest.json', b['manifest'])
    write(d / 'input_manifest.json', b['manifest'])
    sec_by = {s['section_id']: s for s in b['sections']}

    def ledger_row(e):
        return {k: e[k] for k in ('edge_id', 'origin', 'relation_id', 'from_node_id', 'expression', 'sentence', 'condition_text',
                                  'target_division', 'target_number', 'target_subitem', 'target_status', 'reason',
                                  'method', 'source_confirmed', 'source_status', 'evidence')} | {
            'targets': [{'section_id': c['section_id'], 'division': sec_by[c['section_id']]['division'],
                         'number': sec_by[c['section_id']]['number'], 'title': sec_by[c['section_id']]['title'],
                         'page': sec_by[c['section_id']]['first_page'], 'subitem_node_id': c['subitem_node_id']}
                        for c in e['candidates'] if c['role'] == 'target'],
            'candidates': [{'section_id': c['section_id'], 'division': sec_by[c['section_id']]['division'],
                            'number': sec_by[c['section_id']]['number'], 'title': sec_by[c['section_id']]['title'],
                            'page': sec_by[c['section_id']]['first_page'], 'reason': c['reason']}
                           for c in e['candidates'] if c['role'] == 'candidate']}

    count = lambda xs, k: {v: sum(1 for x in xs if x[k] == v) for v in sorted({x[k] for x in xs})}
    write(d / 'reference_ledger.json', {'release_id': rid, 'total': len(b['edges']),
                                        'by_status': count(b['edges'], 'target_status'),
                                        'note': '대상 확인(target_status)은 적용 여부가 아니다. source_confirmed는 기존 파싱 값 그대로다.',
                                        'references': [ledger_row(e) for e in b['edges']]})
    write(d / 'additional_reference_candidates.json', {'release_id': rid, 'total': len(b['scan']),
                                                       'by_status': count(b['scan'], 'target_status'),
                                                       'note': '기존 232건과 별도. 일반 패턴 점검으로 찾은 새 후보이며 기존 파싱 관계가 없다.',
                                                       'candidates': [ledger_row(e) for e in b['scan']]})
    write(d / 'section_registry.json', {
        'release_id': rid,
        'rules': ['부문 표지 쪽(‘2026’과 ‘X부문’ 제목이 함께 있는 쪽)으로 본문 부문 구간을 나눈다. 첫 표지 앞은 목차 구역',
                  '본문 구역의 제목 노드, 또는 본문 글의 첫 줄이 번호(N-N-N, N-N, 제N장) 제목일 때만 절로 둔다',
                  '번호 없는 제목·품목 코드·문장 속 번호는 절로 만들지 않는다',
                  '절 식별자 = 문서 + 부문 + 번호. 다른 부문의 같은 번호는 별도 절',
                  '제목 끝 개정 표기와 단위 기준(㎥당)은 title에서 떼고 title_raw에 원문을 둔다',
                  '목차 줄은 toc_entries로 따로 두고 본문 절과 대조만 한다'],
        'covers': b['covers'], 'stats': b['section_stats'],
        'counts': {f'{dv}/{lv}': sum(1 for s in b['sections'] if s['division'] == dv and s['level'] == lv)
                   for dv in bi.DIVISIONS for lv in ('chapter', 'group', 'section')},
        'toc_match': count(b['toc'], 'match_status'),
        'toc_without_body_section': [t for t in b['toc'] if t['match_status'] != 'matched'],
        'page_division_disagreements': {p: e for p, e in b['page_evidence'].items() if e['agree'] is False},
        'sections': b['sections']})
    node_by = {n['node_id']: n for n in b['nodes']}
    per_table = {}
    for r in b['records']:
        if r['kind'] == 'table':
            per_table[r['record']['table_id']] = per_table.get(r['record']['table_id'], 0) + 1
    no_sec = {}
    for r in b['records']:
        if r['section_id'] is None:
            reg = node_by[r['source_node_id']]['region']
            no_sec[reg] = no_sec.get(reg, 0) + 1
    tables = [n for n in b['nodes'] if n['kind'] == 'table']
    # 다음 청킹 입력(교정 적용)과 교정 장부
    with open(d / 'search_records.jsonl', 'w', encoding='utf-8') as f:
        for x in b['search_records']:
            f.write(json.dumps(x, ensure_ascii=False) + '\n')
    changed = [x for x in b['search_records'] if x['origin'] != 'original']
    write(d / 'correction_ledger.json', {
        'release_id': rid, 'note': '원문 대조 교정 자료를 원문 저장·검색 단계에 적용한 결과. 파싱 원본 출력은 바꾸지 않았다.',
        'corrections': [{**c, 'section_id': f"{bi.DOCUMENT_ID}:{bi.DIV_CODE[c['division']]}:{c['number']}",
                         'moved_nodes': [{'node_id': n, 'before': b['membership_before'].get(n),
                                          'after': f"{bi.DOCUMENT_ID}:{bi.DIV_CODE[c['division']]}:{c['number']}"} for n in c['members']],
                         'added_nodes': [f"corr:{c['correction_id']}:heading", f"corr:{c['correction_id']}:basis"]}
                        for c in b['corrections']],
        'search_records_changed': changed,
        'counts': {'search_records': len(b['search_records']), 'section_corrected': sum(x['origin'] == 'section_corrected' for x in changed),
                   'added_from_pdf': sum(x['origin'] == 'added_from_pdf' for x in changed)}})
    write(d / 'source_coverage.json', {
        'release_id': rid,
        'records': {'total': len(b['records']), 'by_kind': count(b['records'], 'kind'),
                    'with_source_node': sum(r['source_node_id'] in node_by for r in b['records']),
                    'with_section': sum(r['section_id'] is not None for r in b['records']),
                    'without_section_by_region': no_sec,
                    'without_section_note': 'front=목차·표지 앞부분, cover=부문 표지 쪽. 본문 레코드는 모두 절에 속한다',
                    'table_cell_links': sum(len(r['cell_ids']) for r in b['records'])},
        'tables': {'total': len(tables), 'with_records': sum(1 for t in tables if t['node_id'] in per_table),
                   'without_own_records': [t['node_id'] for t in tables if t['node_id'] not in per_table],
                   'without_own_records_note': '칸 안 작은 표·주석 표 등 자기 table_id로 레코드를 내지 않은 표. 노드와 칸은 모두 보존',
                   'cells': sum(1 for n in b['nodes'] if n['kind'] == 'cell')},
        'nodes': count(b['nodes'], 'kind'), 'regions': count(b['nodes'], 'region'),
        'relations': {'total': len(b['relations']), 'endpoint_normalization': b['relation_stats']},
        'records_by_section': {s['section_id']: sum(1 for r in b['records'] if r['section_id'] == s['section_id'])
                               for s in b['sections'] if s['level'] == 'section'}})
    hashes = {t: {'rows': len(r), 'content_sha256': content_hash(c, r)} for t, (c, r) in rows.items()}
    imp = {'release_id': rid, 'generation_id': b['document']['generation_id'],
           'migrations': {m.name: bi.sha256(m) for m in MIGRATIONS}, 'tables': hashes}
    write(d / 'import_manifest.json', imp)
    return imp


# 해시 목록에 넣지 않는 파일: 목록 자신과 검사 결과(검사 결과는 out/verification_runs/에 따로 쌓는다)
MANIFEST_SKIP = {'manifest.json', 'verification.json', 'example_queries.json'}


def write_manifest(rid, status=None):
    """모든 결과 파일 저장이 끝난 뒤 마지막에 부른다. status가 없으면 기존 목록의 상태를 유지한다."""
    d = OUT / rid
    if status is None:
        status = json.loads((d / 'manifest.json').read_text(encoding='utf-8'))['status']
    files = {p.name: bi.sha256(p) for p in sorted(d.iterdir()) if p.is_file() and p.name not in MANIFEST_SKIP}
    write(d / 'manifest.json', {'release_id': rid, 'status': status, 'files_sha256': files,
                                'note': '이 폴더의 자료 파일 전체(manifest.json·검사 결과 제외). 검사 결과는 out/verification_runs/'})


def createdb():
    u = urlparse(dsn())
    name = u.path.lstrip('/')
    admin = u._replace(path='/postgres').geturl()
    with psycopg.connect(admin, autocommit=True) as c:
        if not c.execute('select 1 from pg_database where datname=%s', (name,)).fetchone():
            c.execute(f'create database "{name}"')
            print('created', name)
        else:
            print('exists', name)


def migrate(conn=None):
    with (conn or psycopg.connect(dsn())) as c:
        for m in MIGRATIONS:
            c.execute(m.read_text(encoding='utf-8'))
            print('migrated', m.name)


def load(fail_after=None):
    b = bi.build()
    rows = rows_of(b)
    imp = write_ledgers(b, rows)
    rid = b['manifest']['release_id']
    with psycopg.connect(dsn()) as c:
        try:
            with c.transaction():
                c.execute("""insert into rag_knowledge.releases(release_id, generation_id, status, input_manifest, code_sha256)
                             values (%s, %s, 'loading', %s, %s)
                             on conflict (release_id) do update set status='loading', input_manifest=excluded.input_manifest,
                               code_sha256=excluded.code_sha256, completed_at=null""",
                          (rid, b['document']['generation_id'], dump(b['manifest']), dump(b['manifest']['code_sha256'])))
                for t in reversed(TABLES):
                    c.execute(f'delete from rag_knowledge.{t} where release_id=%s', (rid,))
                for t in TABLES:
                    cols, data = rows[t]
                    with c.cursor().copy(f"copy rag_knowledge.{t} ({','.join(cols)}) from stdin") as cp:
                        for r in data:
                            cp.write_row(r)
                    if fail_after == t:
                        raise RuntimeError(f'시험용 중단: {t} 적재 직후')
                got = {t: c.execute(f'select count(*) from rag_knowledge.{t} where release_id=%s', (rid,)).fetchone()[0]
                       for t in TABLES}
                want = {t: len(rows[t][1]) for t in TABLES}
                if got != want:
                    raise RuntimeError(f'적재 행 수 불일치: {got} != {want}')
                c.execute("set constraints all immediate")
                c.execute("""update rag_knowledge.releases set status='complete', row_counts=%s, completed_at=now()
                             where release_id=%s""", (dump(got), rid))
        except Exception:
            with c.transaction():
                c.execute("""insert into rag_knowledge.releases(release_id, generation_id, status, input_manifest, code_sha256)
                             values (%s, %s, 'failed', %s, %s) on conflict (release_id) do nothing""",
                          (rid, b['document']['generation_id'], dump(b['manifest']), dump(b['manifest']['code_sha256'])))
            raise
    write_manifest(rid, 'loaded_complete')
    print(json.dumps({'release_id': rid, 'rows': {t: v['rows'] for t, v in imp['tables'].items()}}, ensure_ascii=False))
    return rid


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser()
    p.add_argument('cmd', choices=['createdb', 'migrate', 'load'])
    p.add_argument('--fail-after', help='시험용: 지정 테이블 적재 직후 일부러 실패')
    a = p.parse_args()
    {'createdb': createdb, 'migrate': migrate, 'load': lambda: load(a.fail_after)}[a.cmd]()
