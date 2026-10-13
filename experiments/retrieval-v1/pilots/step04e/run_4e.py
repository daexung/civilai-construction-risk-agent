"""4e 실행기. 검증형 선택기(src/select_verified.py)로 질문을 처리하고 결과를 step04e 실행 폴더에 남긴다.

  python -B run_4e.py replay --run-id rp-1 --ids N08,Q13,V11,V12 [--tag rep2]   # 저장된 응답만 사용(모델 호출 없음, 캐시에 없으면 '재생 불가'로 기록)
  python -B run_4e.py run --run-id live-1 --ids N08 --tag rep4                    # 새 호출 허용(상한 30회·$1)
  python -B run_4e.py run --run-id final-60 --set all                             # 60문 최종 확인(바뀌지 않은 입력은 4d 캐시 재사용)
  python -B run_4e.py run --run-id dev-e --cases dev                              # 4e 개발 사례(dev_cases_4e.json)

- 이번 단계 상한: 유료 호출 시도 30회, 예상 비용 $1(먼저 닿는 쪽). 4d 원장·캐시는 읽기 전용이며 이 단계의 원장(ledger_4e.jsonl)을 따로 쓴다.
- 4d 캐시(읽기 전용)에서 같은 입력·모델·프롬프트·스키마·설정의 성공 응답을 재사용한다. 새 응답은 step04e/cache/에만 쓴다.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
WORK = HERE.parents[1]
sys.path.insert(0, str(WORK / 'src'))
sys.path.insert(0, str(WORK / 'pilots/step04d'))
import retrieve as rv  # noqa: E402
import select_verified as sv  # noqa: E402
import specs  # noqa: E402

CAPS = {'cost_usd': 1.0, 'attempts': 30}
LEDGER = HERE / 'ledger_4e.jsonl'
CACHE = HERE / 'cache'
CACHE_4D = WORK / 'pilots/step04d/cache'


class ReplayCaller:
    """모델을 부르지 않는다. 같은 입력의 저장된 응답이 없으면 재생 불가로 돌려준다."""

    def __init__(self, tag=''):
        self.inner = sv.ModelCaller.__new__(sv.ModelCaller)
        import os
        os.environ['AGENT_LLM'] = 'on'
        from backend.agent.tools.llm import client as llm
        self.provider, self.model = llm.provider_name(), llm.model_name()
        self.tag = tag
        self.dirs = [CACHE, CACHE_4D]

    def totals(self):
        return 0, 0.0

    def call(self, role, system, prompt, schema, qid=None, run_id=None):
        key = sv.sha([self.model, self.provider, system, prompt, schema, sv.CONFIG['llm'], self.tag])
        for d in self.dirs:
            f = d / f'{key}.json'
            if f.exists():
                rec = json.loads(f.read_text(encoding='utf-8'))
                if rec.get('ok'):
                    rec.update(cached=True, cache_source=d.parent.name, orig_cost_usd=rec.get('cost_usd'), orig_attempts=rec.get('attempts'),
                               cost_usd=0.0, attempts=0, replay=True)
                    return rec
        return {'ok': False, 'error': 'replay_cache_miss', 'attempts': 0, 'cost_usd': 0.0, 'cached': False, 'role': role, 'replay': True}


def load_cases(which):
    d = json.loads((HERE / 'dev_cases_4e.json').read_text(encoding='utf-8'))
    cases = d['colloquial_normal'] + d['similar_no_data'] + d['number_only']
    return [{'id': c['id'], 'question': c['question'], 'set': 'dev_4e', 'no_data': c['id'].startswith('E0') and c['id'] in ('E04', 'E05', 'E06'),
             'spec': c} for c in cases]


def pick(ids, which, cases):
    if cases == 'dev':
        cs = load_cases(None)
        return [c for c in cs if not ids or c['id'] in set(ids.split(','))]
    sp = specs.load_specs()
    exp = []
    for s in sp:
        if s.get('tasks'):
            for k, t in enumerate(s['tasks']):
                exp.append({**s, 'id': f"{s['id']}_{k}", 'parent': s['id'], 'question': t['query']})
        else:
            exp.append(s)
    if ids:
        want = set(ids.split(','))
        return [s for s in exp if s['id'] in want or s.get('parent') in want]
    return exp


def run(mode, run_id, ids, which, tag, cases):
    rt = rv.Retriever()
    caller = ReplayCaller(tag) if mode == 'replay' else sv.ModelCaller(LEDGER, CACHE, CAPS, tag=tag, fallback_cache_dirs=[CACHE_4D])
    vs = sv.VerifiedSelector(rt, caller)
    out_dir = HERE / 'runs' / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'meta.json').write_text(json.dumps({'run_id': run_id, 'mode': mode, 'tag': tag, 'started': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                                   'versions': vs.versions(), 'caps': CAPS, 'model': caller.model, 'provider': caller.provider},
                                                  ensure_ascii=False, indent=1), encoding='utf-8')
    api0 = rt.api_calls
    summary = []
    for s in pick(ids, which, cases):
        f = out_dir / f"{s['id']}.json"
        if f.exists():
            print(s['id'], '이미 있음(건너뜀)')
            continue
        if mode == 'run':
            att, cost = caller.totals()
            if att >= CAPS['attempts'] or cost >= CAPS['cost_usd']:
                print('상한 도달: 중단', att, cost)
                break
        r = vs.run(s['question'], qid=s['id'], run_id=run_id, fallback=False)
        new_api = rt.api_calls - api0
        api0 = rt.api_calls
        if new_api and mode == 'run':
            with open(LEDGER, 'a', encoding='utf-8') as lf:
                lf.write(json.dumps({'run_id': run_id, 'qid': s['id'], 'role': 'query_embedding', 'ok': True, 'attempts': new_api,
                                     'cost_usd': round(new_api * 30 / 1e6 * 0.20, 7), 'latency_sec': None,
                                     'started': time.strftime('%Y-%m-%dT%H:%M:%S')}, ensure_ascii=False) + '\n')
        r['query_embedding_calls'] = new_api
        miss = any(c.get('error') == 'replay_cache_miss' for c in r.get('calls', []))
        r['replay_status'] = ('cache_miss_not_replayable' if miss else 'replayed_from_cache') if mode == 'replay' else None
        f.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
        fin = r.get('final', {})
        prim = [p['chunk_id'].split(':', 1)[-1][-20:] for p in r.get('validated', {}).get('primary', [])]
        print(s['id'], r['method'], fin.get('status'), 'primary', prim, '| rules', [x['rule'] for x in fin.get('reasons', [])],
              '| confirmed', len(fin.get('confirmed_chunks', [])), 'confirm_only', len(fin.get('confirmation_only_chunks', [])),
              'cc', len(r.get('confirmation_context', [])), '| lookups', [l['kind'] for l in r.get('lookups', [])],
              '| calls', len(r.get('calls', [])), 'cached', r.get('usage_total', {}).get('cached_calls'), 'cost', r.get('usage_total', {}).get('cost_usd'),
              '| replay', r['replay_status'])
    if mode == 'run':
        att, cost = caller.totals()
        print('이번 단계 누적 시도', att, '누적 비용', round(cost, 4))
    rt.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['replay', 'run'])
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--ids', default='')
    ap.add_argument('--set', default='all')
    ap.add_argument('--tag', default='')
    ap.add_argument('--cases', default='specs', choices=['specs', 'dev'])
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    run(a.mode, a.run_id, a.ids, a.set, a.tag, a.cases)
