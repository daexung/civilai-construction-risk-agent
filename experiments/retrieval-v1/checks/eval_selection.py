"""근거 선택(4b) 평가. 개발(기존 두 질문 세트)과 독립 확인(새 4b 질문)을 구별한다.

  python -B experiments/retrieval-v1/checks/eval_selection.py dev      # 기존 20문 + 4단계 새 20문(이제 개발·회귀)
  python -B experiments/retrieval-v1/checks/eval_selection.py freeze   # 코드·설정·질문·벡터 해시 고정(새 4b 질문 평가 전)
  python -B experiments/retrieval-v1/checks/eval_selection.py new      # 새 4b 질문 20개, 고정 해시가 같을 때만, 한 번만

결과: out/verification_runs/<청킹 묶음 ID>/<run_id>/. 질문 ID·정답 파일은 평가에서만 읽는다. 선택 코드는 읽지 않는다.
"""
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK / 'src'))
sys.path.insert(0, str(WORK / 'checks'))
import embed_index as ei  # noqa: E402
import retrieve as rv  # noqa: E402
import run_records as rr  # noqa: E402
import select_evidence as se  # noqa: E402

PFX = 'pumsem-2026-errata1:'
DIVS = {'공통': 'common', '토목': 'civil', '건축': 'arch', '기계설비': 'mech', '유지관리': 'maint'}
FREEZE = WORK / 'eval/freeze_step04b.json'
NUM = re.compile(r'\d+(?:\.\d+)?')


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * p))] if xs else None


def final_sections(res):
    """최종 공종 집합: 목록은 확장 목록, 그 밖은 주 근거·보완 근거 절. 대안 후보는 따로 둔다."""
    if res.get('list'):
        return [s['section_id'] for s in res['sections']], []
    prim = [e['section_id'] for e in res['evidence_sets'] if e['role'] in ('primary', 'complement')]
    alt = [e['section_id'] for e in res['evidence_sets'] if e['role'] == 'alternative']
    return prim, alt


def evidence_view(res):
    """주 근거로 선택한 조각, 읽은 조각 전체, 답변 문맥 글."""
    selected, units, ctx = set(), {}, ''
    for e in res.get('evidence_sets', []):
        if e['role'] not in ('primary', 'complement'):
            continue
        selected |= {c['chunk_id'] for c in e['selected']}
        for cid, u in e['result']['units'].items():
            units.setdefault(cid, u)
        ctx += '\n' + e['result']['answer_context']['text']
    return selected, units, ctx


def dev_old(sel, rt, tk):
    qs = json.loads((WORK / 'eval/dev_questions_2026-10-10.json').read_text(encoding='utf-8'))['questions']
    rows = []
    for q in qs:
        tasks = q.get('tasks') or [q]
        for ti, t in enumerate(tasks):
            query = t.get('query') or q['text']
            spec = t.get('expect_any') or q.get('expect_set') or q.get('expect_all') or []
            expect = {f'{PFX}{DIVS[d]}:{n}' for d, n in spec}
            t0 = time.perf_counter()
            res = sel.run(query)
            ms = (time.perf_counter() - t0) * 1000
            tk.append(ms)
            fin, alt = final_sections(res)
            base = rt.search(query, 'hybrid')
            top5 = [s['section_id'] for s in base['sections'][:5]]
            row = {'set': 'dev_old', 'id': q['id'] + (f':{ti}' if len(tasks) > 1 else ''), 'query': query, 'intent_label': q['intent'],
                   'status': res['status'], 'system_intent': res['intent'], 'final_sections': fin, 'alternatives': alt,
                   'recall5_original': (bool(expect & set(top5)) if expect else None), 'top5_original': top5,
                   'expected': sorted(expect), 'extra_searches': res['extra_searches'], 'relevance': res.get('relevance'),
                   'insufficiency': res.get('insufficiency'), 'ms': round(ms, 1)}
            if expect and not q.get('expect_none'):
                row['final_hit_any'] = bool(expect & set(fin + alt))
                row['final_hit_primary'] = bool(expect & set(fin))
                row['set_ratio'] = round(len(expect & set(fin)) / len(expect), 3) if q.get('expect_all') or q.get('expect_set') or q.get('metric') == 'list_relevance' else None
            if q.get('evidence_regex'):
                ei_secs = {f'{PFX}{DIVS[d]}:{n}' for d, n in q['evidence_in']}
                rx = re.compile(q['evidence_regex'])
                _, units, ctxt = evidence_view(res)
                row['evidence_regex_in_units'] = any((u['section'] or {}).get('section_id') in ei_secs and rx.search(u['context_text'] + '\n' + u['body_text'])
                                                     for u in units.values())
                row['evidence_regex_in_context'] = bool(rx.search(ctxt))
            row['no_data_expected'] = bool(q.get('expect_none'))
            rows.append(row)
    return rows


