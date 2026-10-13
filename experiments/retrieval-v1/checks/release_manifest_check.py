"""원문 릴리스 해시 목록이 자료 파일을 빠짐없이 담는지, 그리고 새 원문 버전의 내용이 기존 버전과 같은지 확인한다.

  python -B experiments/retrieval-v1/checks/release_manifest_check.py
      격리 DB(civilai_rag_tx)·임시 폴더에서 db.py load 경로를 실행해 확인한다. 기존 검증 DB·자료 폴더는 읽기만 한다.
  python -B experiments/retrieval-v1/checks/release_manifest_check.py --recorded <새 release_id>
      검증 DB에 이미 적재한 새 릴리스와 자료 폴더 out/<release_id>/를 확인한다. 아무것도 쓰지 않고 실행 기록만 남긴다.
  python -B experiments/retrieval-v1/checks/release_manifest_check.py --compare-path
      compare_releases.py가 비교 결과를 저장한 뒤 해시 목록을 다시 만드는 경로를 임시 출력 위치에서 확인한다(자료 폴더 쓰기 없음).

비교 기준은 청킹 묶음이 쓰는 기존 원문 릴리스(chunking.DEFAULT_RELEASE)다. release_id 열만 빼고 모든 열이 같아야 한다.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

import psycopg

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK / 'src'))
sys.path.insert(0, str(WORK / 'checks'))
import chunking as ch  # noqa: E402
import db  # noqa: E402
import run_records as rr  # noqa: E402

OLD = ch.DEFAULT_RELEASE
MAIN_DSN = db.dsn()
TX_DSN = MAIN_DSN.rsplit('/', 1)[0] + '/civilai_rag_tx'
STRAY = ('verification.json', 'example_queries.json')
SAME_FILES = ('additional_reference_candidates.json', 'correction_ledger.json', 'reference_ledger.json',
              'section_registry.json', 'source_coverage.json')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def manifest_problems(d):
    """해시 목록을 파일에서 독립적으로 다시 확인한다."""
    man = json.loads((d / 'manifest.json').read_text(encoding='utf-8'))
    listed = man['files_sha256']
    files = {p.name for p in d.iterdir() if p.is_file() and p.name != 'manifest.json'}
    return {'status': man['status'], 'listed': len(listed), 'files_in_folder': len(files),
            'unlisted': sorted(files - set(listed)), 'missing': sorted(set(listed) - files),
            'mismatch': sorted(n for n, h in listed.items() if n in files and sha(d / n) != h),
            'has_search_records': 'search_records.jsonl' in listed,
            'stray_check_files': sorted(n for n in files if n in STRAY)}


def release_md5(c, table, rid):
    return c.execute(f"""select count(*), md5(coalesce(string_agg((to_jsonb(t) - 'release_id')::text, E'\\n'
                         order by (to_jsonb(t) - 'release_id')::text), ''))
                         from rag_knowledge.{table} t where release_id=%s""", (rid,)).fetchone()


def canon(cols, row):
    return json.dumps([json.loads(v) if c == 'issues' and isinstance(v, str) else v for c, v in zip(cols, row)],
                      ensure_ascii=False, sort_keys=True, default=str)


def chunk_diff(c_new, rid_new, c_old, rid_old):
    """새 릴리스에서 청킹 코드를 메모리에서만 돌려 기존 청킹 묶음 저장 내용과 비교한다(저장하지 않음)."""
    old_set, old_input = c_old.execute('select chunk_set_id, input_sha256 from rag_knowledge.chunk_sets where release_id=%s',
                                       (rid_old,)).fetchone()
    d, b, meta = ch.build(c_new, rid_new)
    rws = ch.rows(d, b, meta['chunk_set_id'])
    out = {'old_chunk_set': old_set, 'would_be_chunk_set': meta['chunk_set_id'],
           'input_sha256_same': d['input_sha256'] == old_input, 'tables': {}}
    for t in ch.TABLES:
        cols, data = rws[t]
        keep = [i for i, c in enumerate(cols) if c not in ('release_id', 'chunk_set_id')]
        names = [cols[i] for i in keep]
        mem = sorted(canon(names, [r[i] for i in keep]) for r in data)
        stored = sorted(canon(names, r) for r in c_old.execute(
            f"select {','.join(names)} from rag_knowledge.{t} where chunk_set_id=%s", (old_set,)).fetchall())
        out['tables'][t] = {'rows_new': len(mem), 'rows_old': len(stored), 'same': mem == stored}
    return out


def content_diff(c_new, rid_new, c_old, rid_old):
    t = {}
    for table in db.TABLES:
        a, b = release_md5(c_new, table, rid_new), release_md5(c_old, table, rid_old)
        t[table] = {'rows_new': a[0], 'rows_old': b[0], 'same': a == b}
    return t


def ledger_diff(new_dir, old_dir):
    strip = lambda x: {k: v for k, v in x.items() if k != 'release_id'}
    res = {n: strip(json.loads((new_dir / n).read_text(encoding='utf-8'))) == strip(json.loads((old_dir / n).read_text(encoding='utf-8')))
           for n in SAME_FILES}
    res['search_records.jsonl'] = sha(new_dir / 'search_records.jsonl') == sha(old_dir / 'search_records.jsonl')
    new_in = json.loads((new_dir / 'input_manifest.json').read_text(encoding='utf-8'))
    old_in = json.loads((old_dir / 'input_manifest.json').read_text(encoding='utf-8'))
    changed_code = sorted(k for k in set(new_in['code_sha256']) | set(old_in['code_sha256'])
                          if new_in['code_sha256'].get(k) != old_in['code_sha256'].get(k))
    return res, {'input_files_same': {k: v['sha256'] for k, v in new_in['files'].items()} ==
                                     {k: v['sha256'] for k, v in old_in['files'].items()},
                 'changed_code_files': changed_code}


def compare_path():
    """1b의 원래 비교(0aaa… → 37f81b5cfb1b, 길어깨 제목 세 개 보완 기대값)를 db.OUT만 임시 폴더로 바꿔 실행한다.
    새 릴리스 폴더의 사본에 비교 결과가 더해지고 해시 목록이 그에 맞게 다시 만들어지는지 확인한다."""
    import compare_releases as cmp
    new = OLD
    old = 'rk-complete-82c206c61e21-0aaa02185ae9'
    tmp = WORK / 'out/tx_isolated' / f'compare-{time.strftime("%Y%m%dT%H%M%S")}'
    src = WORK / 'out' / new
    before = {p.name: sha(p) for p in src.iterdir() if p.is_file()}
    d = tmp / new
    d.mkdir(parents=True)
    for p in src.iterdir():
        if p.is_file() and p.name not in ('manifest.json', 'compare_with_previous_release.json'):
            shutil.copy2(p, d / p.name)
    # 비교 전 상태: 비교 결과 파일이 아직 없는 목록(적재 직후와 같음)
    db.OUT = tmp
    db.write_manifest(new, 'loaded_complete')
    listed_before = set(json.loads((d / 'manifest.json').read_text(encoding='utf-8'))['files_sha256'])
    checks = []
    try:
        ok = cmp.main(old, new)
        m = manifest_problems(d)
        listed = set(json.loads((d / 'manifest.json').read_text(encoding='utf-8'))['files_sha256'])
        checks = [
            {'name': '비교 도구의 원래 기대값(길어깨 제목 세 개 보완)이 그대로 통과', 'passed': bool(ok)},
            {'name': '비교 전 목록에는 비교 결과 파일이 없음', 'passed': 'compare_with_previous_release.json' not in listed_before},
            {'name': '비교 뒤 목록에 비교 결과 파일이 추가됨', 'passed': 'compare_with_previous_release.json' in listed},
            {'name': '목록 누락 0, 목록의 없는 파일 0', 'passed': not m['unlisted'] and not m['missing'], 'detail': m},
            {'name': '해시 불일치 0, 상태 유지(loaded_complete)', 'passed': not m['mismatch'] and m['status'] == 'loaded_complete', 'detail': m},
            {'name': 'search_records.jsonl도 목록에 있음', 'passed': m['has_search_records']},
            {'name': '실제 자료 폴더는 바뀌지 않음', 'passed': {p.name: sha(p) for p in src.iterdir() if p.is_file()} == before},
        ]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    res = {'release_id': new, 'compared_with': old, 'mode': 'compare_path_isolated_output', 'passed': sum(c['passed'] for c in checks),
           'failed': sum(not c['passed'] for c in checks), 'note': '출력 위치만 임시 폴더. DB는 읽기만 했다. 검사 개수는 정확도 점수가 아니다.',
           'checks': checks}
    r = rr.start(new, 'compare_manifest_path', None, note='compare_releases.py의 해시 목록 갱신 경로를 임시 출력 위치에서 실행')
    res['run_id'] = r['meta']['run_id']
    meta = rr.finish(r, {'verification.json': res}, res['failed'] == 0 and bool(checks), {'passed': res['passed'], 'failed': res['failed']})
    for c in checks:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['name'])
    print('run', meta['run_id'], meta['status'])
    return meta['status'] == 'passed'


def run(recorded):
    checks = []

    def check(name, ok, detail=None):
        checks.append({'name': name, 'passed': bool(ok), 'detail': detail})

    old_dir = WORK / 'out' / OLD
    tmp = None
    if recorded:
        rid, new_dir, c_new_dsn = recorded, WORK / 'out' / recorded, MAIN_DSN
        note = f'검증 DB에 적재한 새 릴리스 {rid}를 확인(쓰기 없음)'
    else:
        tag = time.strftime('%Y%m%dT%H%M%S')
        tmp = WORK / 'out/tx_isolated' / f'manifest-{tag}'
        os.environ['RAG_DATABASE_URL'] = TX_DSN
        db.OUT = tmp / 'out'
        db.createdb()
        with psycopg.connect(TX_DSN) as c:
            c.execute('drop schema if exists rag_knowledge cascade')   # 격리 DB만 초기화한다
        db.migrate()
        rid = db.load()
        new_dir, c_new_dsn = db.OUT / rid, TX_DSN
        note = f'격리 DB civilai_rag_tx, 임시 폴더(검사 후 삭제)에서 db.py load 경로를 실행. 새 릴리스 {rid}'
    try:
        m = manifest_problems(new_dir)
        check('해시 목록 상태가 loaded_complete', m['status'] == 'loaded_complete', m['status'])
        check('search_records.jsonl이 해시 목록에 있음', m['has_search_records'])
        check('폴더의 자료 파일이 모두 목록에 있고 목록의 파일이 모두 있음', not m['unlisted'] and not m['missing'], m)
        check('목록의 모든 해시가 파일에서 다시 계산한 값과 같음', not m['mismatch'] and m['listed'] > 0, m)
        check('자료 폴더에 검사 결과 파일이 없음', not m['stray_check_files'], m['stray_check_files'])
        led, code = ledger_diff(new_dir, old_dir)
        check('장부·검색 입력 파일이 기존 릴리스와 같음(release_id만 다름)', all(led.values()), led)
        check('입력 파일 해시는 같고 바뀐 코드는 db.py뿐', code['input_files_same'] and code['changed_code_files'] == ['db.py'], code)
        with psycopg.connect(c_new_dsn) as cn, psycopg.connect(MAIN_DSN) as co:
            st = cn.execute('select status from rag_knowledge.releases where release_id=%s', (rid,)).fetchone()
            check('새 릴리스 DB 상태 complete, 활성 채널 없음', st and st[0] == 'complete' and
                  cn.execute('select count(*) from rag_knowledge.release_channels').fetchone()[0] == 0, st)
            cd = content_diff(cn, rid, co, OLD)
            check('원문 테이블 11개가 기존 릴리스와 같음(release_id 열만 제외)', all(v['same'] for v in cd.values()), cd)
            cc = chunk_diff(cn, rid, co, OLD)
            check('새 릴리스의 청킹 입력 해시가 기존 청킹 묶음과 같음', cc['input_sha256_same'], cc['would_be_chunk_set'])
            check('새 릴리스에서 청킹을 메모리로 돌린 결과가 기존 청킹 묶음 저장 내용과 같음(ID 열 제외)',
                  all(v['same'] for v in cc['tables'].values()), cc['tables'])
            link = co.execute('select chunk_set_id, release_id, status from rag_knowledge.chunk_sets').fetchall()
            check('기존 청킹 묶음은 기존 원문 릴리스에 연결된 그대로', link == [(cc['old_chunk_set'], OLD, 'complete')], link)
    finally:
        if tmp and tmp.exists():
            shutil.rmtree(tmp)
    res = {'release_id': rid, 'compared_with': OLD, 'mode': 'recorded' if recorded else 'isolated',
           'passed': sum(x['passed'] for x in checks), 'failed': sum(not x['passed'] for x in checks),
           'note': '검사 개수는 정확도 점수가 아니다.', 'checks': checks}
    tool = 'manifest_check_recorded' if recorded else 'manifest_check_isolated'
    r = rr.start(rid, tool, new_dir if recorded else None, note=note)
    res['run_id'] = r['meta']['run_id']
    meta = rr.finish(r, {'verification.json': res}, res['failed'] == 0, {'passed': res['passed'], 'failed': res['failed']})
    for x in checks:
        print(('PASS ' if x['passed'] else 'FAIL ') + x['name'])
    print('run', meta['run_id'], meta['status'])
    return meta['status'] == 'passed'


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a = argparse.ArgumentParser()
    a.add_argument('--recorded', metavar='RELEASE_ID')
    a.add_argument('--compare-path', action='store_true')
    args = a.parse_args()
    sys.exit(0 if (compare_path() if args.compare_path else run(args.recorded)) else 1)
