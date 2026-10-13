"""4d 호출·비용·지연 집계(원장 ledger.jsonl)와 실행별 코드·프롬프트 해시 이력. 모델 호출 없음."""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent


def main():
    rows = [json.loads(l) for l in (HERE / 'ledger.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    by_run = defaultdict(lambda: {'attempts': 0, 'cost': 0.0, 'calls': 0})
    by_role = defaultdict(lambda: {'attempts': 0, 'cost': 0.0, 'calls': 0, 'lat': []})
    for r in rows:
        a = by_run[r['run_id']]
        a['attempts'] += r['attempts']
        a['cost'] += r['cost_usd']
        a['calls'] += 1
        b = by_role[r['role']]
        b['attempts'] += r['attempts']
        b['cost'] += r['cost_usd']
        b['calls'] += 1
        if r.get('latency_sec'):
            b['lat'].append(r['latency_sec'])
    out = {'total_attempts': sum(r['attempts'] for r in rows), 'total_cost_usd': round(sum(r['cost_usd'] for r in rows), 4),
           'by_run': {k: {**v, 'cost': round(v['cost'], 4)} for k, v in by_run.items()},
           'by_role': {k: {'calls': v['calls'], 'attempts': v['attempts'], 'cost': round(v['cost'], 4),
                           'latency_median_sec': round(statistics.median(v['lat']), 2) if v['lat'] else None,
                           'latency_max_sec': max(v['lat']) if v['lat'] else None} for k, v in by_role.items()}}
    hist = {}
    for d in sorted((HERE / 'runs').iterdir()):
        m = d / 'meta.json'
        if m.exists():
            v = json.loads(m.read_text(encoding='utf-8'))['versions']
            hist[d.name] = {k: v[k][:10] for k in ('select_verified_code_sha256', 'select_verified_config_sha256', 'system_select_sha256',
                                                   'schema_select_sha256', 'system_list_sha256', 'schema_list_sha256')}
    out['run_versions'] = hist
    (HERE / 'usage_4d.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
