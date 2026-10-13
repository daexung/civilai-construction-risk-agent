"""4d 결과를 기존 4b(저장된 평가 행)·4c(저장된 평가)와 같은 질문 기준으로 비교한다. 모델 호출 없음.

  python -B compare_4d.py <eval 파일 이름(eval_*.json)> [<eval 파일 ...>]    # 결과: compare_4d.json, 표준 출력에 마크다운 표
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
WORK = HERE.parents[1]
sys.path.insert(0, str(HERE))
import specs  # noqa: E402

RUNS = WORK / 'out/verification_runs/cs-37f81b5cfb1b-46f4f035c0fa'
B4_DEV = json.loads((RUNS / '20261012T123214-eval_selection_dev/dev_selection_results.json').read_text(encoding='utf-8'))['rows']
B4_IND = json.loads((RUNS / '20261012T123241-eval_selection_new/new_selection_results.json').read_text(encoding='utf-8'))['rows']
C4 = json.loads((WORK / 'pilots/step04c/results.json').read_text(encoding='utf-8'))
B4 = {r['id']: r for r in B4_DEV}
B4.update({r['id']: r for r in B4_IND})
SP = {s['id']: s for s in specs.load_specs()}


def b4_for(qid):
    if qid in B4:
        return B4[qid]
    tasks = [B4[k] for k in B4 if k.startswith(qid + ':')]
    if tasks:
        return {'id': qid, 'tasks': tasks, 'status': '/'.join(t['status'] for t in tasks),
                'final_hit_primary': all(t.get('final_hit_primary') for t in tasks)}
    return None


def main(files):
    rows = {}
    for f in files:
        d = json.loads((HERE / f).read_text(encoding='utf-8'))
        for r in d['rows']:
            rows[r['id']] = r
    out = {'files': files, 'n': len(rows), 'dev12': [], 'agg': {}}
    # ---- 개발 12문 비교
    for q in specs.DEV12:
        r = rows.get(q)
        b = B4.get(q)
        c = C4[q]['llm']['r1']
        out['dev12'].append({
            'id': q, 'category': SP[q]['category'], 'allowed': SP[q]['allowed_status'],
            '4b': {'status': b['status'], 'required_in_context': len(b.get('required_in_context', [])), 'required_n': len(b.get('required_chunks', [])),
                   'forbidden_primary': len(b.get('forbidden_in_primary_selected', [])), 'forbidden_units': len(b.get('forbidden_in_units', [])),
                   'answer_recall': b.get('answer_recall_final'), 'unneeded': len(b.get('unneeded_sections', []))},
            '4c': {'status': c['status'], 'required_in_context': len(c.get('final', {}).get('required_in_context', [])) if c.get('final') else None,
                   'forbidden_primary': len(c.get('forbidden_in_primary', [])), 'required_missing_selected': len(c.get('required_missing_in_selected', [])),
                   'list_sel_set': c.get('required_sections_covered_selected_set'), 'list_primary': c.get('required_sections_covered'),
                   'quotes_invalid': len(c['quotes']['invalid'])},
            '4d': {'status': r['status'], 'required_in_context': r['required_in_context'], 'required_n': r['required_n'], 'required_selected': r['required_selected'],
                   'required_class': r['required_class'], 'forbidden_primary': len(r['forbidden_primary']), 'forbidden_context': len(r['forbidden_in_context']),
                   'reasons': r['reasons'], 'rejected': r['rejected'], 'lookups': r['lookups'], 'competing': len(r['competing']),
                   'list': r.get('list'), 'no_data_ok': r['no_data_ok'], 'promoted': r['promoted'], 'cost_usd': r['cost_usd'], 'latency_sec': r['latency_sec']}})
    # ---- 60문 회귀 집계(4b와 4d를 같은 질문 분모로)
    A = {'questions': len(rows)}
    chunkq = [q for q, s in SP.items() if s['required_chunks'] and not s['is_list'] and not s['no_data'] and q in rows]
    A['chunk_questions'] = len(chunkq)
    A['required_total'] = sum(len(SP[q]['required_chunks']) for q in chunkq)
    A['required_in_context_4b'] = sum(len(B4[q].get('required_in_context', [])) for q in chunkq if q in B4)
    A['required_in_context_4d'] = sum(rows[q]['required_in_context'] for q in chunkq)
    A['required_selected_4d'] = sum(rows[q]['required_selected'] for q in chunkq)
    A['required_classes_4d'] = dict(Counter(v for q in chunkq for v in rows[q]['required_class'].values()))
    A['forbidden_primary_4b'] = [q for q in rows if q in B4 and B4[q].get('forbidden_in_primary_selected')]
    A['forbidden_primary_4d'] = [q for q in rows if rows[q].get('forbidden_primary')]
    A['forbidden_units_4b'] = [q for q in rows if q in B4 and B4[q].get('forbidden_in_units')]
    A['forbidden_context_4d'] = [q for q in rows if rows[q].get('forbidden_in_context')]
    normal = [q for q in rows if not SP[q]['no_data']]
    A['normal_n'] = len(normal)
    A['normal_rejected_4b'] = [q for q in normal if (b4_for(q) or {}).get('status') == 'not_found']
    A['normal_rejected_4d'] = [q for q in normal if rows[q]['status'] == 'not_found']
    nd = [q for q in rows if SP[q]['no_data']]
    A['no_data'] = {q: {'4b': (b4_for(q) or {}).get('status'), '4d': rows[q]['status'], '4d_ok': rows[q].get('no_data_ok')} for q in nd}
    hold = [q for q in rows if SP[q]['hold']]
    A['hold'] = {q: {'4b': (b4_for(q) or {}).get('status'), '4d': rows[q]['status'], '4d_forbidden_primary': rows[q].get('forbidden_primary')} for q in hold}
    A['status_4b'] = dict(Counter((b4_for(q) or {}).get('status') for q in rows))
    A['status_4d'] = dict(Counter(rows[q]['status'] for q in rows))
    ov4 = [q for q in normal if not SP[q]['hold'] and (b4_for(q) or {}).get('status') == 'needs_confirmation']
    ov4d = [q for q in normal if not SP[q]['hold'] and rows[q]['status'] == 'needs_confirmation']
    A['needs_confirmation_on_normal_4b'] = ov4
    A['needs_confirmation_on_normal_4d'] = ov4d
    A['needs_confirmation_reasons_4d'] = dict(Counter(x for q in ov4d for x in set(rows[q]['reasons'])))
    # 목록
    lq = [q for q in rows if SP[q]['is_list'] and SP[q]['category'] == 'list' and q in B4 and SP[q]['answer_sections']]
    A['lists'] = {}
    for q in lq:
        r = rows[q]
        if 'list' not in r:
            A['lists'][q] = {'4d': 'no list pass', '4b_recall': B4[q].get('answer_recall_final'), '4b_unneeded': len(B4[q].get('unneeded_sections', []))}
            continue
        L = r['list']
        A['lists'][q] = {'req_n': len(SP[q]['answer_sections']), '4d_hit': len(L['required_hit']), '4d_missing': len(L['required_missing']),
                         '4d_unneeded': len(L['unneeded']), '4d_forbidden': len(L['forbidden_included']), '4d_uncertain_required': len(L['uncertain_required']),
                         '4b_recall': B4[q].get('answer_recall_final'), '4b_unneeded': len(B4[q].get('unneeded_sections', [])),
                         '4b_forbidden': len(B4[q].get('forbidden_sections_in_final', []))}
    # 구형 세트(절 단위)
    old = [q for q in rows if SP[q]['set'] == 'dev_old' and SP[q]['answer_sections']]
    A['old_set'] = {}
    for q in old:
        sh = rows[q].get('section_hit') or {}
        b = b4_for(q) or {}
        A['old_set'][q] = {'4b_hit_primary': b.get('final_hit_primary'), '4d_hit_primary': sh.get('primary', sh.get('tasks_hit_primary')),
                           '4d_hit_selected': sh.get('selected', sh.get('tasks_hit_selected')), '4d_hit_list': sh.get('list_or_selected')}
    A['cost_usd'] = round(sum(r['cost_usd'] or 0 for r in rows.values()), 4)
    A['latency_median_sec'] = sorted(r['latency_sec'] for r in rows.values())[len(rows) // 2]
    out['agg'] = A
    (HERE / 'compare_4d.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(A, ensure_ascii=False, indent=1))
    for d in out['dev12']:
        print(d['id'], '| 4b', d['4b'], '| 4c', d['4c'], '| 4d', {k: v for k, v in d['4d'].items() if k not in ('required_class', 'list')})


if __name__ == '__main__':
    main(sys.argv[1:])
