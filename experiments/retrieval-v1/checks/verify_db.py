"""로컬 PostgreSQL에 적재한 릴리스를 원래 입력과 직접 비교한다. 실패 항목이 있으면 종료 코드 1.

  python -B experiments/retrieval-v1/checks/verify_db.py            # 적재 결과 검사
  결과: out/verification_runs/<release_id>/<run_id>/ (재적재·중단 검사는 checks/isolated_tx.py)
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import psycopg

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK / 'src'))
import build_index as bi  # noqa: E402
import db  # noqa: E402
from query import EvidenceStore  # noqa: E402
import run_records as rr  # noqa: E402

checks = []


def check(name, ok, detail=None, kind='data'):
    checks.append({'name': name, 'kind': kind, 'passed': bool(ok), 'detail': detail})


def q(c, sql, *args):
    return c.execute(sql, args).fetchall()


def one(c, sql, *args):
    return c.execute(sql, args).fetchone()[0]


def table_counts(c, rid):
    return {t: one(c, f'select count(*) from rag_knowledge.{t} where release_id=%s', rid) for t in db.TABLES}


def main(reload):
    saved = json.loads((WORK / 'out/input_manifest.json').read_text(encoding='utf-8'))
    rid = saved['release_id']
    imp = json.loads((WORK / 'out' / rid / 'import_manifest.json').read_text(encoding='utf-8'))
    # 1. 원래 파싱 입력 해시
    now = {k: bi.sha256(bi.ROOT / v['path']) for k, v in saved['files'].items()}
    check('파싱 입력과 PDF 해시가 적재 때와 같음', now == {k: v['sha256'] for k, v in saved['files'].items()}, now)
    check('기준 생성·수량과 같음', all(saved['counts'][k] == v for k, v in bi.EXPECTED.items()), saved['counts'])

    store = json.loads(bi.INPUTS['store'].read_text(encoding='utf-8'))
    links = json.loads(bi.INPUTS['links'].read_text(encoding='utf-8'))
    records = [json.loads(x) for x in bi.INPUTS['records'].read_text(encoding='utf-8').splitlines()]
    with psycopg.connect(db.dsn()) as c:
        st = q(c, 'select status, row_counts from rag_knowledge.releases where release_id=%s', rid)
        check('릴리스 상태 complete', st and st[0][0] == 'complete', st)
        check('활성 릴리스는 적재로 바뀌지 않음(채널 없음)', one(c, 'select count(*) from rag_knowledge.release_channels') == 0)
        counts = table_counts(c, rid)
        check('DB 행 수 = 적재 장부 행 수', counts == {t: v['rows'] for t, v in imp['tables'].items()}, counts)

        # 2. 레코드 23,481개: 원래 JSON과 연결 정보가 그대로, 원문 노드로 이어짐
        got = {r[0]: (r[1], r[2]) for r in q(c, 'select record_uid, record, link from rag_knowledge.source_records where release_id=%s', rid)}
        same = sum(1 for r, l in zip(records, links['record_links']) if got.get(r['record_uid']) == (r, l))
        check('레코드 23,481개 원래 JSON·연결 정보 동일', len(got) == 23481 and same == 23481, {'db': len(got), 'same': same})
        check('모든 레코드의 원문 노드가 있고 쪽이 같음', one(c, """select count(*) from rag_knowledge.source_records r
              join rag_knowledge.nodes n on n.release_id=r.release_id and n.node_id=r.source_node_id
              where r.release_id=%s and (n.page = r.page or n.kind='table')""", rid) == 23481)
        miss_cells = one(c, """select count(*) from rag_knowledge.source_records r, jsonb_array_elements_text(coalesce(r.link->'cell_ids','[]')) x
              where r.release_id=%s and not exists (select 1 from rag_knowledge.record_cells k
              where k.release_id=r.release_id and k.record_uid=r.record_uid and k.cell_node_id=x)""", rid)
        check('표 레코드의 칸 연결이 모두 칸 노드로 이어짐', miss_cells == 0, miss_cells)

        # 3. 표 2,328개: 노드·칸·상태 보존
        tabs = {r[0]: r[1:] for r in q(c, """select node_id, page, odl_id, structure->>'calc_status',
              (select count(*) from rag_knowledge.nodes k where k.release_id=t.release_id and k.parent_node_id=t.node_id and k.kind='cell')
              from rag_knowledge.nodes t where t.release_id=%s and t.kind='table'""", rid)}
        ok = all(tabs.get(t['table_id']) == (t['page'], str(t['odl_id']), t['calc_status'], len(t['cells'])) for t in store['tables'])
        check('표 2,328개의 쪽·원시 id·계산 상태·칸 수 동일', len(tabs) == 2328 and ok, len(tabs))
        cells_db = {r[0]: r[1] for r in q(c, "select node_id, text from rag_knowledge.nodes where release_id=%s and kind='cell'", rid)}
        check('칸 82,232개 원문 글 동일', len(cells_db) == 82232 and all(cells_db[x['cell_id']] == x['text_raw']
                                                                  for t in store['tables'] for x in t['cells']))
        held = q(c, "select node_id from rag_knowledge.nodes where release_id=%s and kind='table' and jsonb_array_length(structure->'flags')>0", rid)
        check('보류 표는 758쪽 한 개 그대로', [h[0] for h in held] == ['full-p758-o107176'], held)
        tbl_rec = one(c, """select count(distinct r.record->>'table_id') from rag_knowledge.source_records r
              where r.release_id=%s and r.kind='table'""", rid)
        check('표 레코드가 가리키는 표가 모두 표 노드', one(c, """select count(*) from rag_knowledge.source_records r
              left join rag_knowledge.nodes n on n.release_id=r.release_id and n.node_id=r.record->>'table_id'
              where r.release_id=%s and r.kind='table' and n.node_id is null""", rid) == 0, {'tables_with_records': tbl_rec})

        # 4. 기존 관계 11,823건 보존과 미확정 유지
        rel = {r[0]: (r[1], r[2]) for r in q(c, 'select relation_id, raw, confirmed from rag_knowledge.source_relations where release_id=%s', rid)}
        check('기존 관계 11,823건 원래 JSON 동일', len(rel) == 11823 and all(rel[r['relation_id']][0] == r for r in links['relations']))
        check('관계의 confirmed 값이 원래 값과 같음(미확정이 확정으로 바뀌지 않음)',
              all(rel[r['relation_id']][1] == bool(r['confirmed']) for r in links['relations']),
              {'false': sum(not r['confirmed'] for r in links['relations']), 'true': sum(bool(r['confirmed']) for r in links['relations'])})
        norm = q(c, """select type, from_norm, to_norm, count(*) from rag_knowledge.source_relations where release_id=%s
              group by 1,2,3 order by 1,2,3""", rid)
        check('노드가 아닌 끝점은 원시 값만 두고 노드를 만들지 않음', one(c, """select count(*) from rag_knowledge.source_relations
              where release_id=%s and ((to_norm<>'node' and to_node_id is not null) or (from_norm<>'node' and from_node_id is not null))""", rid) == 0,
              [list(x) for x in norm])
        check('참조 관계의 원래 to는 그대로 null(새 연결은 edges에만)', one(c, """select count(*) from rag_knowledge.source_relations
              where release_id=%s and type='reference' and to_raw is not null""", rid) == 0)

        # 5. 참조 232건
        e = q(c, """select edge_id, target_status, source_confirmed, target_division,
              (select count(*) from rag_knowledge.edge_candidates k where k.release_id=e.release_id and k.edge_id=e.edge_id and k.role='target')
              from rag_knowledge.edges e where release_id=%s and origin='existing_reference'""", rid)
        status = {}
        for _, s, *_ in e:
            status[s] = status.get(s, 0) + 1
        check('기존 참조 232건 모두 처리 상태 기록', len(e) == 232 and sum(status.values()) == 232, status)
        check('기존 참조의 source_confirmed가 원래 값(false)', all(x[2] is False for x in e))
        check('확인·부분 확인만 대상이 있고 모호·없음·외부는 대상이 없음',
              all((x[4] > 0) == (x[1] in ('resolved', 'partial')) for x in e))
        bad = q(c, """select e.edge_id, s.division, e.target_division, n.region, s.first_page
              from rag_knowledge.edges e join rag_knowledge.edge_candidates k on k.release_id=e.release_id and k.edge_id=e.edge_id and k.role='target'
              join rag_knowledge.sections s on s.release_id=k.release_id and s.section_id=k.section_id
              join rag_knowledge.nodes n on n.release_id=s.release_id and n.node_id=s.heading_node_id
              where e.release_id=%s and (n.region<>'body'
                 or (e.target_division is not null and s.division <> replace(e.target_division,'부분','부문')))""", rid)
        check('확정 대상이 목차·표지가 아니고, 명시 부문과 다른 부문에 연결되지 않음', not bad, bad)
        sub = q(c, """select k.edge_id from rag_knowledge.edge_candidates k
              join rag_knowledge.sections s on s.release_id=k.release_id and s.section_id=k.section_id
              join rag_knowledge.nodes n on n.release_id=k.release_id and n.node_id=k.subitem_node_id
              where k.release_id=%s and k.subitem_node_id is not null
                and not (n.doc_order >= s.start_order and n.doc_order < s.end_order and n.division=s.division)""", rid)
        check('하위 항목 대상 노드가 대상 절 범위 안에 있음', not sub, sub)
        check('적용 여부 값을 저장하지 않음', one(c, """select count(*) from information_schema.columns
              where table_schema='rag_knowledge' and column_name in ('applicability','applies')""") == 0)

        # 6. 절 목록
        check('절 식별자는 부문별(같은 번호 다른 부문 분리)', one(c, """select count(*) from (select number, level from rag_knowledge.sections
              where release_id=%s group by 1,2 having count(distinct division)>1) x""", rid) > 0
              and one(c, 'select count(*) from rag_knowledge.sections where release_id=%s', rid)
              == one(c, 'select count(distinct (division, level, number)) from rag_knowledge.sections where release_id=%s', rid))
        check('절 제목 노드가 모두 본문 구역', one(c, """select count(*) from rag_knowledge.sections s join rag_knowledge.nodes n
              on n.release_id=s.release_id and n.node_id=s.heading_node_id where s.release_id=%s and n.region<>'body'""", rid) == 0)
        toc = dict(q(c, 'select match_status, count(*) from rag_knowledge.toc_entries where release_id=%s group by 1', rid))
        check('목차 줄과 본문 절 대조(대상 없는 목차 줄은 기록)', True, toc, kind='info')

        # 7. 무결성
        fk = q(c, """select conrelid::regclass::text, conname from pg_constraint
              where connamespace='rag_knowledge'::regnamespace and contype in ('f','p','u') and not convalidated""")
        check('외래 키·기본 키·고유 제약이 모두 검증 상태', not fk, fk)
        check('nodes 식별자 중복 없음', one(c, 'select count(*) - count(distinct node_id) from rag_knowledge.nodes where release_id=%s', rid) == 0)

        # 7b. 원문 대조 교정(길어깨 세 절)과 다음 청킹 입력
        exp_sh = json.loads((WORK / 'corrections/expected_shoulder.json').read_text(encoding='utf-8'))
        sec_of = dict(q(c, """select r.source_node_id, s.division || ' ' || s.number from rag_knowledge.source_records r
              join rag_knowledge.sections s on s.release_id=r.release_id and s.section_id=r.section_id where r.release_id=%s""", rid))
        sec_of.update(dict(q(c, """select n.source_node_id, s.division || ' ' || s.number from rag_knowledge.search_records n
              join rag_knowledge.sections s on s.release_id=n.release_id and s.section_id=n.section_id where n.release_id=%s""", rid)))
        for e in exp_sh['expected']:
            want = e['section'].rsplit(' ', 1)[0]
            moved = [n for n in e['move_nodes'] if sec_of.get(n) != want]
            stay = {k: [n for n in v if sec_of.get(n) != k] for k, v in e['must_stay'].items()}
            sec = q(c, """select title_raw, first_page, heading_node_id, status from rag_knowledge.sections
                  where release_id=%s and division || ' ' || number = %s""", rid, want)
            check(f"교정 기대: {e['section']} 등록·소속", sec and sec[0][0] == e['section'].split(' ', 1)[1] and sec[0][1] == e['page']
                  and not moved and not any(stay.values()), {'section': sec, 'not_moved': moved, 'wrong_stay': stay}, kind='expected_real')
        check('절 1,359 + 원문 대조 교정 3 = 1,362', one(c, 'select count(*) from rag_knowledge.sections where release_id=%s', rid) == 1362
              and one(c, "select count(*) from rag_knowledge.sections where release_id=%s and status='pdf_correction'", rid) == 3)
        check('목차 1,362줄 모두 본문 절과 대조됨', toc == {'matched': 1362}, toc)
        check('교정 노드는 ODL 항목 번호를 만들지 않음', one(c, """select count(*) from rag_knowledge.nodes where release_id=%s
              and node_id like 'corr:%%' and (odl_id is not null or doc_order is not null)""", rid) == 0
              and one(c, "select count(*) from rag_knowledge.nodes where release_id=%s and node_id like 'corr:%%'", rid) == 6)
        sr = dict(q(c, 'select origin, count(*) from rag_knowledge.search_records where release_id=%s group by 1', rid))
        check('검색 입력 = 원본 23,481(그중 절 제목 교정 30) + 원문 보완 기준 3', sr == {'original': 23451, 'section_corrected': 30, 'added_from_pdf': 3}, sr)
        same = one(c, """select count(*) from rag_knowledge.search_records x join rag_knowledge.source_records r
              on r.release_id=x.release_id and r.record_uid=x.record_uid
              where x.release_id=%s and x.origin='original' and x.text=r.text and x.section_text=r.record->>'section'""", rid)
        check('교정 밖 검색 입력 글은 원본 레코드 글과 같음', same == 23451, same)
        stale = q(c, """select x.search_uid, left(x.text,40) from rag_knowledge.search_records x
              join rag_knowledge.sections s on s.release_id=x.release_id and s.section_id=x.section_id
              where x.release_id=%s and x.origin<>'original' and (left(x.text, length(s.title_raw)+3) <> s.title_raw || ' | '
                 or x.section_text <> s.title_raw or x.text like '%%인력식 소규모장비 포설%%')""", rid)
        check('교정 대상 검색 글의 절 제목이 새 소속과 같고 앞 절 제목이 남지 않음', not stale, stale)
        tail = one(c, """select count(*) from rag_knowledge.search_records x join rag_knowledge.source_records r
              on r.release_id=x.release_id and r.record_uid=x.record_uid
              where x.release_id=%s and x.origin='section_corrected'
                and substr(x.text, length(x.section_text)+1) = substr(r.text, length(r.record->>'section')+1)""", rid)
        check('교정 대상은 절 제목만 바뀌고 나머지 글(값·칸)은 원본과 같음', tail == 30, tail)
        order_ok = one(c, """select bool_and(a.search_idx < b.search_idx) from rag_knowledge.search_records a
              join rag_knowledge.search_records b on b.release_id=a.release_id and b.origin='section_corrected'
              and b.correction_id=a.correction_id where a.release_id=%s and a.origin='added_from_pdf'""", rid)
        check('보완한 기준 (일당)이 그 절의 표 앞에 놓임', order_ok)
        sup = q(c, """select x->>'relation_id', x->>'type' from rag_knowledge.corrections k,
              jsonb_array_elements(k.data->'superseded_relations') x where k.release_id=%s""", rid)
        raw_hit = one(c, """select count(*) from rag_knowledge.source_relations r where r.release_id=%s
              and (r.from_raw = any(%s) or r.to_raw = any(%s))""", rid,
                      [n for e in exp_sh['expected'] for n in e['move_nodes']], [n for e in exp_sh['expected'] for n in e['move_nodes']])
        check('교정 소속과 맞지 않는 원본 관계를 빠짐없이 기록(원본은 보존)', len(sup) == raw_hit, {'recorded': len(sup), 'raw': raw_hit,
              'types': sorted({t for _, t in sup})})

        # 8. 원문 대조로 미리 정한 기대 사례(실제)
        exp = json.loads((WORK / 'checks/expected_references.json').read_text(encoding='utf-8'))
        es = EvidenceStore(c, rid)
        examples = []
        for case in exp['real_cases']:
            rows = q(c, """select e.edge_id, e.from_node_id, e.target_status from rag_knowledge.edges e
                  join rag_knowledge.nodes n on n.release_id=e.release_id and n.node_id=e.from_node_id
                  where e.release_id=%s and e.origin='existing_reference' and n.page=%s and position(%s in replace(e.sentence, E'\\n', ' '))>0""",
                     rid, case['source_page'], case['match_sentence'])
            res = []
            for eid, src, stt in rows:
                ref = next(x for x in es.references_from(src) if x['edge_id'] == eid)
                res.append(ref)
            want_st = case['expect_status']
            ok = bool(res) and all(r['target_status'] in want_st.replace('(', ' ').split() or r['target_status'] == want_st for r in res)
            if 'expect_targets' in case and ok:
                for r in res:
                    if r['target_status'] in ('resolved', 'partial'):
                        got_t = {(t['division'], t['number'], t['page']) for t in r['targets']}
                        ok &= all((t['division'], t['number'], t['page']) in got_t for t in case['expect_targets'])
            if 'expect_candidates_include' in case and ok:
                for r in res:
                    got_c = {(t['division'], t['number']) for t in r['candidates']}
                    ok &= all((t['division'], t['number']) in got_c for t in case['expect_candidates_include'])
            if 'expect_subitem' in case and ok:
                for r in res:
                    sub_ids = [t['subitem_node_id'] for t in r['targets'] if t['subitem_node_id']]
                    if r['target_status'] == 'resolved':
                        pg = q(c, 'select page, text from rag_knowledge.nodes where release_id=%s and node_id=%s', rid, sub_ids[0])
                        ok &= pg[0][0] == case['expect_subitem']['page'] and pg[0][1].startswith(case['expect_subitem']['text'][:5])
            check('기대 사례: ' + case['case'], ok, [{k: r[k] for k in ('edge_id', 'target_status', 'reason', 'targets', 'candidates')} for r in res],
                  kind='expected_real')
            examples.append({'case': case['case'], 'expected': case, 'result': res})
        # 예시 조회: 185~186쪽 공통 6-1-x → 6-1-3을 따라가기
        src = q(c, """select e.from_node_id from rag_knowledge.edges e where e.release_id=%s and e.origin='existing_reference'
              and e.sentence like '%%[공통부문] 6-1-3%%' limit 1""", rid)[0][0]
        walk = es.follow_references([src], max_depth=2)
        examples.append({'case': '참조 따라가기(최대 2단계)', 'start': src, 'walk': walk,
                         'target_section_nodes': [list(x) for x in es.section_nodes('pumsem-2026-errata1:common:6-1-3')][:12]})
    out = {'release_id': rid, 'passed': sum(x['passed'] for x in checks), 'failed': sum(not x['passed'] for x in checks),
           'note': '검사 개수는 정확도 점수가 아니다. 실제 사례(expected_real)와 데이터 보존 검사를 구분한다.', 'checks': checks}
    for x in checks:
        print(('PASS ' if x['passed'] else 'FAIL ') + x['name'])
    return out, examples


if __name__ == '__main__':
    # 검사 결과는 원문 릴리스 자료 폴더에 쓰지 않는다. 실행마다 out/verification_runs/<release_id>/<run_id>/에 저장한다.
    # 재적재·중단 검사는 기존 자료를 지우지 않도록 격리 DB에서 checks/isolated_tx.py로 한다.
    sys.stdout.reconfigure(encoding='utf-8')
    a = argparse.ArgumentParser()
    a.add_argument('--reload', action='store_true', help='사용하지 않음: checks/isolated_tx.py를 쓴다')
    if a.parse_args().reload:
        raise SystemExit('재적재 검사는 격리 DB에서: python -B experiments/retrieval-v1/checks/isolated_tx.py')
    rid = json.loads((WORK / 'out/input_manifest.json').read_text(encoding='utf-8'))['release_id']
    run = rr.start(rid, 'verify_db', WORK / 'out' / rid, note=f'DB {db.dsn().rsplit("/", 1)[-1]}, 재적재 없이')
    try:
        res, examples = main(False)
        res['run_id'] = run['meta']['run_id']
        meta = rr.finish(run, {'verification.json': res, 'example_queries.json': examples}, res['failed'] == 0,
                         {'passed': res['passed'], 'failed': res['failed']})
    except BaseException as e:
        rr.fail(run, e)
        raise
    print('run', meta['run_id'], meta['status'])
    sys.exit(0 if meta['status'] == 'passed' else 1)
