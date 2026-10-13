"""결합 검색·근거 조회 평가(4단계). 개발(기존 20문)과 독립 확인(새 20문)을 구별한다.

  python -B experiments/retrieval-v1/checks/eval_search.py dev        # 기존 20문: 키워드만·벡터만·결합 비교(개발·회귀)
  python -B experiments/retrieval-v1/checks/eval_search.py freeze     # 최종 설정·코드 해시 고정(새 20문 평가 전에)
  python -B experiments/retrieval-v1/checks/eval_search.py new        # 새 20문: 고정 해시가 같을 때만 실행, 한 번만

결과: out/verification_runs/<청킹 묶음 ID>/<run_id>/. 검색 Recall은 '공종(절)' 단위이며 상위 5개 절에 정답 절이 있는지다.
검사 개수·Recall은 작은 표본의 개발 지표이며 전체 문서 정확도가 아니다. 근거 완성은 coverage.complete가 아니라 사전 필수 근거 목록과 비교한다.
"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK / 'src'))
import embed_index as ei  # noqa: E402
import retrieve as rv  # noqa: E402
import run_records as rr  # noqa: E402

PFX = 'pumsem-2026-errata1:'
DIV = {'공통': 'common', '토목': 'civil', '건축': 'arch', '기계설비': 'mech', '유지관리': 'maint'}
DIV_FULL = {'common': '공통부문', 'civil': '토목부문', 'arch': '건축부문', 'mech': '기계설비부문', 'maint': '유지관리부문'}
FREEZE = WORK / 'eval/freeze_step04.json'


def sid_of(pair):
    return f'{PFX}{DIV[pair[0]]}:{pair[1]}'


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] if xs else None


def section_ranks(res, k=5):
    return [s['section_id'] for s in res['sections'][:k]]


def first_rank(secs, expect):
    for n, s in enumerate(secs, 1):
        if s in expect:
            return n
    return None


# ---------------- 개발: 기존 20문 ----------------
def dev(rt):
    qs = json.loads((WORK / 'eval/dev_questions_2026-10-10.json').read_text(encoding='utf-8'))['questions']
    old = json.loads(Path(str(WORK.parents[1].parent / '_parser-lab-2026-10-10/search_cmp/out/results.json')).read_text(encoding='utf-8'))
    old_by = {r['id']: r for r in old['rows']}
    titles = {r[0]: (r[1], r[2]) for r in rt.conn.execute(
        'select section_id, title, parent_section_id from rag_knowledge.sections where release_id=%s', (rt.reader.rid,)).fetchall()}
    rows, timings = [], []
    for q in qs:
        tasks = q.get('tasks') or [q]
        row = {'id': q['id'], 'text': q['text'], 'intent': q['intent'], 'tasks': []}
        for ti, t in enumerate(tasks):
            query = t.get('query') or q['text']
            spec = t.get('expect_any') or q.get('expect_set') or q.get('expect_all') or []
            expect = {sid_of(p) for p in spec}
            rec = {'query': query, 'expected': sorted(expect), 'modes': {}}
            for mode in (('bm25', 'vector', 'hybrid') if rt.has_vectors else ('bm25',)):
                res = rt.search(query, mode)
                secs = section_ranks(res)
                timings.append(res['timing_ms']['search'])
                m = {'sections_top5': secs, 'chunks_top5': [h['chunk_id'] for h in res['fused'][:5]], 'top_cosine': res['top_cosine'],
                     'top_bm25': res['top_bm25'], 'dropped_duplicates': len(res['dropped'])}
                if q.get('expect_none'):
                    m['recall5'] = None
                elif 'expect_all' in q:
                    m['found'] = len(expect & set(secs))
                    m['of'] = len(expect)
                    m['recall5'] = len(expect & set(secs)) == len(expect)
                elif 'expect_set' in q:
                    m['first_rank'] = first_rank(secs, expect)
                    m['found'] = len(expect & set(secs))
                    m['of'] = len(expect)
                    prim = {sid_of(p) for p in q['expect_primary']}
                    m['primary_in_top5'] = bool(prim & set(secs))
                    m['primary_rank'] = first_rank(secs, prim)
                    m['recall5'] = m['first_rank'] is not None
                else:
                    m['first_rank'] = first_rank(secs, expect)
                    m['recall5'] = m['first_rank'] is not None
                if q.get('metric') == 'list_relevance':
                    def rel(sid):
                        a = titles.get(sid)
                        if not a:
                            return False
                        txt = a[0] + (titles.get(a[1], ('',))[0] if a[1] else '')
                        return any(w in txt for w in ('콘크리트', '레미콘', '타설'))
                    m['relevant_in_top5'] = sum(rel(s) for s in secs)
                rec['modes'][mode] = m
            row['tasks'].append(rec)
        o = old_by.get(q['id'])
        if o:
            run0 = o['runs'][0]
            row['old_bm25_base_rank'] = run0.get('base_rank')
            row['old_note'] = '기존 4,813조각(옛 청킹) BM25 순위. 파싱·청킹·검색이 함께 다른 비교이므로 청킹 효과만의 비교가 아니다'
        rows.append(row)

    # 근거 조회 연결: 근거 정규식 질문
    ev_rows = []
    for q in qs:
        if not q.get('evidence_regex'):
            continue
        query = q['text']
        res = rt.retrieve(query, 'hybrid' if rt.has_vectors else 'bm25')
        ei_secs = {sid_of(p) for p in q['evidence_in']}
        rx = re.compile(q['evidence_regex'])
        in_units, in_ctx, where = False, False, []
        for e in res['evidence']:
            r = e['result']
            for cid, u in r['units'].items():
                if (u['section'] or {}).get('section_id') in ei_secs and rx.search(u['context_text'] + '\n' + u['body_text']):
                    in_units = True
                    where.append(cid)
            if any((r['units'][c]['section'] or {}).get('section_id') in ei_secs and rx.search(r['answer_context']['text']) for c in r['answer_context']['included']):
                in_ctx = True
        ev_rows.append({'id': q['id'], 'regex': q['evidence_regex'], 'in_units': in_units, 'in_answer_context': in_ctx, 'chunks': where[:4],
                        'sections_top3': [e['section_id'] for e in res['evidence']], 'timing_ms': res['timing_ms']})
        timings.append(res['timing_ms']['evidence'])
    return rows, ev_rows, timings


def summarize_dev(rows, ev_rows):
    out = {}
    for mode in [m for m in ('bm25', 'vector', 'hybrid') if m in rows[0]['tasks'][0]['modes']]:
        n = hit = 0
        misses = []
        for r in rows:
            for t in r['tasks']:
                m = t['modes'][mode]
                if m['recall5'] is None:
                    continue
                n += 1
                hit += bool(m['recall5'])
                if not m['recall5']:
                    misses.append(f"{r['id']}:{t['query'][:20]}")
        out[mode] = {'recall5': f'{hit}/{n}', 'misses': misses}
    out['evidence_in_units'] = f"{sum(e['in_units'] for e in ev_rows)}/{len(ev_rows)}"
    out['evidence_in_answer_context'] = f"{sum(e['in_answer_context'] for e in ev_rows)}/{len(ev_rows)}"
    return out


# ---------------- 독립 확인: 새 20문 ----------------
NUM = re.compile(r'\d+(?:\.\d+)?')


def new_eval(rt):
    spec = json.loads((WORK / 'eval/new_questions_2026-10-12.json').read_text(encoding='utf-8'))
    rows, timings = [], []
    for q in spec['questions']:
        query = q['question']
        row = {'id': q['id'], 'category': q['category'], 'question': query, 'interpretation_hold': q.get('interpretation_hold', False)}
        search = {m: rt.search(query, m) for m in ('bm25', 'vector', 'hybrid')}
        res = rt.retrieve(query, 'hybrid')
        timings.append({'search': res['timing_ms']['search'], 'embed_api': res['timing_ms']['embed_api'], 'evidence': res['timing_ms']['evidence']})
        ans = {PFX + s for s in q.get('answer_sections', [])}
        also = {PFX + s for s in q.get('acceptable_also', [])}
        forb_secs = {PFX + s for s in q.get('forbidden_sections', [])}
        for mode, r in search.items():
            secs = section_ranks(r)
            row[f'{mode}_sections_top5'] = secs
            if ans:
                row[f'{mode}_answer_found'] = len(ans & set(secs))
                row[f'{mode}_hit_any'] = bool(ans & set(secs))
        secs = section_ranks(search['hybrid'])
        row['answer_sections'] = sorted(ans)
        if q['category'] == 'list':
            good = ans | also
            row['precision5'] = round(sum(s in good for s in secs) / max(1, len(secs)), 3)
            row['coverage5'] = round(len(ans & set(secs)) / min(5, len(ans)), 3) if ans else None
        elif q['category'] in ('multi_work',):
            row['all_answer_sections_in_top5'] = ans <= set(secs)
        row['forbidden_sections_in_top5'] = sorted(forb_secs & set(secs))
        # 근거 조회
        units, ctx_text, refs, primary_units = {}, '', [], set()
        for i, e in enumerate(res['evidence']):
            r = e['result']
            for cid, u in r['units'].items():
                units.setdefault(cid, u)
                if i == 0:
                    primary_units.add(cid)
            ctx_text += '\n' + r['answer_context']['text']
            refs += r['references']
        req = q.get('required_chunks', [])
        in_units_ = [c for c in req if c in units]
        in_fused = [c for c in req if c in {h['chunk_id'] for h in search['hybrid']['fused']}]
        row['required_chunks'] = req
        row['required_in_units'] = in_units_
        row['required_in_candidates_top20'] = in_fused
        row['required_all_in_units'] = len(in_units_) == len(req) if req else None
        row['required_in_answer_context'] = [c for c in req if f'[근거 {c}]' in ctx_text]
        forb = q.get('forbidden_chunks', [])
        row['forbidden_chunks_in_any_evidence'] = [c for c in forb if c in units]
        row['forbidden_chunks_in_primary_evidence'] = [c for c in forb if c in primary_units]
        row['forbidden_sections_in_evidence'] = sorted({(u['section'] or {}).get('section_id') for u in units.values()} & forb_secs)
        # 수치 문자열(자동 확인, 사람 검수 아님)
        toks = set()
        for k, v in (q.get('expected_values') or {}).items():
            if isinstance(v, str) and k not in ('조건',):
                toks |= set(NUM.findall(v))
        if toks:
            row['value_tokens'] = sorted(toks)
            row['value_tokens_missing_in_context'] = sorted(t for t in toks if t not in ctx_text)
        # 참조
        rr_ = []
        for rf in q.get('required_references', []):
            hit = [x for x in refs if x['edge_id'] == rf['edge_id']]
            ok = bool(hit) and hit[0]['target_status'] == rf['target_status'] and hit[0]['applicability'] == 'unknown' and (
                PFX + rf['target_section'] in {t['section_id'] for t in hit[0]['targets'] + hit[0]['candidates']})
            rr_.append({'edge_id': rf['edge_id'], 'found': bool(hit), 'ok': ok})
        if rr_:
            row['required_references'] = rr_
        # 상태 표시
        st = {}
        for key in (q.get('required_states') or {}):
            if key in units:
                u = units[key]
                st[key] = bool((not u['normal_calculation_basis']) or any(w.get('link_state') not in (None, 'confirmed') for w in u['why_included']))
            else:
                hit = [x for x in refs if x['edge_id'] == key]
                st[key] = bool(hit) and hit[0]['target_status'] in ('partial', 'ambiguous')
        if st:
            row['state_marked'] = st
        row['all_included_normal_calculation_basis'] = all(r['result']['all_included_normal_calculation_basis'] for r in res['evidence']) if res['evidence'] else None
        row['coverage_complete_by_section'] = [e['result']['coverage']['complete'] for e in res['evidence']]
        row['group_target_search'] = res['group_target_search']
        if q['category'] == 'no_data':
            row['top_cosine'] = search['hybrid']['top_cosine']
            row['top_bm25'] = search['hybrid']['top_bm25']
            row['weak_support'] = rv_weak(search['hybrid'])
        rows.append(row)
    return rows, timings


def rv_weak(res):
    """고정 규칙(개발 20문으로 정함): 최상위 코사인이 기준보다 낮으면 근거 약함. 값은 eval/freeze_step04.json."""
    fz = json.loads(FREEZE.read_text(encoding='utf-8')) if FREEZE.exists() else {}
    th = fz.get('weak_support_cosine')
    return None if th is None or res['top_cosine'] is None else bool(res['top_cosine'] < th)


def summarize_new(rows):
    def tally(sel):
        n = len(sel)
        return {'n': n, 'hit_any_top5': sum(bool(r.get('hybrid_hit_any')) for r in sel)}
    ans = [r for r in rows if r['answer_sections']]
    out = {'questions': len(rows), 'with_answer_sections': len(ans),
           'recall5_all': tally(ans), 'recall5_without_hold': tally([r for r in ans if not r['interpretation_hold']]),
           'recall5_hold_only': tally([r for r in ans if r['interpretation_hold']])}
    for mode in ('bm25', 'vector', 'hybrid'):
        out[f'recall5_{mode}'] = f"{sum(bool(r.get(mode + '_hit_any')) for r in ans)}/{len(ans)}"
    req = [r for r in rows if r['required_chunks']]
    out['required_chunks_total'] = sum(len(r['required_chunks']) for r in req)
    out['required_chunks_in_units'] = sum(len(r['required_in_units']) for r in req)
    out['required_chunks_in_answer_context'] = sum(len(r['required_in_answer_context']) for r in req)
    out['questions_with_all_required_in_units'] = f"{sum(bool(r['required_all_in_units']) for r in req)}/{len(req)}"
    out['questions_with_forbidden_in_primary_evidence'] = [r['id'] for r in rows if r['forbidden_chunks_in_primary_evidence']]
    out['questions_with_forbidden_in_any_evidence'] = [r['id'] for r in rows if r['forbidden_chunks_in_any_evidence']]
    out['questions_with_forbidden_sections_in_top5'] = [r['id'] for r in rows if r['forbidden_sections_in_top5']]
    out['value_tokens_missing'] = {r['id']: r['value_tokens_missing_in_context'] for r in rows if r.get('value_tokens_missing_in_context')}
    out['reference_checks'] = {r['id']: [x['ok'] for x in r['required_references']] for r in rows if r.get('required_references')}
    out['state_marked'] = {r['id']: r['state_marked'] for r in rows if r.get('state_marked')}
    out['no_data'] = {r['id']: {'top_cosine': r['top_cosine'], 'weak_support': r['weak_support'],
                                'top5': r['hybrid_sections_top5']} for r in rows if r['category'] == 'no_data'}
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'dev'
    if '--candidates' in sys.argv:       # 후보 수 비교(개발 전용). 고정 설정은 retrieve.CONFIG의 값이다
        rv.CONFIG['candidates_per_method'] = int(sys.argv[sys.argv.index('--candidates') + 1])
        if cmd != 'dev':
            raise SystemExit('--candidates는 dev에서만 쓴다')
    mf = ei.BASE / 'manifest.json'
    ready = mf.exists() and json.loads(mf.read_text(encoding='utf-8')).get('ready')
    if cmd != 'dev' and not ready:
        raise SystemExit('벡터 색인이 ready가 아니므로 freeze·new를 실행하지 않는다(키워드만 평가는 dev)')
    rt = rv.Retriever(vectors=bool(ready))
    if cmd == 'freeze':
        # 개발 20문 결과로 정한 값(최상위 코사인의 약한 근거 기준)을 포함해 설정·코드·입력 해시를 고정한다
        rows, ev_rows, _ = dev(rt)
        tops = []
        for r in rows:
            if r['intent'] != 'list' or r['id'] != 'Q20':
                for t in r['tasks']:
                    tops.append(t['modes']['hybrid']['top_cosine'])
        q20 = next(t['modes']['hybrid']['top_cosine'] for r in rows if r['id'] == 'Q20' for t in r['tasks'])
        positives = [x for x in tops if x is not None]
        th = round(min(positives) - 0.0, 4)
        fz = {'frozen_on': time.strftime('%Y-%m-%dT%H:%M:%S'), 'config_sha256': rv.config_hash(), 'retrieve_code_sha256': rv.code_hash(),
              'evidence_code_sha256': hashlib.sha256((WORK / 'src/evidence.py').read_bytes()).hexdigest(),
              'embed_index_code_sha256': sha_file(WORK / 'src/embed_index.py'), 'vectors_sha256': rt.manifest.get('vectors_parquet_sha256'),
              'new_questions_sha256': sha_file(WORK / 'eval/new_questions_2026-10-12.json'),
              'weak_support_cosine': th, 'weak_support_rule': '개발 20문 중 정답이 있는 질문의 최상위 코사인 최솟값 미만이면 근거 약함(표시만, 검색 결과를 숨기지 않음)',
              'dev_q20_top_cosine': q20, 'new_eval_done': False}
        FREEZE.write_text(json.dumps(fz, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(fz, ensure_ascii=False, indent=1))
        return
    if cmd == 'dev':
        t0 = time.perf_counter()
        rows, ev_rows, timings = dev(rt)
        summ = summarize_dev(rows, ev_rows)
        run = rr.start(ei.CS, 'eval_search_dev', None, note=f"개발·회귀: 기존 20문. 후보 {rv.CONFIG['candidates_per_method']}개/방식. 구현·설정 조정에 사용")
        res = {'record_kind_note': '개발 사례(조정에 사용). 독립 평가 아님', 'vectors_available': rt.has_vectors,
               'vectors_note': None if rt.has_vectors else '벡터 색인이 ready가 아니라 키워드(BM25) 검색만 평가했다', 'summary': summ, 'rows': rows, 'evidence_rows': ev_rows,
               'timing_ms': {'search_median': pct(timings, .5), 'search_p95': pct(timings, .95), 'n': len(timings)},
               'versions': rv.versions(rt), 'api': {'query_embedding_calls': rt.api_calls, 'new_query_vectors': rt.api_new_vectors,
                                                     'query_cache_hits': rt.api_cache_hits}}
        meta = rr.finish(run, {'dev_results.json': res}, True, summ)
        print(json.dumps(summ, ensure_ascii=False, indent=1))
        print('run', meta['run_id'], 'api', res['api'])
    elif cmd == 'new':
        fz = json.loads(FREEZE.read_text(encoding='utf-8'))
        now = {'config_sha256': rv.config_hash(), 'retrieve_code_sha256': rv.code_hash(),
               'evidence_code_sha256': hashlib.sha256((WORK / 'src/evidence.py').read_bytes()).hexdigest(),
               'embed_index_code_sha256': sha_file(WORK / 'src/embed_index.py'), 'vectors_sha256': rt.manifest.get('vectors_parquet_sha256'),
               'new_questions_sha256': sha_file(WORK / 'eval/new_questions_2026-10-12.json')}
        diff = {k: (fz[k], v) for k, v in now.items() if fz[k] != v}
        if diff:
            raise SystemExit(f'고정한 설정·코드·입력과 다름: {sorted(diff)}')
        repeat = fz.get('new_eval_done')
        if repeat and '--allow-repeat' not in sys.argv:
            raise SystemExit('새 20문은 이미 한 번 평가했다. 다시 하려면 --allow-repeat(재평가로 표시됨)')
        rows, timings = new_eval(rt)
        summ = summarize_new(rows)
        run = rr.start(ei.CS, 'eval_search_new', None, note=('재평가(독립 평가 아님)' if repeat else '독립 확인: 새 20문, 고정 설정에서 한 번'))
        res = {'independent_evaluation': not repeat, 'frozen': fz, 'summary': summ, 'rows': rows, 'timings': timings,
               'api': {'query_embedding_calls': rt.api_calls, 'new_query_vectors': rt.api_new_vectors, 'query_cache_hits': rt.api_cache_hits}}
        meta = rr.finish(run, {'new_results.json': res}, True, summ)
        fz['new_eval_done'] = True
        fz['new_eval_run'] = meta['run_id']
        FREEZE.write_text(json.dumps(fz, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(summ, ensure_ascii=False, indent=1))
        print('run', meta['run_id'], 'api', res['api'])
    rt.close()


if __name__ == '__main__':
    main()
