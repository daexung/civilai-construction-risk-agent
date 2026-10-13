"""격리된 로컬 DB에서 재적재·중단(트랜잭션) 검사를 한다. 기존 검증 DB의 릴리스·청킹 묶음과 자료 파일은 건드리지 않는다.

  python -B experiments/retrieval-v1/checks/isolated_tx.py

- 같은 로컬 PostgreSQL 서버의 별도 DB(civilai_rag_tx)를 쓴다. 적재 코드가 쓰는 파일은 out/tx_isolated/<run>/으로 돌린다.
- 현재 코드로 적재한 결과가 기존 검증 DB의 기존 원문 릴리스·청킹 묶음 내용과 같은지(release_id·chunk_set_id 열만 제외),
  중단 시 되돌림·재적재 동일성을 확인한다. 현재 코드의 원문 릴리스 ID는 db.py 해시가 들어가 기존 ID와 다를 수 있다.
- 결과는 원문 릴리스(현재 코드의 ID)와 청킹 묶음(기존 묶음 ID) 각각의 실행 기록(out/verification_runs/...)에 새 실행으로 남긴다.
"""
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
import fingerprint as fpm  # noqa: E402
import run_records as rr  # noqa: E402

MAIN_DSN = db.dsn()
TX_DSN = MAIN_DSN.rsplit('/', 1)[0] + '/civilai_rag_tx'
REL, CS = ch.DEFAULT_RELEASE, 'cs-37f81b5cfb1b-46f4f035c0fa'


def main():
    tag = time.strftime('%Y%m%dT%H%M%S')
    tmp = WORK / 'out/tx_isolated' / tag
    os.environ['RAG_DATABASE_URL'] = TX_DSN
    db.OUT = tmp / 'out'                    # 적재 코드의 파일 출력을 격리 폴더로
    ch.WORK = tmp
    rel_checks, cs_checks = [], []

    def check(lst, name, ok, detail=None):
        lst.append({'name': name, 'kind': 'transaction', 'passed': bool(ok), 'detail': detail})

    main_fp = fpm.fingerprint(MAIN_DSN, REL, CS)
    main_cmp = fpm.fingerprint(MAIN_DSN, REL, CS, ignore_ids=True)
    db.createdb()
    with psycopg.connect(TX_DSN) as c:
        c.execute('drop schema if exists rag_knowledge cascade')   # 격리 DB만 초기화한다
    db.migrate()
    ch.migrate()
    # 원문 릴리스
    rid = db.load()
    fp = fpm.fingerprint(TX_DSN, rid, None)
    check(rel_checks, '격리 DB에 현재 코드로 적재한 원문 릴리스 = 기존 검증 DB 기존 릴리스의 내용(ID 열 제외)',
          fpm.fingerprint(TX_DSN, rid, None, ignore_ids=True)['release_tables'] == main_cmp['release_tables'],
          {'release_id': rid, 'compared_with': REL})
    imp1 = json.loads((db.OUT / rid / 'import_manifest.json').read_text(encoding='utf-8'))
    try:
        db.load(fail_after='source_records')
        failed = False
    except RuntimeError:
        failed = True
    fp2 = fpm.fingerprint(TX_DSN, rid, None)
    check(rel_checks, '원문 적재 중 실패하면 전부 되돌리고 기존 완성본 유지', failed and fp2['release_tables'] == fp['release_tables']
          and fp2['status']['release'] == 'complete', fp2['status'])
    db.load()
    fp3 = fpm.fingerprint(TX_DSN, rid, None)
    imp2 = json.loads((db.OUT / rid / 'import_manifest.json').read_text(encoding='utf-8'))
    with psycopg.connect(TX_DSN) as c:
        n_rel = c.execute('select count(*) from rag_knowledge.releases where release_id=%s', (rid,)).fetchone()[0]
    check(rel_checks, '같은 입력 원문 재적재: 행 수·내용·식별자 동일, 중복 없음', imp1 == imp2 and fp3['release_tables'] == fp['release_tables'] and n_rel == 1)
    # 청킹 묶음
    sid = ch.load(rid)
    fp4 = fpm.fingerprint(TX_DSN, rid, sid)
    check(cs_checks, '격리 DB에 같은 코드로 적재한 청킹 묶음 = 기존 검증 DB 기존 묶음의 내용(ID 열 제외)',
          fpm.fingerprint(TX_DSN, rid, sid, ignore_ids=True)['chunk_tables'] == main_cmp['chunk_tables'], {'chunk_set_id': sid})
    try:
        ch.load(rid, fail_after='chunk_links')
        failed = False
    except RuntimeError:
        failed = True
    fp5 = fpm.fingerprint(TX_DSN, rid, sid)
    check(cs_checks, '청킹 적재 중 실패하면 되돌리고 이전 정상 묶음 유지', failed and fp5['chunk_tables'] == fp4['chunk_tables']
          and fp5['status']['chunk_set'] == 'complete', fp5['status'])
    ch.load(rid)
    fp6 = fpm.fingerprint(TX_DSN, rid, sid)
    check(cs_checks, '같은 입력 청킹 재적재: 행 수·내용 동일, 중복 없음', fp6['chunk_tables'] == fp4['chunk_tables'])
    # 청킹이 있으면 원문 릴리스 재적재는 외래 키로 막히고 아무것도 바뀌지 않는다
    try:
        db.load()
        blocked = False
    except Exception:
        blocked = True
    fp7 = fpm.fingerprint(TX_DSN, rid, sid)
    check(rel_checks, '청킹 묶음이 있으면 원문 재적재가 막히고 원문·청킹 내용 그대로', blocked and fp7['release_tables'] == fp['release_tables']
          and fp7['chunk_tables'] == fp4['chunk_tables'] and fp7['status'] == {'release': 'complete', 'chunk_set': 'complete'})
    main_after = fpm.fingerprint(MAIN_DSN, REL, CS)
    check(rel_checks, '기존 검증 DB는 이 검사 동안 바뀌지 않음', main_after == main_fp)
    check(cs_checks, '기존 검증 DB는 이 검사 동안 바뀌지 않음', main_after == main_fp)
    shutil.rmtree(tmp)                       # 격리 출력은 지운다(같은 내용이 기존 자료 폴더에 있다)
    note = f'격리 DB civilai_rag_tx, 파일 출력은 임시 폴더(검사 후 삭제). 기존 검증 DB·자료 파일은 쓰지 않음'
    # 청킹 코드는 그대로이므로 청킹 쪽 기록은 기존 청킹 묶음 대상에 둔다(격리 DB의 묶음 ID는 sid)
    for target, data_dir, lst in ((rid, WORK / 'out' / rid, rel_checks), (CS, WORK / 'out/chunks' / CS, cs_checks)):
        run = rr.start(target, 'isolated_tx', data_dir if data_dir.exists() else None, note=note + f' 격리 DB의 원문 릴리스 {rid}, 청킹 묶음 {sid}')
        res = {'target_id': target, 'passed': sum(x['passed'] for x in lst), 'failed': sum(not x['passed'] for x in lst),
               'note': '트랜잭션 검사. 검사 개수는 정확도 점수가 아니다.', 'checks': lst, 'run_id': run['meta']['run_id']}
        meta = rr.finish(run, {'verification.json': res}, res['failed'] == 0, {'passed': res['passed'], 'failed': res['failed']})
        print(target, meta['run_id'], meta['status'])
        for x in lst:
            print(('  PASS ' if x['passed'] else '  FAIL ') + x['name'])
    return all(x['passed'] for x in rel_checks + cs_checks)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(0 if main() else 1)
