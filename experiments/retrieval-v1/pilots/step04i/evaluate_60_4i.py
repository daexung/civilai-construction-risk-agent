"""4h 평가(4f 평가 도구를 그대로 복사해 확인용 문맥·확정/확인용 역할을 더함): 실행 폴더(runs/<run_id>/)의 결과를 고정 기대값(specs.py)과 대조한다. 모델 호출 없음.

  python -B evaluate_4d.py <run_id> [--merge other_run_id ...]    # 결과: eval_<run_id>.json, 요약은 표준 출력

지표 정의
- 정확히 고른 근거: 검증을 통과한 주 근거(primary)·보조 근거(supporting)에 필수 조각이 있음.
  조회로만 도달: 선택하지 않았지만 구조 연결·참조 조회로 최종 문맥에 들어옴. 선택하지 못함: 최종 문맥에도 없음.
- 잘못된 표에 확인 필요만 붙인 경우: 금지 조각이 주 근거인데 상태가 needs_confirmation이면 해결로 세지 않는다(wrong_primary).
- 목록: list.included 절 집합과 필수·허용·금지 절 비교(조각 수가 아니라 절 단위).
- 정상 질문 거부: 자료 있는 질문의 상태가 not_found. 자료 없음 처리: not_found이고 주 근거 없음.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
WORK = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(WORK / 'pilots/step04d'))
import specs  # noqa: E402

PFX = specs.PFX
NUM = re.compile(r'\d+(?:\.\d+)?')
B4_DEV_UNUSED = WORK / 'out/verification_runs/cs-37f81b5cfb1b-46f4f035c0fa/20261012T123214-eval_selection_dev/dev_selection_results.json'
B4_IND = WORK / 'out/verification_runs/cs-37f81b5cfb1b-46f4f035c0fa/20261012T123241-eval_selection_new/new_selection_results.json'


def load_run(run_id):
    d = HERE / 'runs' / run_id
    return {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in d.glob('*.json') if p.stem != 'meta'}


def sec_of(cid):
    # 조각 ID에서 절은 결과 기록(pool_blocks)에 있다
    return None


def eval_one(spec, r, chunk_section):
    """한 질문 결과 -> 평가 행."""
    fin = r.get('final', {})
    val = r.get('validated', {'primary': [], 'supporting': []})
    prim = [p['chunk_id'] for p in val['primary']]
    supp = [p['chunk_id'] for p in val['supporting']]
    sel = list(dict.fromkeys(prim + supp))
    units = set(r.get('final_context_chunks', []))
    in_ctx = {c for c, v in r.get('final_context_has', {}).items() if v}
    ctx_text = r.get('final_context_value_text', '')
    pool = {v['chunk_id']: a for a, v in r.get('pool_blocks', {}).items()}
    cand = {v['chunk_id'] for a, v in r.get('pool_blocks', {}).items() if v['is_candidate']}
    status = fin.get('status')
    row = {'id': spec['id'], 'set': spec['set'], 'category': spec['category'], 'question': spec['question'], 'method': r.get('method'),
           'status': status, 'allowed': spec['allowed_status'], 'status_allowed': status in spec['allowed_status'],
           'primary': prim, 'supporting': supp, 'n_candidates': (r.get('pool') or {}).get('n_candidates'),
           'reasons': [x['rule'] for x in fin.get('reasons', [])], 'rejected': [x['reason'] for x in r.get('rejected', [])],
           'lookups': [l['kind'] for l in r.get('lookups', [])], 'competing': [c['chunk_id'] for c in fin.get('competing_candidates', [])],
           'cost_usd': r.get('usage_total', {}).get('cost_usd'), 'attempts': r.get('usage_total', {}).get('attempts'),
           'latency_sec': r.get('latency_sec'), 'incomplete': bool(r.get('incomplete'))}
    # 상태 판정
    row['normal_rejected'] = (not spec['no_data']) and status == 'not_found'
    row['no_data_ok'] = (status == 'not_found' and not prim) if spec['no_data'] else None
    row['promoted'] = bool(spec['hold'] and status == 'supported')
    # 절 단위
    prim_secs = {chunk_section.get(c) or r['pool_blocks'].get(pool.get(c), {}).get('section_id') for c in prim}
    sel_secs = {chunk_section.get(c) or r['pool_blocks'].get(pool.get(c), {}).get('section_id') for c in sel}
    ctx_secs = {chunk_section.get(c) or r['pool_blocks'].get(pool.get(c), {}).get('section_id') for c in units}
    ans = set(spec['answer_sections'])
    alt_secs = {x['section_id'] for x in r.get('alternatives', [])}
    row['alternatives'] = sorted(alt_secs)
    row['division_choice_required'] = bool(r.get('division_choice_required'))
    if r.get('list'):
        included = set(r['list'].get('included', []))
        row['list'] = {'included': sorted(included), 'uncertain': r['list'].get('uncertain', []), 'complete': r['list'].get('complete'),
                       'status': r['list'].get('status'), 'catalog_total': r['list'].get('catalog_total')}
        ok_also = set(spec['acceptable_sections'])
        row['list'].update({'required_hit': sorted(ans & included), 'required_missing': sorted(ans - included),
                            'unneeded': sorted(included - ans - ok_also), 'forbidden_included': sorted(set(spec['forbidden_sections']) & included),
                            'uncertain_required': sorted(ans & set(r['list'].get('uncertain', [])))})
    row['sections'] = {'primary': sorted(s for s in prim_secs if s), 'selected': sorted(s for s in sel_secs if s), 'context': sorted(s for s in ctx_secs if s)}
    if ans and spec['section_mode'] == 'any':
        row['section_hit'] = {'primary': bool(ans & prim_secs), 'selected': bool(ans & sel_secs), 'context': bool(ans & ctx_secs)}
        if r.get('list') and r['list'].get('included') is not None:
            row['section_hit']['list'] = bool(ans & set(r['list']['included']))
    elif ans:
        base = (set(r['list'].get('included', [])) if r.get('list') else sel_secs) | alt_secs
        row['section_hit'] = {'primary': len(ans & prim_secs) / len(ans), 'selected': len(ans & sel_secs) / len(ans),
                              'context': len(ans & ctx_secs) / len(ans), 'list_or_selected': len(ans & base) / len(ans)}
    forb_sec = set(spec['forbidden_sections'])
    row['forbidden_sections_primary'] = sorted(forb_sec & prim_secs)
    row['forbidden_sections_in_list'] = sorted(forb_sec & set(r.get('list', {}).get('included', []))) if r.get('list') else []
    # 조각 단위
    req = spec['required_chunks'] if not spec['is_list'] else []
    forb = set(spec['forbidden_chunks'])
    cls = {}
    roles = fin.get('evidence_roles', {})
    cc_ids = {x['chunk_id'] for x in r.get('confirmation_context', [])} | set(r.get('unconfirmed_related_presented', [])) | set(r.get('confirmation_context_labels', []))
    for c in req:
        if c in prim or c in supp:
            cls[c] = 'selected_confirmed' if roles.get(c) == 'confirmed' else 'selected_confirmation_only'
        elif c in cc_ids and c in in_ctx:
            cls[c] = 'confirmation_context'
        elif c in in_ctx:
            cls[c] = 'reached_by_lookup'
        elif c in pool:
            cls[c] = 'in_pool_not_in_context'
        else:
            cls[c] = 'not_in_pool'
    row['required_class'] = cls
    row['required_n'] = len(req)
    row['required_selected'] = sum(1 for v in cls.values() if v.startswith('selected'))
    row['required_confirmed'] = sum(1 for v in cls.values() if v == 'selected_confirmed')
    row['required_confirmation_context'] = sum(1 for v in cls.values() if v == 'confirmation_context')
    row['required_in_context'] = sum(1 for c in req if c in in_ctx)
    row['forbidden_primary'] = sorted(forb & set(prim))
    row['forbidden_in_context'] = sorted(forb & units)
    row['wrong_primary_flagged_only'] = bool(forb & set(prim)) and status == 'needs_confirmation'
    toks = set()
    for k, v in (spec['expected_values'] or {}).items():
        if isinstance(v, str) and k != '조건':
            toks |= set(NUM.findall(v))
    row['value_tokens_missing'] = sorted(t for t in toks if t not in ctx_text) if toks and status != 'not_found' else []
    refs = r.get('final_references', [])
    rr = []
    for rf in spec['required_references']:
        hit = [x for x in refs if x['edge_id'] == rf['edge_id']]
        rr.append({'edge_id': rf['edge_id'], 'found': bool(hit), 'ok': bool(hit) and hit[0]['target_status'] == rf['target_status'] and hit[0]['applicability'] == 'unknown'})
    row['required_references'] = rr
    if spec.get('evidence_regex'):
        row['evidence_regex_in_context'] = bool(re.search(spec['evidence_regex'], ctx_text))
    # 확정 승격 금지 질문: 미확정 근거를 정상 주 근거로 내보내지 않았는가
    if spec['hold']:
        unconf_prim = [c for c in prim if c in r.get('pool_blocks', {}) and False]
        row['hold_ok'] = status == 'needs_confirmation' and not row['forbidden_primary']
    return row


def summarize(rows, specs_by_id):
    S = {}
    n = len(rows)
    S['n_questions'] = n
    S['status'] = dict(Counter(r['status'] for r in rows))
    S['fallback'] = sum(1 for r in rows if r['method'] != 'verified_llm')
    normal = [r for r in rows if not specs_by_id[r['id']]['no_data']]
    S['normal_n'] = len(normal)
    S['normal_rejected'] = [r['id'] for r in normal if r['normal_rejected']]
    nd = [r for r in rows if specs_by_id[r['id']]['no_data']]
    S['no_data_n'] = len(nd)
    S['no_data_ok'] = [r['id'] for r in nd if r['no_data_ok']]
    S['no_data_leak'] = [r['id'] for r in nd if not r['no_data_ok']]
    S['hold_n'] = sum(1 for r in rows if specs_by_id[r['id']]['hold'])
    S['promoted'] = [r['id'] for r in rows if r['promoted']]
    S['status_not_allowed'] = [r['id'] for r in rows if not r['status_allowed']]
    chunkq = [r for r in rows if r['required_n']]
    S['required_chunks_total'] = sum(r['required_n'] for r in chunkq)
    S['required_in_context'] = sum(r['required_in_context'] for r in chunkq)
    S['required_selected'] = sum(r['required_selected'] for r in chunkq)
    S['required_classes'] = dict(Counter(v for r in chunkq for v in r['required_class'].values()))
    S['forbidden_primary_questions'] = [r['id'] for r in rows if r['forbidden_primary']]
    S['forbidden_context_questions'] = [r['id'] for r in rows if r['forbidden_in_context']]
    S['wrong_primary_flagged_only'] = [r['id'] for r in rows if r['wrong_primary_flagged_only']]
    S['value_tokens_missing'] = {r['id']: r['value_tokens_missing'] for r in rows if r['value_tokens_missing']}
    S['references_not_ok'] = [r['id'] for r in rows if any(not x['ok'] for x in r['required_references'])]
    lists = [r for r in rows if 'list' in r]
    S['lists'] = {r['id']: {'req_hit': len(r['list']['required_hit']), 'req_missing': r['list']['required_missing'], 'unneeded': r['list']['unneeded'],
                            'forbidden': r['list']['forbidden_included'], 'uncertain_required': r['list']['uncertain_required'],
                            'complete': r['list']['complete']} for r in lists}
    S['needs_confirmation_normal'] = [r['id'] for r in normal if r['status'] == 'needs_confirmation' and not specs_by_id[r['id']]['hold']]
    S['reasons_needs_confirmation_normal'] = dict(Counter(x for r in normal if r['status'] == 'needs_confirmation' and not specs_by_id[r['id']]['hold'] for x in set(r['reasons'])))
    S['cost_usd'] = round(sum(r['cost_usd'] or 0 for r in rows), 4)
    S['attempts'] = sum(r['attempts'] or 0 for r in rows)
    return S


def b4_rows():
    out = {}
    for path in (B4_DEV, B4_IND):
        for r in json.loads(path.read_text(encoding='utf-8'))['rows']:
            out[r['id']] = r
    return out


def main(run_ids):
    sp_all = {s['id']: s for s in specs.load_specs()}
    # Q05는 작업 질문 3개를 각각 실행한 결과를 한 질문으로 본다
    results = {}
    for rid in run_ids:
        results.update(load_run(rid))
    chunk_section = {}
    rows = []
    for qid, s in sp_all.items():
        if s.get('tasks'):
            part = []
            for k, t in enumerate(s['tasks']):
                key = f'{qid}_{k}'
                if key not in results:
                    continue
                sub = {**s, 'id': key, 'question': t['query'], 'answer_sections': t['answer_sections'], 'section_mode': 'any', 'tasks': None}
                part.append(eval_one(sub, results[key], chunk_section))
            if part:
                merged = {'id': qid, 'set': s['set'], 'category': 'multi', 'question': s['question'], 'tasks': part,
                          'status': 'needs_confirmation' if any(p['status'] == 'needs_confirmation' for p in part) else
                          ('not_found' if all(p['status'] == 'not_found' for p in part) else 'supported'),
                          'method': 'verified_llm', 'allowed': s['allowed_status'], 'required_n': 0, 'required_in_context': 0, 'required_selected': 0,
                          'required_class': {}, 'forbidden_primary': [], 'forbidden_in_context': [], 'wrong_primary_flagged_only': False,
                          'value_tokens_missing': [], 'required_references': [], 'reasons': sorted({x for p in part for x in p['reasons']}),
                          'rejected': [x for p in part for x in p['rejected']], 'lookups': [x for p in part for x in p['lookups']],
                          'competing': [], 'primary': [c for p in part for c in p['primary']], 'supporting': [c for p in part for c in p['supporting']],
                          'cost_usd': sum(p['cost_usd'] or 0 for p in part), 'attempts': sum(p['attempts'] or 0 for p in part),
                          'latency_sec': sum(p['latency_sec'] or 0 for p in part), 'incomplete': False, 'n_candidates': None,
                          'status_allowed': True, 'normal_rejected': False, 'no_data_ok': None, 'promoted': False,
                          'section_hit': {'tasks_hit_primary': sum(1 for p in part if p.get('section_hit', {}).get('primary')),
                                          'tasks_hit_selected': sum(1 for p in part if p.get('section_hit', {}).get('selected')),
                                          'tasks_hit_context': sum(1 for p in part if p.get('section_hit', {}).get('context')),
                                          'tasks_hit_any_route': sum(1 for p in part if any((p.get('section_hit') or {}).get(k) for k in ('primary', 'selected', 'list'))),
                                          'tasks': len(part)},
                          'sections': {}, 'forbidden_sections_primary': [], 'forbidden_sections_in_list': []}
                rows.append(merged)
        elif qid in results:
            rows.append(eval_one(s, results[qid], chunk_section))
    out = {'run_ids': run_ids, 'rows': rows, 'summary': summarize(rows, sp_all)}
    (HERE / ('eval_' + '+'.join(run_ids) + '.json')).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    return out


def show(out):
    sys.stdout.reconfigure(encoding='utf-8')
    for r in out['rows']:
        extra = ''
        if 'list' in r:
            extra = f" list inc={len(r['list']['included'])} req_miss={r['list']['required_missing']} unneeded={r['list']['unneeded']} forb={r['list']['forbidden_included']} unc={len(r['list']['uncertain'])} complete={r['list']['complete']}"
        print(r['id'], r['set'][:6], r['category'][:8], '|', r['status'], '' if r['status_allowed'] else 'NOT_ALLOWED', '| req', f"{r['required_in_context']}/{r['required_n']}",
              'sel', r['required_selected'], '| forbP', r['forbidden_primary'], 'forbCtx', len(r['forbidden_in_context']),
              '| reasons', r['reasons'], '| rej', r['rejected'][:3], extra, '| hit', r.get('section_hit'))
    print(json.dumps(out['summary'], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    ids = [a for a in sys.argv[1:]]
    show(main(ids))
