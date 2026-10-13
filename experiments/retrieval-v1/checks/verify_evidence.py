"""근거 조회(src/evidence.py) 검사. 사전 기대값(checks/expected_evidence.json)을 쓴다. 검사 개수는 정확도 점수가 아니다.

  python -B experiments/retrieval-v1/checks/verify_evidence.py

- 실제 사례, 가상 그래프(순환·깊이), 참조 241개 집계, 조회 전후 데이터 불변을 확인한다.
- 결과: out/verification_runs/<청킹 묶음 ID>/<run_id>/ (verification.json, example_lookups.json). 원문·청킹 자료 폴더에는 쓰지 않는다.
- 조회 예제는 검사 실행 기록 폴더에만 남긴다. 기존 자료·검사 기록을 덮어쓰지 않는다.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

import psycopg

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK / 'src'))
sys.path.insert(0, str(WORK / 'checks'))
import db  # noqa: E402
import evidence as ev  # noqa: E402
import fingerprint as fpm  # noqa: E402
import run_records as rr  # noqa: E402

CS, REL = ev.DEFAULT_CS, ev.PINNED[ev.DEFAULT_CS]
OUT = WORK / 'out'


def out_hashes():
    """자료 파일 해시(검사 실행 기록·임시 폴더 제외)."""
    return {str(p.relative_to(OUT)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(OUT.rglob('*')) if p.is_file() and 'verification_runs' not in p.parts and 'tx_isolated' not in p.parts}


def main():
    exp = json.loads((WORK / 'checks/expected_evidence.json').read_text(encoding='utf-8'))
    checks, timings, lookups = [], [], {}

    def check(name, ok, detail=None, kind='real'):
        checks.append({'name': name, 'kind': kind, 'passed': bool(ok), 'detail': detail})

    fp0, h0 = fpm.fingerprint(db.dsn(), REL, CS), out_hashes()
    reader, conn = ev.open_reader(CS)
    cache = {}

    def read(start, depth=1, budget=6000, **kw):
        key = (tuple(start), depth, budget, tuple(sorted(kw.items())))
        if key not in cache:
            t = time.perf_counter()
            cache[key] = reader.read(list(start), depth, budget, **kw)
            timings.append(round((time.perf_counter() - t) * 1000, 1))
        return cache[key]

    def units(r):
        return r['units']

    def inc(r):
        return r['answer_context']['included']

    def ref(r, eid):
        return next((x for x in r['references'] if x['edge_id'] == eid), None)

    def why(r, cid, kind):
        return [w for w in units(r).get(cid, {}).get('why_included', []) if w['kind'] == kind]

    # ---- 버전 확인 ----
    check('조회가 쓰는 청킹 묶음·원문 릴리스가 고정값과 같음',
          (reader.cs, reader.rid) == (CS, REL), {'chunk_set': reader.cs, 'release': reader.rid})
    try:
        ev.Reader(conn, 'cs-248c1cd42357-c074a14622a2')
        refused = False
    except ValueError:
        refused = True
    check('다른 청킹 묶음 ID는 거부', refused)
    with psycopg.connect(db.dsn()) as c2:
        c2.read_only = True
        try:
            c2.execute("update rag_knowledge.chunk_sets set status='failed' where chunk_set_id=%s", (CS,))
            wrote = True
        except psycopg.Error:
            wrote = False
    check('읽기 전용 연결에서는 쓰기가 거부됨', not wrote)

    # ---- 실제 사례 ----
    for case in exp['cases']:
        cid = case['id']
        try:
            run_case(case, read, units, inc, ref, why, check, lookups, reader)
        except Exception as e:                       # 사례 하나의 오류가 전체 검사를 멈추지 않게 한다
            check(f"{cid}: 사례 실행 중 오류 없음", False, repr(e)[:300])

    # ---- 가상 그래프 ----
    for v in exp['virtual_cases']:
        if 'graph' in v:
            g = {k: [{'edge_id': f'{k}->{t}', 'status': 'resolved', 'targets': [t]} for t in ts] for k, ts in v['graph'].items()}
        else:
            g = {k: [{'edge_id': eid, 'status': 'resolved', 'targets': [t] if t else []} for eid, t in es]
                 for k, es in v['graph_edges'].items()}
        r = ev.traverse(v['start'], lambda u: g.get(u, []), v['depth'])
        ok = sorted(r['reads']) == sorted(v['expect_reads'])
        if 'expect_steps' in v:
            ok &= len(r['steps']) == v['expect_steps']
        if 'expect_cut' in v:
            ok &= sorted({c['from_unit'] for c in r['cut']}) == sorted(v['expect_cut'])
        if 'expect_already_read' in v:
            ok &= sum(t['already_read'] for s in r['steps'] for t in s['targets']) == v['expect_already_read']
        check(f"가상 그래프 {v['id']}", ok, {'reads': sorted(r['reads']), 'steps': len(r['steps']), 'cut': len(r['cut'])}, kind='virtual')

    # ---- 두 진입점·재현성(첫 실행 뒤 추가한 기대값. 개발 기준) ----
    ex = exp['extra_checks_added_after_first_run']
    for t in ex['two_entry_points']:
        ra, rb = read(t['a'], 1, 8000), read(t['b'], 1, 8000)
        check(f"두 진입점(표·설명)에서 같은 필수 근거가 조회됨: {t['id']}",
              all(x in units(ra) and x in units(rb) for x in t['same_required']), {'a': sorted(set(t['same_required']) - set(units(ra))),
                                                                              'b': sorted(set(t['same_required']) - set(units(rb)))}, kind='dev_added')
    for start in ex['reproducible']:
        r1 = reader.read([start], 1, 6000)
        rd2, cn2 = ev.open_reader(CS)
        with cn2:
            r2 = rd2.read([start], 1, 6000)
        check(f"같은 입력은 같은 결과(해시·글·ID 동일): {start}", r1['result_sha256'] == r2['result_sha256'] and
              r1['answer_context']['text'] == r2['answer_context']['text'], r1['result_sha256'][:12], kind='dev_added')

    # ---- 다음 단계 평가용 새 질문 20개: 형식과 정답 근거가 실제 자료에 있는지만 확인한다(조회 결과를 정답 조정에 쓰지 않음) ----
    qs = json.loads((WORK / 'eval/new_questions_2026-10-12.json').read_text(encoding='utf-8'))
    comp = {}
    for q_ in qs['questions']:
        comp[q_['category']] = comp.get(q_['category'], 0) + 1
    check('새 질문 20개와 구성(목록 4·규칙 4·품 4·단일 견적 3·여러 공종 3·자료 없음 2)', len(qs['questions']) == 20 and comp == qs['composition'], comp, kind='eval_prep')
    all_chunks = {r[0] for r in conn.execute('select chunk_id from rag_knowledge.chunks where chunk_set_id=%s', (CS,)).fetchall()}
    all_secs = {r[0] for r in conn.execute('select section_id from rag_knowledge.sections where release_id=%s', (REL,)).fetchall()}
    pre = 'pumsem-2026-errata1:'
    miss = []
    for q_ in qs['questions']:
        for k in ('required_chunks', 'forbidden_chunks'):
            miss += [(q_['id'], k, x) for x in q_.get(k, []) if x not in all_chunks]
        for k in ('answer_sections', 'acceptable_also', 'forbidden_sections'):
            miss += [(q_['id'], k, x) for x in q_.get(k, []) if pre + x not in all_secs]
        for rf in q_.get('required_references', []):
            e = conn.execute('select target_status from rag_knowledge.edges where release_id=%s and edge_id=%s', (REL, rf['edge_id'])).fetchone()
            tgt = {r[0] for r in conn.execute("select section_id from rag_knowledge.edge_candidates where release_id=%s and edge_id=%s", (REL, rf['edge_id'])).fetchall()}
            if not e or e[0] != rf['target_status'] or pre + rf['target_section'] not in tgt:
                miss.append((q_['id'], 'reference', rf['edge_id'], e and e[0], sorted(tgt)))
    check('새 질문의 정답 근거 조각·절·참조가 실제 자료에 있음', not miss, miss[:6], kind='eval_prep')
    old_q = Path(WORK).parents[1].parent / '_parser-lab-2026-10-10/search_cmp/questions.json'
    if old_q.exists():
        old = json.loads(old_q.read_text(encoding='utf-8'))
        old_items = old if isinstance(old, list) else old.get('questions', [])
        old_texts = {x['text'] for x in old_items}
        check('새 질문이 기존 20문과 같은 문장이 아님', not ({q_['question'] for q_ in qs['questions']} & old_texts), len(old_texts), kind='eval_prep')
    no_data_hits = {kw: conn.execute('select count(*) from rag_knowledge.chunks where chunk_set_id=%s and (body_text like %s or context_text like %s)',
                                     (CS, '%' + kw + '%', '%' + kw + '%')).fetchone()[0] for kw in ('BIM', '해외')}
    check('자료 없음 질문의 핵심어(BIM·해외)가 조각 본문에 없음', not any(no_data_hits.values()), no_data_hits, kind='eval_prep')

    # ---- 제외 장치 자체 시험: 실제 연결에 쓰인 관계 ID를 제외 목록에 넣으면 조회 경로에서 빠져야 한다 ----
    probe = ev.Reader(conn, CS)
    probe.sup.add('complete-82c206c61e21:rel230')            # 185쪽 표의 기준 연결 관계(시험용으로만 제외)
    rp = probe.read(['t:full-p185-o18870'], 0, 6000)
    check('제외 장치 시험: 제외 목록의 관계는 연결·기준 표시에서 빠짐(시험용 관계 ID)',
          not any(l.get('relation_id') == 'complete-82c206c61e21:rel230' for l in rp['units']['t:full-p185-o18870']['links'])
          and probe.sup_dropped >= 1 and not rp['units']['t:full-p185-o18870']['table']['basis'], probe.sup_dropped, kind='guard')

    # ---- 참조 241개 집계 ----
    agg = exp['aggregate']
    edges = conn.execute("select edge_id, origin, target_status from rag_knowledge.edges where release_id=%s order by edge_id", (REL,)).fetchall()
    start_of = {}
    for e, ch_ in conn.execute("select target_edge_id, chunk_id from rag_knowledge.chunk_links where chunk_set_id=%s and link_type='reference'", (CS,)).fetchall():
        start_of.setdefault(e, []).append(ch_)
    tally = {'existing': {}, 'scan': {}}
    problems = []
    t_all = time.perf_counter()
    for eid, origin, status in edges:
        k = 'existing' if origin == 'existing_reference' else 'scan'
        tally[k][status] = tally[k].get(status, 0) + 1
        starts = start_of.get(eid, [])
        if len(starts) != 1:
            problems.append((eid, 'start_chunk', starts))
            continue
        t = time.perf_counter()
        r = reader.read(starts, 1, 20000, include_cells=False)
        timings.append(round((time.perf_counter() - t) * 1000, 1))
        x = ref(r, eid)
        if not x or x['target_status'] != status or x['origin'] != origin or x['applicability'] != 'unknown':
            problems.append((eid, 'not_traced_or_status_changed', x and x['target_status']))
            continue
        if status in ('ambiguous', 'missing', 'external') and x['followed_chunks']:
            problems.append((eid, 'followed_non_resolved', x['followed_chunks']))
        cand_secs = {c['section_id'] for c in x['candidates']}
        for u in x['followed_chunks']:
            s = (r['units'][u]['section'] or {}).get('section_id')
            if s in cand_secs and s not in {t_['section_id'] for t_ in x['targets']}:
                problems.append((eid, 'candidate_followed', u))
    check('참조 241개 모두 출발 청크 하나와 상태를 추적할 수 있음(의미 검수 아님)', not problems and len(edges) == agg['references_total'],
          {'edges': len(edges), 'existing': tally['existing'], 'scan': tally['scan'], 'problems': problems[:5]})
    check('기존 232건 상태 분포와 추가 후보 9건 구분 유지',
          tally['existing'] == agg['status_existing'] and sum(tally['scan'].values()) == agg['scan'], tally)
    check('ambiguous·missing·external과 후보 역할은 조각으로 따라가지 않음', not [p for p in problems if p[1] in ('followed_non_resolved', 'candidate_followed')])
    # 정상 계산 근거 표시의 일관성: 상태·플래그가 맞지 않는데 true인 단위가 없음
    bad = []
    for r in cache.values():
        for cid, u in r['units'].items():
            should = u['status'] == 'ok' and not any(f in ev.NOT_NORMAL for f in u['flags'])
            if u['normal_calculation_basis'] != should:
                bad.append(cid)
    check('held·소속 미확정·수식 미확정 조각이 정상 계산 근거로 표시되지 않음(조회한 모든 단위)', not bad, bad[:5])
    sup = reader.sup
    leak = [(cid, l['relation_id']) for r in cache.values() for cid, u in r['units'].items() for l in u['links']
            if l.get('relation_id') in sup]
    check('잘못된 길어깨 관계 15건이 어떤 조회 결과의 연결에도 없음', len(sup) == agg['superseded_relations_excluded'] and not leak,
          {'excluded': len(sup), 'leak': leak[:5], 'dropped_during_real_reads': reader.sup_dropped,
           'note': '0이면 청킹 때 이미 쓰지 않아 조회 연결에 없었다는 뜻(제외 장치는 위 시험으로 확인)'})

    # ---- 데이터 불변 ----
    fp1, h1 = fpm.fingerprint(db.dsn(), REL, CS), out_hashes()
    check('조회 전후 DB 지문(원문 릴리스·청킹 묶음)이 같음', fp0 == fp1)
    check('조회 전후 out/ 자료 파일 해시가 같음', h0 == h1, {'files': len(h1)})
    conn.close()

    ts = sorted(timings)
    pct = lambda p: ts[min(len(ts) - 1, int(len(ts) * p))]
    res = {'chunk_set_id': CS, 'release_id': REL, 'passed': sum(c['passed'] for c in checks), 'failed': sum(not c['passed'] for c in checks),
           'note': '고정 청크 ID를 시작점으로 한 근거 조회 검사. 검색 Recall·답변 정확도 평가가 아니다. 검사 개수는 정확도 점수가 아니다.',
           'timing_ms': {'reads': len(ts), 'median': pct(.5), 'p95': pct(.95), 'max': ts[-1],
                         'note': 'DB 읽기와 조립만(API 없음). 로컬 PostgreSQL, 조각 하나당 한 번 호출'},
           'checks': checks}
    return res, lookups


def run_case(case, read, units, inc, ref, why, check, lookups, reader):
    cid = case['id']
    if 'cases' in case and cid == 'shoulder_365_366':
        for sub in case['cases']:
            r = read(sub['start'], 1, 6000)
            u = units(r)
            check(f"{cid} {sub['start'][0]}: 길어깨 표·설명 포함, 앞 인력 표·설명 제외",
                  all(x in u for x in sub['must_units']) and not any(x in u for x in sub['must_not_units']),
                  {'units': list(u)})
            check(f"{cid} {sub['start'][0]}: 교정 번호 {sub['correction_id']}가 표 조각에 연결",
                  (u[sub['start'][0]].get('correction') or {}).get('correction_id') == sub['correction_id'])
        return
    if cid == 'ref_scan_candidates':
        for sub in case['cases']:
            r = read(sub['start'], 1, 20000)
            x = ref(r, sub['edge_id'])
            ok = bool(x) and x['target_status'] == sub['status'] and x['origin'] == sub['origin'] and x['applicability'] == 'unknown'
            if 'start_flags' in sub:
                u = units(r)[sub['start'][0]]
                ok &= all(f in u['flags'] for f in sub['start_flags']) and u['normal_calculation_basis'] == sub['start_normal']
            check(f"{cid} {sub['edge_id']}: origin·상태 유지", ok, x and {k: x[k] for k in ('origin', 'target_status', 'followed_chunks')})
        return
    if cid == 'same_sentence_other_positions':
        sents = set()
        for eid, st in zip(case['edges'], case['starts']):
            r = read([st], 1, 20000)
            x = ref(r, eid)
            sents.add(x['sentence'] if x else None)
            check(f"{cid} {eid}: 각 위치의 참조가 따로 조회됨", x is not None and x['from_chunk'] == st, x and x['from_chunk'])
        check(f"{cid}: 세 위치의 문장이 같고 연결은 서로 다름", len(sents) == 1 and None not in sents, list(sents)[:1])
        return
    if cid == 'depth_limit_real':
        r1 = read(case['start'], 1, case['budget'])
        d1 = case['depth1']
        cut = [x for x in r1['unresolved_references'] if x['kind'] == 'depth_limit' and x['edge_id'] == d1['edge_id']]
        check(f"{cid}: 깊이 1에서 둘째 참조는 깊이 한도로 기록되고 경로가 남음",
              bool(cut) and len(cut[0]['path']) >= 3 and d1['unit_absent'] not in units(r1) and d1['unit_present'] in units(r1), cut and cut[0]['path'])
        r2 = read(case['start'], 2, case['budget'])
        d2 = case['depth2']
        check(f"{cid}: 깊이 2에서는 둘째 참조 대상 조각을 읽음",
              all(ref(r2, e) for e in d2['refs_include']) and d2['unit_present'] in units(r2) and
              not [x for x in r2['unresolved_references'] if x['kind'] == 'depth_limit' and x['edge_id'] == d1['edge_id']])
        lookups[cid] = {'depth1_unresolved': cut, 'depth2_references': [x['edge_id'] for x in r2['references']]}
        return

    r = read(case['start'], case.get('depth', 1), case.get('budget', 6000))
    u, included = units(r), inc(r)
    big = case.get('budget', 6000) >= 6000
    lookups.setdefault(cid, {'start': case['start'], 'depth': case.get('depth', 1), 'budget': case.get('budget', 6000),
                             'included': included, 'excluded': r['excluded'][:12], 'coverage': r['coverage'],
                             'used_est_tokens': r['answer_context']['used_est_tokens'], 'result_sha256': r['result_sha256']})
    if 'must_units' in case:
        miss = [x for x in case['must_units'] if x not in u]
        miss_inc = [x for x in case['must_units'] if big and x in u and x not in included and case.get('budget', 6000) >= 6000]
        check(f"{cid}: 필수 근거 조각이 모두 조회됨", not miss and not miss_inc, {'missing': miss, 'not_in_context': miss_inc})
    if 'must_not_units' in case:
        bad = [x for x in case['must_not_units'] if x in u]
        check(f"{cid}: 붙으면 안 되는 근거가 없음", not bad, bad)
    if 'must_not_division' in case:
        bad = [x for x in u if (u[x]['section'] or {}).get('division') == case['must_not_division']]
        check(f"{cid}: {case['must_not_division']} 근거가 섞이지 않음", not bad, bad)
    for t in case.get('must_text', []):
        got = (u.get(t['unit']) or {}).get(t['field'], '')
        check(f"{cid}: {t['unit']} {t['field']}에 '{t['contains']}'", t['contains'] in got)
    for t in case.get('must_not_text', []):
        got = (u.get(t['unit']) or {}).get(t['field'], '')
        check(f"{cid}: {t['unit']} {t['field']}에 '{t['contains']}'가 없음", t['contains'] not in got)
    for l in case.get('links', []):
        w = why(r, l['unit'], l['kind'])
        check(f"{cid}: {l['unit']} 연결 {l['kind']}={l['state']}", any(x['link_state'] == l['state'] for x in w), w)
    if 'correction' in case:
        c = case['correction']
        check(f"{cid}: 교정 정보({c['correction_id']})가 표 조각에 연결",
              (u[c['unit']].get('correction') or {}).get('correction_id') == c['correction_id'])
    if 'shared_value_count' in case:
        s = case['shared_value_count']
        sv = u[s['unit']]['table']['shared_values']
        check(f"{cid}: 공동값 {s['n']}칸이 원문 식별자·적용 행과 함께 조회됨",
              len(sv) == s['n'] and all(x['cell_node_id'] and x['applies_to_grid_rows'] for x in sv), [x['cell_node_id'] for x in sv])
    if 'heading_node' in case:
        h = case['heading_node']
        hn = u[h['unit']].get('heading_node') or {}
        check(f"{cid}: 순서 번호 없는 교정 제목 노드를 연결로 읽음",
              hn.get('node_id') == h['node_id'] and (hn.get('doc_order') is None) == h['doc_order_is_null'] and
              hn.get('origin') == h['origin'] and hn.get('text') == h['text'], hn)
    if 'table_parts' in case:
        t = case['table_parts']
        parts = u[t['unit']]['table']['parts']
        check(f"{cid}: 원래 표의 모든 부분이 연결되고 선택 부분이 표시됨",
              [p['chunk_id'] for p in parts] == t['parts'] and [p['chunk_id'] for p in parts if p['selected']] == [t['selected']], parts)
    if 'same_context_as' in case:
        s = case['same_context_as']
        rb = read([s['unit_a']], 0, 6000)
        strip = lambda x: [l for l in x.split('\n') if not l.startswith(s['ignore_line_prefix'])]
        check(f"{cid}: 나뉜 두 부분의 머리글·기준 문맥이 같음", strip(units(rb)[s['unit_a']]['context_text']) == strip(u[s['unit_b']]['context_text']))
        a_rows = units(rb)[s['unit_a']]['table']['rows']
        b_rows = u[s['unit_b']]['table']['rows']
        ga = [x for r_ in a_rows for x in (r_['grid_rows'] or [])]
        gb = [x for r_ in b_rows for x in (r_['grid_rows'] or [])]
        check(f"{cid}: 나뉜 표의 행 순서가 이어짐(앞 부분 < 뒤 부분)", ga == sorted(ga) and gb == sorted(gb) and (not ga or not gb or max(ga) < min(gb)), [ga[-1:], gb[:1]])
    if 'table_rows' in case:
        t = case['table_rows']
        rows = u[t['unit']]['table']['rows']
        g = [x for r_ in rows for x in (r_['grid_rows'] or [])]
        check(f"{cid}: 표 {t['n']}행이 원문 순서로 모두 있음", len(rows) == t['n'] and g == sorted(g), len(rows))
    if 'table_rows_each' in case:
        got = {k: len(u[k]['table']['rows']) for k in case['table_rows_each']}
        check(f"{cid}: 교정 표 행 수 유지", got == case['table_rows_each'], got)
    if case.get('body_equals_source_records'):
        bad = []
        for k in case['start']:
            rows = reader.q("""select s.text, s.record->>'section' from rag_knowledge.chunk_sources cs
                               join rag_knowledge.search_records sr on sr.release_id=cs.release_id and sr.search_uid=cs.search_uid
                               join rag_knowledge.source_records s on s.release_id=sr.release_id and s.record_uid=sr.record_uid
                               where cs.chunk_set_id=%s and cs.chunk_id=%s and cs.role='body' order by cs.ord""", reader.cs, k)
            want = '\n'.join(t[len(sec) + 3:] if sec and t.startswith(sec + ' | ') else t for t, sec in rows)
            if want != u[k]['body_text']:
                bad.append(k)
        check(f"{cid}: 조회한 원문 글이 원본 레코드 글과 같음(글자 단위)", not bad, bad)
    if 'flags' in case:
        for k, fl in case['flags'].items():
            check(f"{cid}: {k} 표시 {fl}", all(f in u[k]['flags'] for f in fl), u[k]['flags'])
    if 'normal' in case:
        for k, v in case['normal'].items():
            check(f"{cid}: {k} 정상 계산 근거 표시={v}", u[k]['normal_calculation_basis'] == v)
    if 'all_included_normal' in case:
        check(f"{cid}: 담은 근거 전체가 정상 계산 근거는 아님" if not case['all_included_normal'] else f"{cid}: 모두 정상",
              r['all_included_normal_calculation_basis'] == case['all_included_normal'])
    if 'no_related_kind' in case:
        bad = [(k, w['kind']) for k, v in u.items() for w in v['why_included'] if w['kind'] in case['no_related_kind']]
        check(f"{cid}: 가까운 표·설명을 소속으로 붙이지 않음", not bad, bad)
    if 'basis_state' in case:
        b = case['basis_state']
        check(f"{cid}: 기준 연결 상태 {b['state']} 유지", any(x['state'] == b['state'] for x in u[b['unit']]['table']['basis']), u[b['unit']]['table']['basis'])
    if 'no_confirmed_link_among' in case:
        bad = [k for k in case['no_confirmed_link_among'] if any(w['link_state'] == 'confirmed' for w in u[k]['why_included'] if 'link_state' in w)]
        check(f"{cid}: 후보 주석 표가 확정으로 바뀌지 않음", not bad, bad)
    for rf in case.get('refs', []):
        x = ref(r, rf['edge_id'])
        ok = x is not None and x['target_status'] == rf['status'] and x['applicability'] == rf['applicability']
        if x and 'origin' in rf:
            ok &= x['origin'] == rf['origin']
        if x and 'condition_contains' in rf:
            ok &= rf['condition_contains'] in x['condition_text']
        if x and 'sentence_contains' in rf:
            ok &= rf['sentence_contains'] in x['sentence']
        if x and 'followed_include' in rf:
            ok &= all(f in x['followed_chunks'] for f in rf['followed_include'])
        if x and rf.get('followed_exclude_all'):
            ok &= not x['followed_chunks']
        if x and 'candidates_include' in rf:
            ok &= all(f in {c['section_id'] for c in x['candidates']} for f in rf['candidates_include'])
        if x and 'subitem_node_id' in rf:
            ok &= any(t['subitem_node_id'] == rf['subitem_node_id'] for t in x['targets'])
        if x and 'via_unconfirmed_membership' in rf:
            ok &= x['via_unconfirmed_membership'] == rf['via_unconfirmed_membership']
        check(f"{cid}: 참조 {rf['edge_id']} 상태 {rf['status']}·적용 unknown·조건·출처", ok,
              x and {k: x[k] for k in ('target_status', 'origin', 'followed_chunks', 'via_unconfirmed_membership')})
    for k in case.get('unresolved_kinds', []):
        check(f"{cid}: 미해결 참조 {k}가 이유와 함께 기록됨", any(x['kind'] == k and x.get('detail') for x in r['unresolved_references']),
              [x['kind'] for x in r['unresolved_references']])
    if 'coverage_complete' in case:
        check(f"{cid}: coverage.complete={case['coverage_complete']}", r['coverage']['complete'] == case['coverage_complete'], r['coverage'])
    if 'excluded_reason' in case:
        check(f"{cid}: 제외 사유 {case['excluded_reason']}가 ID와 함께 기록됨",
              any(x['reason'] == case['excluded_reason'] and x['chunk_ids'] for x in r['excluded']), [x['reason'] for x in r['excluded']][:6])
    if 'included_exact' in case:
        check(f"{cid}: 예산 안에는 선택 조각만 담김", included == case['included_exact'], included)
    if 'oversize_for_budget' in case:
        d = u[case['oversize_for_budget']]
        check(f"{cid}: 예산보다 큰 조각은 자르지 않고 과대로 표시",
              d.get('oversize_for_budget') is True and r['answer_context']['over_budget'] and
              d['body_text'] in r['answer_context']['text'] and d['context_text'] in r['answer_context']['text'])
    if 'long_text' in case:
        l = case['long_text']
        d = u[l['unit']]
        x = [e for e in r['references'] if e['from_chunk'] == l['unit']][0]
        pos = d['body_text'].find(x['sentence'])
        check(f"{cid}: 120자 이후에 있는 참조 문장까지 전체 원문을 조회", len(d['body_text']) > 120 and pos > l['sentence_after_char'] and
              d['body_text'] in r['answer_context']['text'], {'len': len(d['body_text']), 'sentence_at': pos})


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    run = rr.start(CS, 'verify_evidence', WORK / 'out/chunks' / CS, note='근거 조회 검사(읽기 전용). 사전 기대 checks/expected_evidence.json')
    try:
        res, lookups = main()
        res['run_id'] = run['meta']['run_id']
        meta = rr.finish(run, {'verification.json': res, 'example_lookups.json': lookups}, res['failed'] == 0,
                         {'passed': res['passed'], 'failed': res['failed']})
    except BaseException as e:
        rr.fail(run, e)
        raise
    for x in res['checks']:
        print(('PASS ' if x['passed'] else 'FAIL ') + x['name'] + ('' if x['passed'] or not x['detail'] else f"  -> {str(x['detail'])[:200]}"))
    print('timing', res['timing_ms'])
    print('run', meta['run_id'], meta['status'], res['passed'], res['failed'])
    sys.exit(0 if meta['status'] == 'passed' else 1)
