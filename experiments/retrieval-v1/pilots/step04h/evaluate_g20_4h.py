"""4h 개발·회귀 평가(4g 20문). 4g의 고정 기대값(eval/expected_04g_*.json)과 판정 함수를 그대로 쓰되, 4h 결과의 용도 구분(정상 답변 근거·검토용 원문·진단 후보)과
목록 완전성 의미 분리를 더해 집계한다. 4g 질문은 이번 수정에 사용했으므로 **개발·회귀 자료**이며 독립 성공이 아니다. 모델을 부르지 않는다.

  python -B evaluate_g20_4h.py <run_id>                          # 실행 폴더 runs/<run_id>/4g_G**.json
"""
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
W = HERE.parents[1]
sys.path.insert(0, str(W / 'pilots/step04g'))
import evaluate_4g as eg  # noqa: E402

PFX = eg.PFX


def load(run_id, qid):
    f = HERE / 'runs' / run_id / f'4g_{qid}.json'
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else None


def delivery(r, c):
    f = r['final']
    if c in set(f.get('review_chunks', [])):
        return 'review'
    if c in set(f.get('answer_evidence_chunks', [])):
        return 'answer'
    if any(d['chunk_id'] == c for d in r.get('diagnostic_candidates', [])):
        return 'diagnostic'
    return 'none'


def main(run_id, extra=None):
    rows, not_run = [], []
    extra = extra or {}
    for qid in eg.EX:
        r = load(extra.get(qid, run_id), qid)
        if r is None:
            not_run.append(qid)
            continue
        row = eg.analyze(qid, r)
        f = r['final']
        e = eg.EX[qid]
        row['answer_evidence'] = sorted(c.split(':', 1)[-1] for c in f.get('answer_evidence_chunks', []))
        row['review_material'] = sorted(c.split(':', 1)[-1] for c in f.get('review_chunks', []))
        row['diagnostic'] = [d['chunk_id'].split(':', 1)[-1] for d in r.get('diagnostic_candidates', [])]
        row['retained_review'] = [x['chunk_id'].split(':', 1)[-1] for x in r.get('retained_review', [])]
        row['warnings'] = [w['chunk_id'].split(':', 1)[-1] for w in (r.get('target_compare') or {}).get('warnings', [])]
        row['uncertain_expressions'] = r.get('uncertain_expressions')
        for x in row['required']:
            x['delivery'] = delivery(r, next(rc['chunk_id'] for rc in e['required_chunks'] if rc['chunk_id'].split(':', 1)[-1] == x['chunk_id']))
        if e['type'] == 'list':
            lst = r.get('list') or {}
            row['list'].update({'candidates_processed': lst.get('candidates_processed'), 'scope_completeness': lst.get('scope_completeness'),
                                'request_scope': lst.get('request_scope'), 'unexplored_title_matches_n': len((lst.get('lookup_scope') or {}).get('unexplored_title_matches', [])),
                                'unexplored_ratio': (lst.get('lookup_scope') or {}).get('unexplored_ratio'),
                                'list_status': lst.get('status')})
        ok, why = eg.pass_judgement(row)
        # 4h 추가 기준
        if e['type'] == 'list' and e['id'] == 'G14':
            if row['list'].get('scope_completeness') == 'complete' or 'list_scope_unverified' not in row['reasons']:
                ok, why = False, why + ['요청 범위 완전성을 완성으로 표시했거나 범위 미확인 사유가 없음']
        if row['target_excluded']:
            ok, why = False, why + ['대조 결과로 근거가 제외됨']
        row['passed'], row['fail_reasons'] = ok, why
        rows.append(row)
    S = {'executed': len(rows), 'not_run': not_run}
    vals = [r for r in rows if r['type'] in ('value', 'rule_negation', 'rule_reference', 'rule_condition', 'rule_unconfirmed')]
    tot = sum(r['required_n'] for r in vals)
    S['required_chunks'] = {'total': tot, 'in_final_context': sum(r['required_in_context'] for r in vals),
                            'by_delivery': dict(Counter(x['delivery'] for r in vals for x in r['required'])),
                            'by_class': dict(Counter(x['class'] for r in vals for x in r['required'])),
                            'missing': [(r['id'], x['chunk_id'], x['delivery']) for r in vals for x in r['required'] if not x['in_final_context']]}
    S['status'] = dict(Counter(r['status'] for r in rows))
    S['status_not_ok'] = [(r['id'], r['status']) for r in rows if not r['status_ok']]
    S['normal_rejected'] = [r['id'] for r in rows if r['normal_rejected']]
    S['over_hold'] = [(r['id'], r['reasons']) for r in rows if r['over_hold']]
    S['promoted'] = [r['id'] for r in rows if r['promoted']]
    S['forbidden_primary'] = [(r['id'], r['forbidden_primary']) for r in rows if r['forbidden_primary']]
    S['forbidden_context'] = [(r['id'], r['forbidden_in_context']) for r in rows if r['forbidden_in_context']]
    S['target_excluded'] = [(r['id'], r['target_excluded']) for r in rows if r['target_excluded']]
    S['warnings'] = [(r['id'], r['warnings']) for r in rows if r['warnings']]
    nd = [r for r in rows if r['type'] == 'no_data']
    S['no_data'] = {'n': len(nd), 'not_found': [r['id'] for r in nd if r['no_data']['not_found']], 'clean': [r['id'] for r in nd if r['no_data']['context_empty'] and r['no_data']['primary_empty']]}
    S['lists'] = {r['id']: {k: r['list'].get(k) for k in ('required_hit', 'required_missing', 'acceptable_extra', 'unneeded', 'forbidden', 'candidates_processed',
                                                       'scope_completeness', 'list_status', 'unexplored_title_matches_n', 'unexplored_ratio', 'uncertain')} for r in rows if r['type'] == 'list'}
    S['scope'] = {r['id']: r['scope'] for r in rows if r['type'] == 'scope'}
    S['passed'] = [r['id'] for r in rows if r['passed']]
    S['failed'] = [(r['id'], r['fail_reasons']) for r in rows if not r['passed']]
    (HERE / f'eval_g20_{run_id}.json').write_text(json.dumps({'summary': S, 'rows': rows}, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for r in rows:
        print(r['id'], r['type'], r['status'], 'PASS' if r['passed'] else 'FAIL ' + '; '.join(r['fail_reasons'])[:200])
    print(json.dumps({k: S[k] for k in ('required_chunks', 'status', 'status_not_ok', 'normal_rejected', 'over_hold', 'promoted', 'forbidden_primary', 'forbidden_context',
                                       'target_excluded', 'warnings', 'no_data', 'failed')}, ensure_ascii=False, indent=1)[:3500])


if __name__ == '__main__':
    main(sys.argv[1], dict(a.split('=') for a in sys.argv[2:]))