def dev_n(sel, rt, tk, path='eval/new_questions_2026-10-12.json'):
    qs = json.loads((WORK / path).read_text(encoding='utf-8'))['questions']
    return run_set(sel, rt, tk, qs, 'dev_n4')


def run_set(sel, rt, tk, qs, tag):
    rows = []
    for q in qs:
        query = q['question']
        t0 = time.perf_counter()
        res = sel.run(query)
        ms = (time.perf_counter() - t0) * 1000
        tk.append(ms)
        fin, alt = final_sections(res)
        base = rt.search(query, 'hybrid')
        top5 = [s['section_id'] for s in base['sections'][:5]]
        ans = {PFX + s for s in q.get('answer_sections', [])}
        also = {PFX + s for s in q.get('acceptable_also', [])}
        forb_secs = {PFX + s for s in q.get('forbidden_sections', [])}
        selected, units, ctxt = evidence_view(res)
        row = {'set': tag, 'id': q['id'], 'category': q['category'], 'query': query, 'hold': q.get('interpretation_hold', False),
               'status': res['status'], 'system_intent': res['intent'], 'final_sections': fin, 'alternatives': alt,
               'recall5_original': (bool(ans & set(top5)) if ans else None), 'top5_original': top5, 'answer_sections': sorted(ans),
               'extra_searches': res['extra_searches'], 'relevance': res.get('relevance'), 'insufficiency': res.get('insufficiency'),
               'ms': round(ms, 1)}
        finset = set(fin)
        refset = {r['section_id'] for r in res.get('reference_sections', [])}
        row['reference_sections'] = sorted(refset)
        if ans:
            row['hit_any_final'] = bool(ans & (finset | set(alt) | refset))
            row['answer_recall_final'] = round(len(ans & (finset | refset)) / len(ans), 3)   # 참조 대상 절도 근거로 읽은 공종이다
            row['answer_recall_primary_only'] = round(len(ans & finset) / len(ans), 3)
            row['all_answer_in_final'] = ans <= (finset | refset)
            good = ans | also
            row['precision_final'] = round(len(finset & good) / len(finset), 3) if finset else None
            row['unneeded_sections'] = sorted(finset - good)
        row['forbidden_sections_in_final'] = sorted(forb_secs & finset)
        req = q.get('required_chunks', [])
        if q['category'] == 'list':
            req = []
        row['required_chunks'] = req
        row['required_in_primary_selected'] = [c for c in req if c in selected]
        row['required_in_units'] = [c for c in req if c in units]
        row['required_in_context'] = [c for c in req if f'[근거 {c}]' in ctxt]
        sec_of = {c: (u['section'] or {}).get('section_id') for c, u in units.items()}
        row['required_missing_sections_in_final'] = [c for c in req if c not in units and sel.rt.by_id.get(c, {}).get('section_id') not in finset]
        forb = q.get('forbidden_chunks', [])
        row['forbidden_in_primary_selected'] = [c for c in forb if c in selected]
        row['forbidden_in_units'] = [c for c in forb if c in units]
        toks = set()
        for k, v in (q.get('expected_values') or {}).items():
            if isinstance(v, str) and k not in ('조건',):
                toks |= set(NUM.findall(v))
        if toks and res['status'] != 'not_found':
            row['value_tokens_missing'] = sorted(t for t in toks if t not in ctxt)
        refs = [r for e in res.get('evidence_sets', []) if e['role'] in ('primary', 'complement') for r in e['result']['references']]
        rr_ = []
        for rf in q.get('required_references', []):
            hit = [x for x in refs if x['edge_id'] == rf['edge_id']]
            ok = bool(hit) and hit[0]['target_status'] == rf['target_status'] and hit[0]['applicability'] == 'unknown'
            rr_.append({'edge_id': rf['edge_id'], 'found': bool(hit), 'ok': ok})
        if rr_:
            row['required_references'] = rr_
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
        row['all_selected_normal_basis'] = all(units[c]['normal_calculation_basis'] for c in selected if c in units) if selected else None
        if q['category'] == 'no_data':
            row['emitted_evidence_sections'] = [e['section_id'] for e in res.get('evidence_sets', [])] + (
                [s['section_id'] for s in res['sections']] if res.get('list') else [])
            row['no_data_correct'] = res['status'] == 'not_found' and not row['emitted_evidence_sections']
            row['no_data_wrongly_supported'] = res['status'] == 'supported'
        rows.append(row)
    return rows


