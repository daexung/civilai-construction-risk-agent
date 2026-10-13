"""청킹 결과를 로컬 DB에서 원문 릴리스와 직접 비교한다. 실패 항목이 있으면 종료 코드 1.

  python -B experiments/retrieval-v1/checks/verify_chunks.py   # 결과: out/verification_runs/<chunk_set_id>/<run_id>/
"""
import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import psycopg

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK / 'src'))
import chunking as ch  # noqa: E402
import db  # noqa: E402
import run_records as rr  # noqa: E402

checks = []


def check(name, ok, detail=None, kind='data'):
    checks.append({'name': name, 'kind': kind, 'passed': bool(ok), 'detail': detail})


def main(reload):
    rid = ch.DEFAULT_RELEASE
    with psycopg.connect(db.dsn()) as c:
        q = lambda sql, *a: c.execute(sql, a).fetchall()
        one = lambda sql, *a: c.execute(sql, a).fetchone()[0]
        sets = q("select chunk_set_id, status from rag_knowledge.chunk_sets where release_id=%s order by created_at desc", rid)
        d, b, meta = ch.build(c, rid)
        sid = meta['chunk_set_id']
        st = dict(sets).get(sid)
        check('이번 코드·설정·입력의 청킹 묶음이 complete', st == 'complete', sets)
        out = WORK / 'out/chunks' / sid
        man = json.loads((out / 'import_manifest.json').read_text(encoding='utf-8'))

        # 1. 입력: DB와 파일이 같고 원문 릴리스는 그대로
        rel_imp = json.loads((WORK / 'out' / rid / 'import_manifest.json').read_text(encoding='utf-8'))
        now = {t: one(f'select count(*) from rag_knowledge.{t} where release_id=%s', rid) for t in db.TABLES}
        check('원문 릴리스 행 수가 적재 장부와 같음(청킹이 원문을 바꾸지 않음)', now == {t: v['rows'] for t, v in rel_imp['tables'].items()}, now)
        check('입력 해시 = 청킹 묶음에 기록한 입력 해시', d['input_sha256'] == man['input_sha256'] == one(
            'select input_sha256 from rag_knowledge.chunk_sets where chunk_set_id=%s', sid))
        f_rows = [json.loads(x) for x in (WORK / 'out' / rid / 'search_records.jsonl').read_text(encoding='utf-8').splitlines()]
        same = len(f_rows) == len(d['search']) and all(all(fr.get(k) == x[k] for k in d['search_cols']) for fr, x in zip(f_rows, d['search']))
        check('search_records.jsonl 파일과 DB 검색 입력 23,484행이 같음', same and len(d['search']) == 23484, len(f_rows))
        status_now = dict(q("select target_status, count(*) from rag_knowledge.edges where release_id=%s and origin='existing_reference' group by 1", rid))
        check('기존 참조 상태 그대로(210/15/6/1)', status_now == {'resolved': 210, 'partial': 15, 'ambiguous': 6, 'missing': 1}, status_now)

        # 2. 입력 사용처
        used = {r[0] for r in q('select distinct search_uid from rag_knowledge.chunk_sources where chunk_set_id=%s', sid)}
        excl = dict(q('select search_uid, reason from rag_knowledge.chunk_exclusions where chunk_set_id=%s', sid))
        region = dict(q("""select x.search_uid, n.region from rag_knowledge.search_records x join rag_knowledge.nodes n
              on n.release_id=x.release_id and n.node_id=x.source_node_id where x.release_id=%s""", rid))
        no_use = [u for u in region if u not in used and u not in excl]
        check('입력 23,484행 모두 조각 사용처나 제외 사유가 있음', not no_use, {'used': len(used), 'excluded': len(excl), 'none': no_use[:5]})
        check('제외는 목차·앞부분과 부문 표지 쪽만', all(region[u] in ('front', 'cover') for u in excl) and not (used & set(excl)),
              {r: sum(1 for v in excl.values() if v == r) for r in set(excl.values())})
        check('본문 입력은 모두 조각에 사용', all(u in used for u, r in region.items() if r == 'body'))

        # 3. 원문 글 보존: 조각 body = 원문 레코드 글(절 제목 앞머리 제외)을 순서대로
        sx = {x['search_uid']: x for x in d['search']}
        src = defaultdict(list)
        for cid, u, role in q('select chunk_id, search_uid, role from rag_knowledge.chunk_sources where chunk_set_id=%s order by chunk_id, ord', sid):
            src[cid].append((u, role))
        chunks = {r[0]: dict(zip(['kind', 'body', 'text', 'context', 'status', 'section', 'est', 'issues', 'parts'], r[1:])) for r in q(
            """select chunk_id, kind, body_text, text, context_text, status, section_id, est_tokens, issues, part_count
               from rag_knowledge.chunks where chunk_set_id=%s""", sid)}
        bad_body = [cid for cid, x in chunks.items() if x['kind'] != 'work' and x['body'] != '\n'.join(
            ch.body_of(sx[u]) for u, role in src[cid] if role == 'body')]
        check('설명·표 조각의 원문 글이 레코드 글 그대로(자르거나 바꾸지 않음)', not bad_body, bad_body[:5])
        check('조각 글 = 문맥 + 원문(역할 분리 저장)', all(x['text'] == (x['context'] + '\n' + x['body'] if x['body'] else x['context'])
                                                 for x in chunks.values()))
        trec = defaultdict(list)
        for cid, x in chunks.items():
            if x['kind'] == 'table':
                trec[cid.split('#')[0]] += [u for u, role in src[cid] if role == 'body']
        rec_by_table = defaultdict(list)
        for x in d['search']:
            if x['kind'] == 'table' and region[x['search_uid']] == 'body':
                rec_by_table['t:' + d['recs'][x['record_uid']]['record']['table_id']].append(x['search_uid'])
        check('표 레코드는 한 표 조각(나눈 경우 여러 부분)에 원문 순서대로 한 번씩', dict(trec) == dict(rec_by_table))

        # 4. 표 2,328개
        tl = defaultdict(list)
        for cid, node in q("select chunk_id, target_node_id from rag_knowledge.chunk_links where chunk_set_id=%s and link_type='table_node'", sid):
            tl[node].append(cid)
        tables = q("select node_id, region, structure->>'calc_status' from rag_knowledge.nodes where release_id=%s and kind='table'", rid)
        no_chunk = [(t, r) for t, r, _ in tables if not tl.get(t)]
        check('표 2,328개 모두 표 조각이 있거나(본문) 앞부분 제외', len(tables) == 2328 and all(r == 'front' for _, r in no_chunk), no_chunk)
        held = [cid for cid, x in chunks.items() if x['status'] == 'held']
        check('보류 표 상태 유지(758쪽 한 표)', held == ['t:full-p758-o107176'] and '0.215 0.415' in chunks['t:full-p758-o107176']['body'], held)
        unc = {t for t, r, s in tables if s != '구조 표지 없음(값 검증은 별도)'}
        check('표 상태(calc_status)가 보류면 조각도 보류', all(chunks[c]['status'] == 'held' for t in unc for c in tl.get(t, [])))
        bas = q("""select r.to_raw, r.from_raw from rag_knowledge.source_relations r where r.release_id=%s and r.type='basis_of' and r.to_raw is not null
              and r.relation_id <> all(%s)""", rid, sorted(b.superseded))
        miss_b = [t for t, bn in bas if tl.get(t) and not any(
            one("select count(*) from rag_knowledge.chunk_links where chunk_set_id=%s and chunk_id=%s and link_type='basis' and target_node_id=%s", sid, cid, bn)
            and '기준: ' in chunks[cid]['context'] for cid in tl[t])]
        check('기준(…당)이 있는 표는 모든 조각 문맥에 기준이 있고 기준 노드로 연결', not miss_b, {'tables_with_basis': len(bas), 'missing': miss_b[:5]})
        sh = q("""select r.link->'shared_cell_ids', x.search_uid from rag_knowledge.search_records x join rag_knowledge.source_records r
              on r.release_id=x.release_id and r.record_uid=x.record_uid where x.release_id=%s and jsonb_array_length(r.link->'shared_cell_ids')>0""", rid)
        cells = defaultdict(set)
        for cid, cell, role in q('select chunk_id, cell_node_id, role from rag_knowledge.chunk_cells where chunk_set_id=%s', sid):
            cells[(cid, role)].add(cell)
        miss_sh = [u for ids, u in sh if region[u] == 'body' and not any(set(ids) <= cells[(cid, 'shared_value')]
                                                                           for cid in tl.get(d['recs'][sx[u]['record_uid']]['record']['table_id'], []))]
        check('공동값 칸이 모두 조각의 칸 연결(shared_value)로 남음', not miss_sh, {'records_with_shared': len(sh), 'missing': miss_sh[:5]})

        # 5. 길어깨 교정과 제외한 관계
        sup = sorted(b.superseded)
        check('교정과 맞지 않는 관계 15건을 조각 연결에 쓰지 않음', len(sup) == 15 and one(
            'select count(*) from rag_knowledge.chunk_links where chunk_set_id=%s and relation_id = any(%s)', sid, sup) == 0, sup)
        exp = json.loads((WORK / 'checks/expected_chunks.json').read_text(encoding='utf-8'))
        cases = {x['id']: x for x in exp['cases']}
        s = cases['shoulder']
        for t, sec in s['tables'].items():
            cid = 't:' + t
            prev = s['previous_tables_must_not_link'][t]
            title = d['sections'][sec]['title_raw']
            back = one('select count(*) from rag_knowledge.chunk_links where chunk_set_id=%s and chunk_id=%s and target_node_id=%s', sid, cid, prev)
            rules = [r[0] for r in q("""select chunk_id from rag_knowledge.chunk_links where chunk_set_id=%s and link_type='related_table'
                  and target_node_id=%s""", sid, t)]
            ok = (chunks[cid]['section'] == sec and title in chunks[cid]['context'] and '기준: (일당)' in chunks[cid]['context']
                  and '인력식 소규모장비 포설' not in chunks[cid]['text'] and back == 0 and len(rules) == 1
                  and chunks[rules[0]]['section'] == sec and '[주] ①' in chunks[rules[0]]['body'] and '④' in chunks[rules[0]]['body'])
            check(f'기대 사례: 길어깨 {title}', ok, {'chunk': cid, 'back_links_to_previous_table': back, 'rule_chunks': rules}, kind='expected_real')
        # 6. 185쪽
        p = cases['p185_shared']
        cid = 't:' + p['table']
        body = chunks[cid]['body']
        nest = q("select chunk_id from rag_knowledge.chunk_links where chunk_set_id=%s and link_type='parent_table' and target_node_id=%s", sid, p['table'])
        ref = q("""select l.chunk_id, e.target_status, k.section_id from rag_knowledge.chunk_links l join rag_knowledge.edges e
              on e.release_id=l.release_id and e.edge_id=l.target_edge_id join rag_knowledge.edge_candidates k on k.release_id=e.release_id and k.edge_id=e.edge_id
              join rag_knowledge.chunk_sources s on s.chunk_set_id=l.chunk_set_id and s.chunk_id=l.chunk_id
              join rag_knowledge.search_records x on x.release_id=s.release_id and x.search_uid=s.search_uid
              where x.source_node_id='full-p185:n18951' and l.chunk_set_id=%s and l.link_type='reference'""", sid)
        ok = (len(src[cid]) and sum(r == 'body' for _, r in src[cid]) == 7 and body.count('[공동값') >= 5 and '중복 합산하지 않음' in body
              and len(cells[(cid, 'shared_value')]) >= 4 and chunks[cid]['section'] == p['section']
              and [n[0] for n in nest] == ['t:' + p['nested_table']]
              and any(r[1] == 'resolved' and r[2].endswith('common:6-1-3') for r in ref))
        check('기대 사례: 185쪽 공동값·칸 안 표·6-1-3 참조', ok, {'shared_cells': sorted(cells[(cid, 'shared_value')]), 'nested': nest, 'ref': ref},
              kind='expected_real')
        # 7. 555·501·502
        n555 = [u for u, r in src['t:full-p555-o80398'] if r == 'body']
        nt = q("select chunk_id, confirmed from rag_knowledge.chunk_links where chunk_set_id=%s and link_type='note_table_of' and target_node_id='full-p555-o80398' order by 1", sid)
        # 사전 기대값은 555쪽의 주석 표 하나만 적었다. 원본 관계에는 556쪽 세 개를 포함해 넷이 있어 원본 관계와 맞춰 본다
        orig_nt = sorted('t:' + r[0] for r in q("select from_raw from rag_knowledge.source_relations where release_id=%s and type='note_table_of' and to_raw='full-p555-o80398'", rid))
        check('기대 사례: 555쪽 13행 순서 그대로, 주석 표(원본 관계 4개, 사전 기대 1개 포함)는 미확정 후보로 연결',
              len(n555) == 13 and n555 == rec_by_table['t:full-p555-o80398'] and chunks['t:full-p555-o80398']['status'] == 'ok'
              and [x[0] for x in nt] == orig_nt and not any(x[1] for x in nt) and 't:full-p555-o80829' in orig_nt,
              {'linked': nt, 'original_relations': orig_nt}, kind='expected_real')
        cnt = {t: len(rec_by_table['t:' + t]) for t in cases['p501_p502']['tables']}
        check('기대 사례: 501·502쪽 교정 표 행 수 7·7·13과 글 그대로', list(cnt.values()) == [7, 7, 13] and not [c for c in bad_body if '50' in c],
              cnt, kind='expected_real')
        # 8. 참조
        rl = defaultdict(list)
        for cid, e in q("select chunk_id, target_edge_id from rag_knowledge.chunk_links where chunk_set_id=%s and link_type='reference'", sid):
            rl[e].append(cid)
        edges = q('select edge_id, origin, target_status, expression from rag_knowledge.edges where release_id=%s', rid)
        check('기존 참조 232 + 새 후보 9의 출발 조각을 모두 찾음', len(edges) == 241 and all(rl.get(e[0]) for e in edges),
              {'with_chunk': sum(1 for e in edges if rl.get(e[0]))})
        amb = [e for e in edges if e[3] == '9-1-4 4급 기준점 측량']
        cands = one("select count(*) from rag_knowledge.edge_candidates where release_id=%s and edge_id=%s and role='candidate'", rid, amb[0][0])
        sub = q("""select k.subitem_node_id from rag_knowledge.edges e join rag_knowledge.edge_candidates k on k.release_id=e.release_id and k.edge_id=e.edge_id
              where e.release_id=%s and e.expression like '1-2-4 /7.%%' and k.role='target'""", rid)
        check('기대 사례: 참조 상태 구별(모호 9-1-4 후보 3개, 하위 항목 1-2-4/7. 노드까지)',
              amb[0][2] == 'ambiguous' and cands == 3 and sub and sub[0][0], {'ambiguous_candidates': cands, 'subitem': sub}, kind='expected_real')
        conf = q("""select l.relation_id from rag_knowledge.chunk_links l join rag_knowledge.source_relations r
              on r.release_id=l.release_id and r.relation_id=l.relation_id where l.chunk_set_id=%s and l.confirmed and not r.confirmed""", sid)
        check('위치 근거(미확정) 관계를 확정 연결로 바꾸지 않음', not conf, conf[:5])
        unk = q("""select l.chunk_id from rag_knowledge.chunks k join rag_knowledge.chunk_links l on l.chunk_set_id=k.chunk_set_id and l.chunk_id=k.chunk_id
              where k.chunk_set_id=%s and k.status='membership_unconfirmed' and l.link_type='related_table'""", sid)
        check('소속 미확정 설명은 표에 붙이지 않음', not unk, unk[:5])
        # 9. 크기·과대·나눔
        over = [cid for cid, x in chunks.items() if x['est'] > ch.CONFIG['safety_cap_est_tokens'] and x['status'] != 'oversize']
        check('추정 안전 상한을 넘는 조각은 oversize로 표시(자르지 않음)', not over, over)
        parts = defaultdict(list)
        for cid, x in chunks.items():
            if x['kind'] == 'table' and x['parts'] > 1:
                parts[cid.split('#')[0]].append(cid)
        ctx_rep = all(all(chunks[c]['context'].split('\n(표 일부')[0] == chunks[v[0]]['context'].split('\n(표 일부')[0] for c in v)
                      and len(v) == chunks[v[0]]['parts'] for v in parts.values())
        check('나눈 큰 표는 모든 부분에 같은 제목·기준·머리글 문맥을 반복', ctx_rep, {'split_tables': len(parts)})
        big = max((x for x in chunks.items() if x[1]['kind'] == 'table'), key=lambda kv: kv[1]['est'])
        check('가장 큰 표 조각 확인(정보)', True, {'chunk': big[0], 'est_tokens': big[1]['est'], 'parts': big[1]['parts']}, kind='info')
        # 10. 무결성·재현·트랜잭션
        fk = q("""select conrelid::regclass::text, conname from pg_constraint where connamespace='rag_knowledge'::regnamespace
              and contype in ('f','p','u') and not convalidated""")
        check('외래 키·기본 키가 모두 검증 상태', not fk, fk)
        d2, b2, meta2 = ch.build(c, rid)
        r1, r2 = ch.rows(d, b, sid), ch.rows(d2, b2, meta2['chunk_set_id'])
        same = meta2['chunk_set_id'] == sid and {t: db.content_hash(*r1[t]) for t in r1} == {t: db.content_hash(*r2[t]) for t in r2} \
            and {t: v['content_sha256'] for t, v in man['tables'].items()} == {t: db.content_hash(*r1[t]) for t in r1}
        check('같은 입력·설정의 반복 생성: 같은 ID·내용·연결', same)
    res = {'chunk_set_id': sid, 'passed': sum(x['passed'] for x in checks), 'failed': sum(not x['passed'] for x in checks),
           'note': '검사 개수는 정확도 점수가 아니다.', 'checks': checks}
    for x in checks:
        print(('PASS ' if x['passed'] else 'FAIL ') + x['name'] + ('' if x['passed'] else f"  {str(x['detail'])[:300]}"))
    return res


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    a = argparse.ArgumentParser()
    a.add_argument('--reload', action='store_true', help='사용하지 않음: checks/isolated_tx.py를 쓴다')
    if a.parse_args().reload:
        raise SystemExit('재적재 검사는 격리 DB에서: python -B experiments/retrieval-v1/checks/isolated_tx.py')
    # 검사 결과는 청킹 자료 폴더에 쓰지 않는다. 실행마다 out/verification_runs/<chunk_set_id>/<run_id>/에 저장한다
    with psycopg.connect(db.dsn()) as c0:
        sid = ch.build(c0, ch.DEFAULT_RELEASE)[2]['chunk_set_id']
    run = rr.start(sid, 'verify_chunks', WORK / 'out/chunks' / sid, note=f'DB {db.dsn().rsplit("/", 1)[-1]}, 재적재 없이')
    try:
        res = main(False)
        res['run_id'] = run['meta']['run_id']
        meta = rr.finish(run, {'verification.json': res}, res['failed'] == 0, {'passed': res['passed'], 'failed': res['failed']})
    except BaseException as e:
        rr.fail(run, e)
        raise
    print('run', meta['run_id'], meta['status'])
    sys.exit(0 if meta['status'] == 'passed' else 1)
