"""4g 평가: 고정한 기대값(eval/expected_04g_*.json)과 실행 결과(runs/<run_id>/)를 대조한다. 모델을 부르지 않는다. 코드 판정만 쓰고 모델 자기 채점은 쓰지 않는다.

  python -B evaluate_4g.py first-20 rep2 rep3        # 결과: eval_4g.json

지표 구분: 후보 검색(풀에 있음) / 모델 선택 / 코드 검증(거부·확인용 강등) / 최종 문맥(누락·혼입)을 구분한다.
- 확정 선택: 검증을 통과한 주·보조 근거이고 상태 표시가 붙지 않은 것(evidence_roles=confirmed)
- 확인용 선택: 고르긴 했으나 상태 표시가 붙은 것(confirmation_only)
- 확인용 문맥: 선택하지 않았지만 구조상 연결돼 확인용으로 보존된 것(confirmation_context)
- 조회로 도달: 선택하지 않았으나 구조 조회로 최종 문맥에 들어온 것
근거 있음은 계산 적용 승인이 아니다(applicability는 항상 unknown).
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
W = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / 'step04g' / 'prep'))
import browse  # noqa: E402

EXP = json.loads((W / 'eval/expected_04g_2026-10-12.json').read_text(encoding='utf-8'))
EX = {e['id']: e for e in EXP['expected']}
PFX = 'pumsem-2026-errata1:'
rt, vs = browse.open_store()
SECOF = {c: ch['section_id'] for c, ch in vs.store.chunk.items()}


def norm(s):
    return re.sub(r'\s+', '', s or '').lower()


def load(run_id, qid):
    f = HERE / 'runs' / run_id / f'{qid}.json'
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else None


def analyze(qid, r):
    e = EX[qid]
    fin = r['final']
    prim = [p['chunk_id'] for p in r.get('validated', {}).get('primary', [])]
    supp = [p['chunk_id'] for p in r.get('validated', {}).get('supporting', [])]
    ctx = set(r.get('final_context_chunks', []))
    roles = fin.get('evidence_roles', {})
    cc = {c['chunk_id'] for c in r.get('confirmation_context', [])}
    pool = {b['chunk_id']: b for b in (r.get('pool_blocks') or {}).values()}
    text = r.get('final_context_value_text', '') or ''
    row = {'id': qid, 'type': e['type'], 'status': fin.get('status'), 'method': r.get('method'), 'status_expected': e['status_expected'],
           'status_acceptable': e['status_acceptable'], 'reasons': [x['rule'] for x in fin.get('reasons', [])],
           'primary': [c.split(':', 1)[-1] for c in prim], 'supporting': [c.split(':', 1)[-1] for c in supp],
           'confirmed': sorted(c.split(':', 1)[-1] for c in fin.get('confirmed_chunks', [])),
           'confirmation_only': sorted(c.split(':', 1)[-1] for c in fin.get('confirmation_only_chunks', [])),
           'confirmation_context': sorted(c.split(':', 1)[-1] for c in cc), 'target_excluded': [x['chunk_id'].split(':', 1)[-1] for x in r.get('target_excluded', [])],
           'absent_terms': r.get('absent_terms'), 'alias_confirmed': r.get('alias_confirmed'),
           'calls': [(c.get('role'), c.get('attempts'), c.get('cost_usd')) for c in r.get('calls', [])], 'query_embedding_calls': r.get('query_embedding_calls'),
           'latency_sec': r.get('latency_sec'), 'n_context_chunks': len(ctx), 'context_chars': len(text)}
    st = fin.get('status')
    row['status_ok'] = st in e['status_acceptable']
    row['status_is_expected'] = st == e['status_expected']
    row['normal_rejected'] = bool(e['type'] in ('value', 'rule_negation', 'rule_reference', 'rule_condition', 'rule_unconfirmed', 'list') and st == 'not_found')
    row['over_hold'] = bool(e['status_expected'] == 'supported' and st == 'needs_confirmation')
    row['promoted'] = bool(e['status_expected'] == 'needs_confirmation' and st == 'supported')
    # 필수 근거
    req = []
    for rc in e.get('required_chunks', []):
        c = rc['chunk_id']
        in_pool = c in pool
        cand = bool(pool.get(c, {}).get('is_candidate'))
        if c in prim or c in supp:
            cls = 'selected_confirmed' if roles.get(c) == 'confirmed' else 'selected_confirmation_only'
        elif c in cc:
            cls = 'confirmation_context'
        elif c in ctx:
            cls = 'reached_by_lookup'
        elif in_pool:
            cls = 'in_pool_not_in_context'
        else:
            cls = 'not_in_pool'
        req.append({'chunk_id': c.split(':', 1)[-1], 'role': rc['role'], 'in_pool': in_pool, 'candidate': cand, 'class': cls, 'in_final_context': c in ctx,
                    'present_unflagged': c in ctx and cls in ('selected_confirmed', 'reached_by_lookup'),
                    'layer_if_missing': (None if c in ctx else ('후보 검색(풀에 없음)' if not in_pool else '모델 선택/코드 검증/최종 읽기(풀에는 있음)'))})
    row['required'] = req
    row['required_in_context'] = sum(1 for x in req if x['in_final_context'])
    row['required_n'] = len(req)
    # 값·문장 토큰
    row['value_tokens_missing'] = [t for t in e.get('required_value_tokens', []) if t not in text]
    row['text_tokens_missing'] = [t for t in e.get('required_text_tokens', []) if norm(t) not in norm(text)]
    # 금지 근거
    fb = set(e.get('forbidden_sections', [])) | set(e.get('list_forbidden_sections', []))
    row['forbidden_primary'] = sorted({SECOF[c].replace(PFX, '') for c in prim + supp if c in SECOF and SECOF[c] in fb})
    row['forbidden_in_context'] = sorted({SECOF[c].replace(PFX, '') for c in ctx if c in SECOF and SECOF[c] in fb})
    # 확정 근거로 들어온 금지(정상 전달): 확정 선택 + 상태가 보류가 아닌 경우
    row['forbidden_confirmed'] = sorted({SECOF[c].replace(PFX, '') for c in fin.get('confirmed_chunks', []) if c in SECOF and SECOF[c] in fb})
    # 참조
    rr = e.get('required_reference')
    if rr:
        refs = r.get('final_references', [])
        pr = r.get('pool_refs', {})
        tgt = set(rr['target_chunks_any'])
        row['reference'] = {'expression': rr['expression'], 'target_in_context': bool(tgt & ctx),
                            'ref_states': [x for x in fin.get('reference_states', [])], 'pool_refs_matching': [v for v in pr.values() if '9-1-1' in (v.get('expression') or '')]}
    # 목록
    if e['type'] == 'list':
        lst = r.get('list') or {}
        inc = set(lst.get('included', []))
        sel_secs = {SECOF[c] for c in prim + supp if c in SECOF}
        got = inc | sel_secs if not lst.get('included') else inc
        req_s, acc, forb = set(e['list_required_sections']), set(e['list_acceptable_additional']), set(e['list_forbidden_sections'])
        row['list'] = {'included_n': len(inc), 'from_primary_n': len(sel_secs), 'used_n': len(got), 'required_n': len(req_s),
                       'required_hit': sorted(s.replace(PFX, '') for s in req_s & got), 'required_missing': sorted(s.replace(PFX, '') for s in req_s - got),
                       'acceptable_extra': sorted(s.replace(PFX, '') for s in got & acc), 'unneeded': sorted(s.replace(PFX, '') for s in got - req_s - acc - forb),
                       'forbidden': sorted(s.replace(PFX, '') for s in got & forb), 'complete_flag': lst.get('complete'), 'list_status': lst.get('status'),
                       'uncertain': [s.replace(PFX, '') for s in lst.get('uncertain', [])], 'catalog_total': lst.get('catalog_total'), 'catalog_shown': lst.get('catalog_shown')}
    # 자료 없음
    if e['type'] == 'no_data':
        row['no_data'] = {'not_found': st == 'not_found', 'primary_empty': not prim and not supp, 'context_empty': not ctx and not cc,
                          'normal_or_confirmation_evidence': bool(fin.get('confirmed_chunks') or fin.get('confirmation_only_chunks') or cc),
                          'diag_excluded': row['target_excluded']}
    # 번호·범위
    if e['type'] == 'scope':
        alts = {x['section_id'] for x in r.get('alternatives', [])}
        row['scope'] = {'method': r.get('method'), 'alternatives_n': len(alts), 'covers_expected': set(e['alternatives_sections']) <= alts,
                        'extra_alternatives': sorted(s.replace(PFX, '') for s in alts - set(e['alternatives_sections'])),
                        'division_choice_required': bool(r.get('division_choice_required')), 'no_primary': not prim,
                        'applies_unknown': all(x.get('applies') == 'unknown' for x in r.get('alternatives', [])), 'model_calls': len(r.get('calls', []))}
    return row


def pass_judgement(row):
    """질문별 판정(고정한 기대 기준). 이유를 함께 남긴다."""
    why = []
    e = EX[row['id']]
    t = row['type']
    if row.get('status') == 'execution_error':
        return False, ['실행 오류']
    if not row['status_ok']:
        why.append(f"상태 {row['status']} (허용 {row['status_acceptable']})")
    if row['forbidden_primary'] or row['forbidden_in_context']:
        why.append(f"금지 근거 혼입 주·보조 {row['forbidden_primary']} 문맥 {row['forbidden_in_context']}")
    if t in ('value', 'rule_negation', 'rule_reference', 'rule_condition', 'rule_unconfirmed'):
        miss = [x['chunk_id'] for x in row['required'] if not x['in_final_context']]
        if miss:
            why.append(f'필수 근거 문맥 누락 {miss}')
        if row['value_tokens_missing']:
            why.append(f"값 토큰 누락 {row['value_tokens_missing']}")
        if row['text_tokens_missing']:
            why.append(f"조건 문장 누락 {row['text_tokens_missing']}")
        if e['id'] == 'G09':
            u = [x for x in row['required'] if x['role'] == 'required_unconfirmed']
            if row['status'] == 'supported' or any(x['class'] in ('selected_confirmed',) for x in u):
                why.append('소속 미확정 설명을 확정 근거로 올림')
        if 'reference' in row and not row['reference']['target_in_context']:
            why.append('참조 대상 내용이 문맥에 없음')
    if t == 'list':
        li = row['list']
        if li['required_missing']:
            why.append(f"목록 필수 누락 {li['required_missing']}")
        if li['forbidden']:
            why.append(f"목록에 금지 항목 {li['forbidden']}")
    if t == 'no_data':
        nd = row['no_data']
        if not nd['not_found'] or not nd['primary_empty'] or not nd['context_empty']:
            why.append(f'자료 없음 처리 미달 {nd}')
    if t == 'scope':
        sc = row['scope']
        if not (sc['covers_expected'] and sc['division_choice_required'] and sc['no_primary'] and sc['applies_unknown']):
            why.append(f'범위 모호 처리 미달 {sc}')
    return (not why), why


def main(run_ids):
    first = run_ids[0]
    rows = []
    not_run = []
    for qid in EX:
        r = load(first, qid)
        if r is None:
            not_run.append(qid)
            continue
        row = analyze(qid, r)
        ok, why = pass_judgement(row)
        row['passed'], row['fail_reasons'] = ok, why
        rows.append(row)
    S = {'n_questions': 20, 'executed': len(rows), 'not_run': not_run}
    by = lambda t: [r for r in rows if r['type'] == t]  # noqa: E731
    vals = [r for r in rows if r['type'] in ('value', 'rule_negation', 'rule_reference', 'rule_condition', 'rule_unconfirmed')]
    req_total = sum(r['required_n'] for r in vals)
    req_ctx = sum(r['required_in_context'] for r in vals)
    cls = Counter(x['class'] for r in vals for x in r['required'])
    S['required_chunks'] = {'questions': len(vals), 'total': req_total, 'in_final_context': req_ctx,
                            'rate': round(req_ctx / req_total, 4) if req_total else None, 'classes': dict(cls),
                            'missing': [(r['id'], x['chunk_id'], x['layer_if_missing']) for r in vals for x in r['required'] if not x['in_final_context']]}
    # 확정 정상 질문 기준(값·규칙·참조·조건; G09 제외)의 필수 포함
    norm_q = [r for r in vals if r['id'] != 'G09']
    S['required_chunks_excluding_unconfirmed_case'] = {'total': sum(r['required_n'] for r in norm_q), 'in_final_context': sum(r['required_in_context'] for r in norm_q)}
    S['status'] = dict(Counter(r['status'] for r in rows))
    S['status_ok'] = [r['id'] for r in rows if r['status_ok']]
    S['status_not_ok'] = [(r['id'], r['status'], r['status_acceptable']) for r in rows if not r['status_ok']]
    S['normal_rejected'] = [r['id'] for r in rows if r['normal_rejected']]
    S['over_hold'] = [(r['id'], r['reasons']) for r in rows if r['over_hold']]
    S['promoted'] = [r['id'] for r in rows if r['promoted']]
    S['forbidden_primary_questions'] = [(r['id'], r['forbidden_primary']) for r in rows if r['forbidden_primary']]
    S['forbidden_context_questions'] = [(r['id'], r['forbidden_in_context']) for r in rows if r['forbidden_in_context']]
    S['forbidden_confirmed_questions'] = [(r['id'], r['forbidden_confirmed']) for r in rows if r['forbidden_confirmed']]
    nd = by('no_data')
    S['no_data'] = {'n': len(nd), 'not_found': [r['id'] for r in nd if r['no_data']['not_found']],
                    'clean_context': [r['id'] for r in nd if r['no_data']['context_empty'] and r['no_data']['primary_empty']],
                    'leak': [(r['id'], r['no_data']) for r in nd if not (r['no_data']['not_found'] and r['no_data']['context_empty'] and r['no_data']['primary_empty'])]}
    ls = by('list')
    S['lists'] = {r['id']: r['list'] for r in ls}
    sc = by('scope')
    S['scope'] = {r['id']: r['scope'] for r in sc}
    S['passed'] = [r['id'] for r in rows if r['passed']]
    S['failed'] = [(r['id'], r['fail_reasons']) for r in rows if not r['passed']]
    S['by_type_passed'] = {t: [sum(1 for r in by(t) if r['passed']), len(by(t))] for t in sorted({r['type'] for r in rows})}
    # 반복
    rep = {}
    for qid in EXP['repeat_risk_cases']['ids']:
        items = []
        for rid in run_ids:
            r = load(rid, qid)
            if r is None:
                items.append({'run': rid, 'executed': False})
                continue
            row = analyze(qid, r)
            items.append({'run': rid, 'executed': True, 'status': row['status'], 'primary': row['primary'], 'supporting': row['supporting'],
                          'confirmed': row['confirmed'], 'confirmation_only': row['confirmation_only'], 'confirmation_context': row['confirmation_context'],
                          'n_context_chunks': row['n_context_chunks'], 'context_chars': row['context_chars'], 'reasons': row['reasons'],
                          'required_in_context': row['required_in_context'], 'required_n': row['required_n'], 'forbidden_in_context': row['forbidden_in_context'],
                          'forbidden_primary': row['forbidden_primary'], 'absent_terms': row['absent_terms'], 'calls': row['calls'],
                          'passed': pass_judgement(row)[0]})
        ex = [i for i in items if i['executed']]
        same = lambda k: all(i[k] == ex[0][k] for i in ex)  # noqa: E731
        rep[qid] = {'runs': items, 'why': EXP['repeat_risk_cases']['why'][qid],
                    'stable': {'status': same('status'), 'primary': same('primary'), 'supporting': same('supporting'), 'confirmed': same('confirmed'),
                               'context_chunks': same('n_context_chunks')},
                    'all_passed': all(i['passed'] for i in ex)}
    S['repeats'] = rep
    # 호출·지연
    led = [json.loads(l) for l in (HERE / 'ledger_4g.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    S['ledger'] = {'rows': len(led), 'attempts': sum(x['attempts'] for x in led), 'cost_usd': round(sum(x['cost_usd'] for x in led), 4),
                   'by_role': dict(Counter(x['role'] for x in led)),
                   'by_run': {rid: {'attempts': sum(x['attempts'] for x in led if x['run_id'] == rid), 'cost_usd': round(sum(x['cost_usd'] for x in led if x['run_id'] == rid), 4)} for rid in run_ids}}
    lat = sorted(r['latency_sec'] for r in rows if r['latency_sec'] is not None)
    S['latency_sec_first_run'] = {'median': lat[len(lat) // 2], 'p90': lat[int(len(lat) * 0.9) - 1], 'max': lat[-1]} if lat else None
    (HERE / 'eval_4g.json').write_text(json.dumps({'summary': S, 'rows': rows}, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for r in rows:
        print(r['id'], r['type'], r['status'], 'PASS' if r['passed'] else 'FAIL ' + '; '.join(r['fail_reasons'])[:260])
    print(json.dumps({k: S[k] for k in ('required_chunks', 'required_chunks_excluding_unconfirmed_case', 'status', 'status_not_ok', 'normal_rejected', 'over_hold', 'promoted',
                                        'forbidden_primary_questions', 'forbidden_context_questions', 'forbidden_confirmed_questions', 'by_type_passed')}, ensure_ascii=False, indent=1)[:3500])
    rt.close()


if __name__ == '__main__':
    main(sys.argv[1:])
