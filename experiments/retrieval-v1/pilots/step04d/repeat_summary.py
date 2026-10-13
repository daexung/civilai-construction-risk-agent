"""반복 측정 요약: 같은 질문을 여러 실행(첫 실행 + 반복 실행)에서 비교한다. 모델 호출 없음.

  python -B repeat_summary.py reg60-c rep-2 rep-3
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import specs  # noqa: E402

SP = {s['id']: s for s in specs.load_specs()}


def load(run, qid):
    f = HERE / 'runs' / run / f'{qid}.json'
    return json.loads(f.read_text(encoding='utf-8')) if f.exists() else None


def main(runs):
    first = runs[0]
    ids = sorted({p.stem for r in runs[1:] for p in (HERE / 'runs' / r).glob('*.json') if p.stem != 'meta'})
    out = {}
    for q in ids:
        rows = []
        for r in runs:
            d = load(r, q)
            if d is None:
                continue
            s = SP.get(q.split('_')[0], {})
            prim = sorted(p['chunk_id'] for p in d.get('validated', {}).get('primary', []))
            supp = sorted(p['chunk_id'] for p in d.get('validated', {}).get('supporting', []))
            forb = sorted(set(s.get('forbidden_chunks', [])) & set(prim)) if s else []
            rows.append({'run': r, 'status': d['final']['status'], 'primary': prim, 'supporting': supp, 'forbidden_primary': forb,
                         'rules': [x['rule'] for x in d['final'].get('reasons', [])], 'method': d['method'],
                         'list_included': sorted(d['list']['included']) if d.get('list') and 'included' in d['list'] else None,
                         'cost_usd': d['usage_total']['cost_usd'], 'cached_calls': d['usage_total']['cached_calls'],
                         'lookups': [l['kind'] for l in d.get('lookups', [])], 'absent_terms': d.get('absent_terms')})
        out[q] = {'runs': rows, 'status_same': len({r['status'] for r in rows}) == 1, 'primary_same': len({tuple(r['primary']) for r in rows}) == 1,
                  'selected_same': len({(tuple(r['primary']), tuple(r['supporting'])) for r in rows}) == 1,
                  'list_same': (len({tuple(r['list_included']) for r in rows if r['list_included'] is not None}) <= 1)}
    (HERE / 'repeat_summary.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    for q, v in out.items():
        print(q, '상태 동일' if v['status_same'] else '상태 다름', '| 주 근거 동일' if v['primary_same'] else '| 주 근거 다름', '| 선택 집합 동일' if v['selected_same'] else '| 선택 집합 다름',
              '| 목록 동일' if v['list_same'] else '| 목록 다름', [(r['run'], r['status'], len(r['primary']), r['forbidden_primary']) for r in v['runs']])


if __name__ == '__main__':
    main(sys.argv[1:])
