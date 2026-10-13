"""4f 개발 사례 평가: 4e 개발 사례(E·G)와 4f 개발 사례(F·H)를 결과를 보기 전에 고정한 기대와 실행 결과(runs/<run_id>/)로 대조한다.
독립 평가가 아니다(이전 단계 결과를 본 뒤 만든 개발·회귀 자료). 모델을 부르지 않는다.

  python -B evaluate_dev_4f.py <run_id> [<run_id> ...]     # 같은 질문이 여러 실행에 있으면 앞 실행을 우선. 결과: eval_dev_<첫 run_id>.json
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
WORK = HERE.parents[1]
PFX = 'pumsem-2026-errata1:'


def main(run_ids):
    cases = {}
    for fn in ('pilots/step04e/dev_cases_4e.json', 'pilots/step04f/dev_cases_4f.json'):
        d = json.loads((WORK / fn).read_text(encoding='utf-8'))
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and 'question' in v[0] and 'expected_lookup' not in v[0]:
                for c in v:
                    cases[c['id']] = c
    rows = []
    for cid, c in cases.items():
        f = next((HERE / 'runs' / rid / f'{cid}.json' for rid in run_ids if (HERE / 'runs' / rid / f'{cid}.json').exists()), None)
        if f is None:
            continue
        r = json.loads(f.read_text(encoding='utf-8'))
        fin = r['final']
        blocks = r.get('pool_blocks') or {}
        sec_of = {b['chunk_id']: b['section_id'] for b in blocks.values()}
        prim = [p['chunk_id'] for p in r['validated']['primary']]
        supp = [p['chunk_id'] for p in r['validated']['supporting']]
        prim_secs = sorted({sec_of.get(x, '').replace(PFX, '') for x in prim + supp})
        ctx_secs = sorted({sec_of.get(x, '').replace(PFX, '') for x in r.get('final_context_chunks', [])})
        text = r.get('final_context_value_text', '')
        reasons = [x['rule'] for x in fin['reasons']]
        role_names = sorted({x['role'] for x in r.get('question_roles', [])})
        row = {'id': cid, 'run': f.parent.name, 'question': c['question'], 'status': fin['status'], 'method': r['method'], 'primary_sections': prim_secs,
               'context_sections': ctx_secs, 'absent_terms': r.get('absent_terms'), 'alias_confirmed': r.get('alias_confirmed'),
               'confirmed_chunks': len(fin.get('confirmed_chunks', [])), 'confirmation_only_chunks': len(fin.get('confirmation_only_chunks', [])),
               'model_calls': [x.get('role') for x in r.get('calls', [])], 'new_calls': [x.get('role') for x in r.get('calls', []) if not x.get('cached')],
               'reasons': reasons, 'missing_targets': fin.get('missing_targets'), 'target_compare': r.get('target_compare') and
               [(i['candidate'], i['model_verdict'], i['effective_verdict'], i['span_valid']) for i in r['target_compare']['items']],
               'target_excluded': [x['chunk_id'].split(':')[-1] for x in r.get('target_excluded', [])], 'roles': role_names}
        ch = {}
        if 'allowed_status' in c:
            ch['status_allowed'] = fin['status'] in c['allowed_status']
        if c.get('must_not_status'):
            ch['status_not_forbidden'] = fin['status'] not in c['must_not_status']
        if c.get('must_not_reasons'):
            ch['reasons_not_present'] = not (set(c['must_not_reasons']) & set(reasons))
        if c.get('answer_sections_any'):
            ch['answer_section_in_selection'] = any(s in prim_secs for s in c['answer_sections_any'])
        if c.get('evidence_contains_any'):
            ch['evidence_contains'] = any(w in text for w in c['evidence_contains_any'])
        for key in ('forbidden_sections', 'forbidden_sections_in_answer_context'):
            if c.get(key):
                ch['forbidden_sections_absent'] = not any(s in prim_secs or s in ctx_secs for s in c[key])
        if c.get('alias_expected'):
            ch['alias_confirmed_as_expected'] = all(any(k.startswith(t) and v == w for k, v in (r.get('alias_confirmed') or {}).items()) for t, w in c['alias_expected'].items())
        if c.get('roles_expected'):
            ch['roles_recorded'] = all(x in role_names for x in c['roles_expected'])
        if cid in ('E02', 'E03'):
            ch['missing_target_shown'] = bool(fin.get('missing_targets'))
            ch['no_confirmed_evidence'] = not fin.get('confirmed_chunks')
            ch['confirmation_only_present'] = bool(fin.get('confirmation_only_chunks'))
        if c.get('confirmed_evidence_must_be_empty'):
            ch['no_confirmed_evidence'] = not fin.get('confirmed_chunks')
            ch['preferred_status'] = fin['status'] == c['preferred_status']
        if 'alternatives_sections' in c:
            alts = {x['section_id'].replace(PFX, '') for x in r.get('alternatives', [])}
            ch['alternatives_cover_expected'] = set(c['alternatives_sections']) <= alts
            ch['no_model_call'] = len(r.get('calls', [])) == 0 and r['method'] == 'structural_number_lookup'
            ch['division_choice_required'] = bool(r.get('division_choice_required'))
            ch['alternatives_not_marked_answer'] = all(x['applies'] == 'unknown' for x in r.get('alternatives', [])) and not prim
        row['checks'] = ch
        row['all_passed'] = all(ch.values())
        rows.append(row)
    out = {'run_ids': run_ids, 'note': '개발·회귀 사례(독립 평가 아님). 기대는 결과를 보기 전에 원문 확인으로 고정했다.',
           'passed_cases': [r['id'] for r in rows if r['all_passed']], 'failed_cases': [r['id'] for r in rows if not r['all_passed']], 'rows': rows}
    (HERE / f'eval_dev_{run_ids[0]}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for r in rows:
        bad = [k for k, v in r['checks'].items() if not v]
        print(r['id'], r['status'], r['method'], 'prim', r['primary_sections'], 'conf', r['confirmed_chunks'], 'confOnly', r['confirmation_only_chunks'],
              'cmp', r['target_compare'], 'excl', r['target_excluded'], 'PASS' if r['all_passed'] else f'FAIL {bad}', '| reasons', r['reasons'])
    print(len(out['passed_cases']), 'pass', len(out['failed_cases']), 'fail', out['failed_cases'])


if __name__ == '__main__':
    main(sys.argv[1:])
