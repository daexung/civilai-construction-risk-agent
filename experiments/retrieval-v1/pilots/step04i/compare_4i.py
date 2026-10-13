"""4i 비교 집계: 네 방식(가·나·다·라)의 재생 결과(runs/<방식>-<집합>/)를 같은 기준으로 집계한다. 모델·임베딩 호출 0. 새 결과를 만들지 않고 읽기만 한다.

  python -B compare_4i.py        # 결과: compare_4i.json
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
WORK = HERE.parents[1]
METHODS = ['ga', 'na', 'da', 'ra']
SETS = ['60', 'g20', 'dev', 'g09']
H4 = WORK / 'pilots/step04h/runs'
NO_DATA = {'60': ['Q20', 'N19', 'N20', 'V19', 'V20'], 'g20': ['4g_G15', '4g_G16', '4g_G17', '4g_G18'],
           'dev': ['E04', 'E05', 'E06', 'F04', 'F05', 'H3']}
OTHER_HOLD = {'unconfirmed_chunk', 'attribution_unconfirmed', 'reference_unresolved', 'rejected_primary_item', 'rows_rejected', 'supporting_rejected',
              'budget_required', 'list_incomplete', 'list_scope_unverified', 'list_from_section_catalog', 'negation_unverified', 'confirmation_context_unconfirmed',
              'unselected_unconfirmed_related', 'review_material_retained', 'model_missing', 'no_primary', 'division_choice_required', 'competing_alternative',
              'query_rewritten'}


def load(method, which, qid):
    f = HERE / 'runs' / f'{method}-{which}' / f'{qid}.json'
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else None


def ids_of(which):
    return sorted(p.stem for p in (HERE / 'runs' / f'ga-{which}').glob('*.json') if p.stem != 'summary')


def sig(r):
    f = r['final']
    return {'status': f.get('status'), 'primary': sorted(p['chunk_id'] for p in r.get('validated', {}).get('primary', [])),
            'supporting': sorted(p['chunk_id'] for p in r.get('validated', {}).get('supporting', [])),
            'confirmed': sorted(f.get('confirmed_chunks', [])), 'confirmation_only': sorted(f.get('confirmation_only_chunks', [])),
            'answer': sorted(f.get('answer_evidence_chunks', [])), 'review': sorted(f.get('review_chunks', [])),
            'context': sorted(r.get('final_context_chunks', [])), 'reasons': sorted(x['rule'] for x in f.get('reasons', [])),
            'absent': r.get('absent_terms')}


def main():
    out = {'methods': {}, 'baseline_reproduction': {}, 'changed_cases': [], 'no_data': {}, 'over_hold': {}, 'other_holds_kept': {}, 'coverage': {}}
    # ---- 재생 범위·미실행·외부 호출
    for m in METHODS:
        cov = {}
        for s in SETS:
            sm = HERE / 'runs' / f'{m}-{s}' / 'summary.json'
            cov[s] = json.loads(sm.read_text(encoding='utf-8')) if sm.exists() else None
        out['coverage'][m] = cov
    # ---- 기준선 재현(가 vs 4h 최종)
    base_map = {'60': lambda q: H4 / 'final-60' / f'{q}.json', 'g20': lambda q: H4 / 'final-g20' / f'{q}.json', 'dev': lambda q: H4 / 'final-dev' / f'{q}.json'}
    bad = []
    nchk = 0
    for s, fn in base_map.items():
        for q in ids_of(s):
            f4 = fn(q)
            if not f4.exists():
                if s == 'dev':
                    # 4h 개발 대조(H1·H2·H3·E01~E03)는 dev-e/dev-h/final-dev에 있다
                    alt = [H4 / 'dev-h' / f'{q}.json', H4 / 'dev-e' / f'{q}.json']
                    f4 = next((a for a in alt if a.exists()), f4)
                if not f4.exists():
                    bad.append((s, q, '4h 결과 없음'))
                    continue
            a, b = load('ga', s, q), json.loads(f4.read_text(encoding='utf-8'))
            nchk += 1
            if a is None or sig(a) != sig(b):
                bad.append((s, q, [k for k in sig(b) if a is None or sig(a)[k] != sig(b)[k]]))
    g09 = {'4g_G09_first': H4 / 'final-g20' / '4g_G09.json', '4g_G09_rep2': H4 / 'g09-rep2' / '4g_G09.json', '4g_G09_rep3': H4 / 'g09-rep3' / '4g_G09.json'}
    for q, f4 in g09.items():
        a, b = load('ga', 'g09', q), json.loads(f4.read_text(encoding='utf-8'))
        nchk += 1
        if a is None or sig(a) != sig(b):
            bad.append(('g09', q, [k for k in sig(b) if a is None or sig(a)[k] != sig(b)[k]]))
    out['baseline_reproduction'] = {'checked': nchk, 'mismatch': bad}
    # ---- 방식별 집계
    allq = [(s, q) for s in ('60', 'g20', 'dev') for q in ids_of(s)]
    for m in METHODS:
        st = Counter()
        conf_nodata = {}
        for s, q in allq:
            r = load(m, s, q)
            if r is None:
                st['missing'] += 1
                continue
            st[r['final']['status']] += 1
        out['methods'][m] = {'status': dict(st), 'questions': len(allq)}
    # ---- 변화 사례(가 대비)
    ga = {(s, q): load('ga', s, q) for s, q in allq}
    for s, q in allq:
        base = ga[(s, q)]
        for m in METHODS[1:]:
            r = load(m, s, q)
            if r is None or base is None:
                continue
            a, b = sig(base), sig(r)
            if a['status'] != b['status'] or a['confirmed'] != b['confirmed'] or a['confirmation_only'] != b['confirmation_only'] or a['answer'] != b['answer'] or a['review'] != b['review']:
                out['changed_cases'].append({'set': s, 'id': q, 'method': m, 'ga_status': a['status'], 'status': b['status'],
                                             'ga_confirmed_n': len(a['confirmed']), 'confirmed_n': len(b['confirmed']),
                                             'ga_confirmation_only_n': len(a['confirmation_only']), 'confirmation_only_n': len(b['confirmation_only']),
                                             'ga_answer_n': len(a['answer']), 'answer_n': len(b['answer']), 'ga_review_n': len(a['review']), 'review_n': len(b['review']),
                                             'ga_reasons': a['reasons'], 'reasons': b['reasons'],
                                             'diagnostic_info': [x['rule'] for x in r['final'].get('diagnostic_info', [])],
                                             'question': (r.get('question') or '')[:60]})
    # ---- 자료 없음: 관련 없는 정상·검토용 근거와 잘못된 supported
    for s, ids in NO_DATA.items():
        for q in ids:
            row = {}
            for m in METHODS:
                r = load(m, s, q)
                if r is None:
                    row[m] = None
                    continue
                f = r['final']
                row[m] = {'status': f['status'], 'confirmed_n': len(f.get('confirmed_chunks', [])), 'confirmation_only_n': len(f.get('confirmation_only_chunks', [])),
                          'answer_n': len(f.get('answer_evidence_chunks', [])), 'review_n': len(f.get('review_chunks', [])), 'context_n': len(r.get('final_context_chunks', [])),
                          'reasons': [x['rule'] for x in f.get('reasons', [])]}
            out['no_data'][f'{s}:{q}'] = row
    # ---- 정상 질문의 불필요 보류(기대 supported였던 것: 4h 기준선에서 supported였거나 4g 기대 supported)
    exp = json.loads((WORK / 'eval/expected_04g_2026-10-12.json').read_text(encoding='utf-8'))['expected']
    exp_sup = {'4g_' + e['id'] for e in exp if e['status_expected'] == 'supported'}
    for m in METHODS:
        oh = []
        for s, q in allq:
            r = load(m, s, q)
            if r is None or r['final']['status'] != 'needs_confirmation':
                continue
            b = ga[(s, q)]
            in_exp = q in exp_sup
            if in_exp:
                oh.append((s, q, [x['rule'] for x in r['final']['reasons']]))
        out['over_hold'][m] = oh
    # ---- 다른 보류 규칙 유지: 가에서 다른 보류 사유가 있는 질문이 다른 방식에서도 보류인지
    for m in METHODS[1:]:
        lost = []
        n = 0
        for s, q in allq:
            base = ga[(s, q)]
            r = load(m, s, q)
            if base is None or r is None:
                continue
            reasons = {x['rule'] for x in base['final'].get('reasons', [])}
            if base['final']['status'] == 'needs_confirmation' and (reasons & OTHER_HOLD):
                n += 1
                if r['final']['status'] != 'needs_confirmation':
                    lost.append((s, q, sorted(reasons & OTHER_HOLD), r['final']['status']))
        out['other_holds_kept'][m] = {'checked': n, 'lost': lost}
    (HERE / 'compare_4i.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    print('baseline reproduction', out['baseline_reproduction']['checked'], 'mismatch', out['baseline_reproduction']['mismatch'][:6])
    print('status by method', {m: out['methods'][m]['status'] for m in METHODS})
    print('coverage not_run', {m: {s: (c or {}).get('not_run') for s, c in out['coverage'][m].items()} for m in METHODS})
    print('external blocked', {m: {s: (c or {}).get('external_connection_attempts_blocked') for s, c in out['coverage'][m].items()} for m in METHODS})
    print('changed cases', len(out['changed_cases']))
    for c in out['changed_cases']:
        print(' ', c['set'], c['id'], c['method'], c['ga_status'], '->', c['status'], '| conf', c['ga_confirmed_n'], '->', c['confirmed_n'], '| confOnly', c['ga_confirmation_only_n'], '->', c['confirmation_only_n'],
              '| review', c['ga_review_n'], '->', c['review_n'], '| ga reasons', c['ga_reasons'], '->', c['reasons'])
    print('no_data')
    for k, v in out['no_data'].items():
        print(' ', k, {m: (x['status'], x['confirmed_n'], x['answer_n'], x['review_n']) if x else None for m, x in v.items()})
    print('over_hold', {m: [(q) for s, q, r in v] for m, v in out['over_hold'].items()})
    print('other holds', {m: (v['checked'], v['lost']) for m, v in out['other_holds_kept'].items()})


if __name__ == '__main__':
    main()