def summarize(rows):
    out = {}
    for tag in sorted({r['set'] for r in rows}):
        rs = [r for r in rows if r['set'] == tag]
        s = {'n': len(rs), 'status': dict(Counter(r['status'] for r in rs))}
        ans = [r for r in rs if r.get('answer_sections') or r.get('expected')]
        pos = [r for r in rs if not (r.get('category') == 'no_data' or r.get('no_data_expected'))]
        s['recall5_original'] = f"{sum(bool(r['recall5_original']) for r in ans if r.get('recall5_original') is not None)}/{sum(r.get('recall5_original') is not None for r in ans)}"
        s['final_hit_any'] = f"{sum(bool(r.get('hit_any_final', r.get('final_hit_any'))) for r in ans)}/{len(ans)}"
        s['positives_not_found'] = [r['id'] for r in pos if r['status'] == 'not_found']
        s['positives_needs_confirmation'] = [r['id'] for r in pos if r['status'] == 'needs_confirmation']
        nd = [r for r in rs if r.get('category') == 'no_data' or r.get('no_data_expected')]
        s['no_data'] = {r['id']: r['status'] for r in nd}
        s['no_data_wrongly_supported'] = [r['id'] for r in nd if r['status'] == 'supported']
        if tag != 'dev_old':
            lists = [r for r in rs if r.get('category') == 'list']
            s['list'] = {r['id']: {'recall': r.get('answer_recall_final'), 'precision': r.get('precision_final'), 'n_final': len(r['final_sections']),
                                   'unneeded': len(r.get('unneeded_sections', []))} for r in lists}
            s['list_complete'] = f"{sum(bool(r.get('all_answer_in_final')) for r in lists)}/{len(lists)}"
            nl = [r for r in rs if r.get('required_chunks')]
            tot = sum(len(r['required_chunks']) for r in nl)
            s['required_chunks_in_units'] = f"{sum(len(r['required_in_units']) for r in nl)}/{tot}"
            s['questions_all_required'] = f"{sum(len(r['required_in_units']) == len(r['required_chunks']) for r in nl)}/{len(nl)}"
            s['forbidden_in_primary'] = [r['id'] for r in rs if r.get('forbidden_in_primary_selected')]
            s['forbidden_in_units'] = [r['id'] for r in rs if r.get('forbidden_in_units')]
            s['forbidden_sections_in_final'] = [r['id'] for r in rs if r.get('forbidden_sections_in_final')]
            s['value_tokens_missing'] = {r['id']: r['value_tokens_missing'] for r in rs if r.get('value_tokens_missing')}
            s['reference_ok'] = {r['id']: [x['ok'] for x in r['required_references']] for r in rs if r.get('required_references')}
            s['state_marked'] = {r['id']: r['state_marked'] for r in rs if r.get('state_marked')}
        else:
            ev = [r for r in rs if 'evidence_regex_in_units' in r]
            s['evidence_regex_in_units'] = f"{sum(r['evidence_regex_in_units'] for r in ev)}/{len(ev)}"
            s['evidence_regex_in_context'] = f"{sum(r['evidence_regex_in_context'] for r in ev)}/{len(ev)}"
        s['extra_searches'] = sum(len(r['extra_searches']) for r in rs)
        out[tag] = s
    return out


