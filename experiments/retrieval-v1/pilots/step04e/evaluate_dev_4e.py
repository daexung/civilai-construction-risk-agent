"""4e 개발 사례(E01~E06, G01~G04) 평가: 결과를 보기 전에 고정한 기대(dev_cases_4e.json)와 실행 결과(runs/<run_id>/)를 대조한다.
독립 평가가 아니다(규칙을 만든 뒤 같은 작업에서 만든 개발 자료). 모델을 부르지 않는다.

  python -B evaluate_dev_4e.py dev-final     # 결과: eval_dev_<run_id>.json
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
PFX = 'pumsem-2026-errata1:'


def main(run_id):
    d = json.loads((HERE / 'dev_cases_4e.json').read_text(encoding='utf-8'))
    cases = {c['id']: c for k in ('colloquial_normal', 'similar_no_data', 'number_only') for c in d[k]}
    rows = []
    for cid, c in cases.items():
        r = json.loads((HERE / 'runs' / run_id / f'{cid}.json').read_text(encoding='utf-8'))
        f = r['final']
        blocks = r.get('pool_blocks') or {}
        sec_of = {b['chunk_id']: b['section_id'] for b in blocks.values()}
        prim = [p['chunk_id'] for p in r['validated']['primary']]
        supp = [p['chunk_id'] for p in r['validated']['supporting']]
        prim_secs = sorted({sec_of.get(x, '').replace(PFX, '') for x in prim + supp})
        ctx_secs = sorted({sec_of.get(x, '').replace(PFX, '') for x in r.get('final_context_chunks', [])})
        text = r.get('final_context_value_text', '')
        row = {'id': cid, 'question': c['question'], 'status': f['status'], 'method': r['method'], 'primary_sections': prim_secs,
               'context_sections': ctx_secs, 'absent_terms': r.get('absent_terms'), 'alias_confirmed': r.get('alias_confirmed'),
               'confirmed_chunks': len(f.get('confirmed_chunks', [])), 'confirmation_only_chunks': len(f.get('confirmation_only_chunks', [])),
               'model_calls': len([x for x in r.get('calls', [])]), 'reasons': [x['rule'] for x in f['reasons']],
               'missing_targets': f.get('missing_targets')}
        checks = {}
        if 'allowed_status' in c:
            checks['status_allowed'] = f['status'] in c['allowed_status']
        if c.get('must_not_status'):
            checks['status_not_forbidden'] = f['status'] not in c['must_not_status']
        if c.get('answer_sections_any'):
            checks['answer_section_in_selection'] = any(s in prim_secs for s in c['answer_sections_any'])
        if c.get('evidence_contains_any'):
            checks['evidence_contains'] = any(w in text for w in c['evidence_contains_any'])
        if c.get('forbidden_sections'):
            checks['forbidden_sections_absent'] = not any(s in prim_secs or s in ctx_secs for s in c['forbidden_sections'])
        if 'alias_expected' in c and c['alias_expected']:
            checks['alias_confirmed_as_expected'] = all(any(k.startswith(t) and v == w for k, v in (r.get('alias_confirmed') or {}).items())
                                                      for t, w in c['alias_expected'].items())
        if cid in ('E02', 'E03'):
            checks['missing_target_shown'] = bool(f.get('missing_targets'))
            checks['no_confirmed_evidence'] = not f.get('confirmed_chunks')
            checks['confirmation_only_present'] = bool(f.get('confirmation_only_chunks'))
        if c.get('confirmed_evidence_must_be_empty'):
            checks['no_confirmed_evidence'] = not f.get('confirmed_chunks')
            checks['preferred_status'] = f['status'] == c['preferred_status']
        if 'alternatives_sections' in c:
            alts = {x['section_id'].replace(PFX, '') for x in r.get('alternatives', [])}
            checks['alternatives_cover_expected'] = set(c['alternatives_sections']) <= alts
            checks['no_model_call'] = len(r.get('calls', [])) == 0 and r['method'] == 'structural_number_lookup'
            checks['division_choice_required'] = bool(r.get('division_choice_required'))
            checks['alternatives_not_marked_answer'] = all(x['applies'] == 'unknown' for x in r.get('alternatives', [])) and not prim
        row['checks'] = checks
        row['all_passed'] = all(checks.values())
        rows.append(row)
    out = {'run_id': run_id, 'note': '개발 사례(독립 평가 아님). 기대는 결과를 보기 전에 원문 확인으로 고정했다.',
           'passed_cases': [r['id'] for r in rows if r['all_passed']], 'failed_cases': [r['id'] for r in rows if not r['all_passed']], 'rows': rows}
    (HERE / f'eval_dev_{run_id}.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for r in rows:
        bad = [k for k, v in r['checks'].items() if not v]
        print(r['id'], r['status'], r['method'], 'prim', r['primary_sections'], 'conf', r['confirmed_chunks'], 'confOnly', r['confirmation_only_chunks'],
              'PASS' if r['all_passed'] else f'FAIL {bad}')
    print(len(out['passed_cases']), 'pass', len(out['failed_cases']), 'fail', out['failed_cases'])


if __name__ == '__main__':
    main(sys.argv[1])