def versions(sel):
    v = se.versions(sel)
    v['new_questions_04b_sha256'] = sha_file(WORK / 'eval/new_questions_04b_2026-10-12.json')
    return v


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'dev'
    rt = rv.Retriever(embed_queries=True)
    sel = se.Selector(rt)
    tk = []
    if cmd == 'dev':
        note = sys.argv[2] if len(sys.argv) > 2 else ''
        rows = dev_old(sel, rt, tk) + dev_n(sel, rt, tk)
        summ = summarize(rows)
        run = rr.start(ei.CS, 'eval_selection_dev', None, note='4b 개발·회귀: 기존 20문 + 4단계 새 20문(이제 개발 자료). ' + note)
        res = {'role': '개발 사례(조정에 사용). 독립 평가 아님', 'summary': summ, 'rows': rows, 'versions': versions(sel),
               'timing_ms': {'median': pct(tk, .5), 'p95': pct(tk, .95), 'n': len(tk)},
               'api': {'query_embedding_calls': rt.api_calls, 'new_query_vectors': rt.api_new_vectors, 'cache_hits': rt.api_cache_hits}}
        meta = rr.finish(run, {'dev_selection_results.json': res}, True, {k: v['status'] for k, v in summ.items()})
        print(json.dumps(summ, ensure_ascii=False, indent=1))
        print('run', meta['run_id'], 'api', res['api'], 'timing', res['timing_ms'])
    elif cmd == 'freeze':
        v = versions(sel)
        fz = {'frozen_on': time.strftime('%Y-%m-%dT%H:%M:%S'), 'versions': v, 'new_eval_done': False,
              'previous_freeze': {'file': 'eval/freeze_step04.json', 'sha256': sha_file(WORK / 'eval/freeze_step04.json')},
              'note': '4b 최종 설정·코드·질문·벡터 해시. 이 해시가 바뀌면 새 4b 질문 평가를 거부한다.'}
        FREEZE.write_text(json.dumps(fz, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(fz, ensure_ascii=False, indent=1))
    elif cmd == 'new':
        fz = json.loads(FREEZE.read_text(encoding='utf-8'))
        now = versions(sel)
        diff = {k: (fz['versions'][k], now[k]) for k in now if fz['versions'].get(k) != now[k]}
        if diff:
            raise SystemExit(f'고정한 해시와 다름: {sorted(diff)}')
        repeat = fz.get('new_eval_done')
        if repeat and '--allow-repeat' not in sys.argv:
            raise SystemExit('새 4b 질문은 이미 한 번 평가했다(--allow-repeat는 재평가로 표시)')
        qs = json.loads((WORK / 'eval/new_questions_04b_2026-10-12.json').read_text(encoding='utf-8'))['questions']
        rows = run_set(sel, rt, tk, qs, 'independent_04b')
        summ = summarize(rows)
        run = rr.start(ei.CS, 'eval_selection_new', None, note=('재평가(독립 평가 아님)' if repeat else '4b 독립 확인: 고정 설정에서 한 번'))
        res = {'independent_evaluation': not repeat, 'frozen': fz, 'summary': summ, 'rows': rows, 'versions': now,
               'timing_ms': {'median': pct(tk, .5), 'p95': pct(tk, .95), 'n': len(tk)},
               'api': {'query_embedding_calls': rt.api_calls, 'new_query_vectors': rt.api_new_vectors, 'cache_hits': rt.api_cache_hits}}
        meta = rr.finish(run, {'new_selection_results.json': res}, True, {k: v['status'] for k, v in summ.items()})
        fz['new_eval_done'] = True
        fz['new_eval_run'] = meta['run_id']
        FREEZE.write_text(json.dumps(fz, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(summ, ensure_ascii=False, indent=1))
        print('run', meta['run_id'], 'api', res['api'])
    rt.close()


if __name__ == '__main__':
    main()
