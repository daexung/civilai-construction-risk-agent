"""4d 실행기. 질문 명세(specs.py)를 검증형 선택기(src/select_verified.py)에 통과시키고 결과를 실행 폴더에 남긴다.

  python -B run_4d.py estimate                              # 호출 없이 입력량·최악 비용 기록(precall_estimate_4d.json)
  python -B run_4d.py run --run-id dev12-a --set dev12      # 개발 12문
  python -B run_4d.py run --run-id reg60-a --set all        # 60문(개발 12문 포함)
  python -B run_4d.py run --run-id rep-b --ids V09,V12 --tag rep2    # 반복 측정(캐시 키가 달라 새로 호출)

- 운영 상한: 예상 비용 5달러, 유료 호출 시도 200회(재시도·형식 복구·질문 임베딩 포함). 먼저 닿는 쪽에서 멈춘다.
- 같은 입력·모델·프롬프트·설정의 성공 응답은 cache/에서 재사용한다(반복 측정은 --tag로 구분).
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
sys.path.insert(0, str(HERE))
import retrieve as rv  # noqa: E402
import select_evidence as se  # noqa: E402
import select_verified as sv  # noqa: E402
import specs  # noqa: E402

CAPS = {'cost_usd': 5.0, 'attempts': 200}
LEDGER = HERE / 'ledger.jsonl'
CACHE = HERE / 'cache'


def expand(sp):
    """작업을 나눈 질문(Q05)은 사람이 준 작업 질문 3개를 각각 실행한다(질문 수로는 1개). 전체 글의 질문 벡터는 캐시에 없고 만들지 않는다."""
    out = []
    for s in sp:
        if s.get('tasks'):
            for k, t in enumerate(s['tasks']):
                out.append({**s, 'id': f"{s['id']}_{k}", 'parent': s['id'], 'question': t['query'], 'answer_sections': t['answer_sections'],
                            'section_mode': 'any', 'tasks': None})
        else:
            out.append(s)
    return out


def pick(ids, which):
    sp = expand(specs.load_specs())
    if ids:
        want = set(ids.split(','))
        return [s for s in sp if s['id'] in want or s.get('parent') in want]
    if which == 'dev12':
        return [s for s in sp if s['dev12']]
    return sp


def estimate():
    rt = rv.Retriever(embed_queries=False)
    sel = se.Selector(rt)
    sv._SEC = sel.sec
    store = sv.Store(rt)
    rows = {}
    tot_chars = 0
    for s in expand(specs.load_specs()):
        pool = sv.build_pool(rt, store, sel, s['question'])
        prompt, ctx = sv.build_prompt(pool, store)
        chars = len(sv.SYSTEM_SELECT) + len(prompt)
        worst = chars / 1e6 * sv.PRICE['input_per_m'] + sv.CONFIG['llm']['max_output_tokens'] / 1e6 * sv.PRICE['output_per_m']
        rows[s['id']] = {'chars': chars, 'worst_case_usd_per_attempt': round(worst, 4), 'n_candidates': len(pool.candidates()),
                         'n_linked_only': len(pool.blocks) - len(pool.candidates()), 'prompt_sha256': sv.sha(prompt),
                         'context_sha256': sv.sha(ctx), 'dev12': s['dev12']}
        tot_chars += chars
    n = len(rows)
    # 호출 계획: 60문 1차 + 목록 절 판단(목록 질문 수) + 보완 검색 선택(최대 질문 수의 1/4 가정) + 반복(위험 사례 12문 × 2)
    n_list = sum(1 for s in expand(specs.load_specs()) if s['is_list'])
    plan = {'first_pass': n, 'list_pass': n_list, 'supplement_pass_assumed': n // 4, 'repeats_assumed': 12 * 2, 'dev12_rerun_after_fix_assumed': 12 * 2}
    calls = sum(plan.values())
    worst_each = sum(r['worst_case_usd_per_attempt'] for r in rows.values()) / n
    est = {'price': {**sv.PRICE, 'source': 'ai.google.dev 가격표(gemini-3.5-flash-lite, 표준·유료) 입력 $0.30/출력 $2.50 per 1M. '
                     'Vertex 공식 가격표 본문은 읽지 못했고 제3자 가격 추적 사이트가 같은 값을 적음(공식 확인 아님) → 비용 상한 점검에 ×1.5를 곱한다'},
           'caps': CAPS, 'max_output_tokens': sv.CONFIG['llm']['max_output_tokens'], 'planned_calls': plan, 'planned_calls_total': calls,
           'max_attempts_per_call': sv.CONFIG['llm']['max_attempts'], 'worst_case_per_attempt_avg_usd': round(worst_each, 4),
           'worst_case_total_usd_if_every_attempt_maxed': round(calls * sv.CONFIG['llm']['max_attempts'] * worst_each * 1.5, 2),
           'expected_per_call_usd': round(0.65 * (tot_chars / n) / 1e6 * sv.PRICE['input_per_m'] + 350 / 1e6 * sv.PRICE['output_per_m'], 4),
           'expected_total_usd': round(calls * (0.65 * (tot_chars / n) / 1e6 * sv.PRICE['input_per_m'] + 350 / 1e6 * sv.PRICE['output_per_m']), 2),
           'expected_basis': '4c 실측: 입력 토큰 ≈ 글자 수 × 0.65, 출력 약 250~500토큰(생각 토큰 없음)',
           'system_select_sha256': sv.sha(sv.SYSTEM_SELECT), 'schema_select_sha256': sv.sha(sv.SCHEMA_SELECT),
           'system_list_sha256': sv.sha(sv.SYSTEM_LIST), 'schema_list_sha256': sv.sha(sv.SCHEMA_LIST),
           'questions': rows}
    (HERE / 'precall_estimate_4d.json').write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({k: v for k, v in est.items() if k != 'questions'}, ensure_ascii=False, indent=1))
    rt.close()


def run(run_id, ids, which, tag):
    rt = rv.Retriever()
    caller = sv.ModelCaller(LEDGER, CACHE, CAPS, tag=tag)
    vs = sv.VerifiedSelector(rt, caller)
    out_dir = HERE / 'runs' / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'meta.json').write_text(json.dumps({'run_id': run_id, 'tag': tag, 'started': time.strftime('%Y-%m-%dT%H:%M:%S'),
                                                   'versions': vs.versions(), 'caps': CAPS, 'model': caller.model, 'provider': caller.provider},
                                                  ensure_ascii=False, indent=1), encoding='utf-8')
    api0 = rt.api_calls
    for s in pick(ids, which):
        f = out_dir / f"{s['id']}.json"
        if f.exists():
            print(s['id'], '이미 있음(건너뜀)')
            continue
        att, cost = caller.totals()
        if att >= CAPS['attempts'] or cost >= CAPS['cost_usd']:
            print('상한 도달: 중단', att, cost)
            break
        r = vs.run(s['question'], qid=s['id'], run_id=run_id)
        # 질문 임베딩 호출(보완 검색 등)도 시도 횟수로 센다
        new_api = rt.api_calls - api0
        api0 = rt.api_calls
        if new_api:
            with open(LEDGER, 'a', encoding='utf-8') as lf:
                lf.write(json.dumps({'run_id': run_id, 'qid': s['id'], 'role': 'query_embedding', 'ok': True, 'attempts': new_api,
                                     'cost_usd': round(new_api * 30 / 1e6 * 0.20, 7), 'latency_sec': None,
                                     'started': time.strftime('%Y-%m-%dT%H:%M:%S')}, ensure_ascii=False) + '\n')
        r['query_embedding_calls'] = new_api
        f.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
        fin = r.get('final', {})
        prim = [p['chunk_id'].split(':', 1)[-1][-22:] for p in r.get('validated', {}).get('primary', [])]
        print(s['id'], r['method'], fin.get('status'), 'primary', prim, '| rules', [x['rule'] for x in fin.get('reasons', [])],
              '| rej', [x['reason'] for x in r.get('rejected', [])], '| lookups', [l['kind'] for l in r.get('lookups', [])],
              '| calls', len(r['calls']), 'cached', r['usage_total']['cached_calls'], 'cost', r['usage_total']['cost_usd'], 'sec', r['latency_sec'])
    att, cost = caller.totals()
    print('누적 시도', att, '누적 비용', round(cost, 4))
    rt.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['estimate', 'run'])
    ap.add_argument('--run-id', default='dev12-a')
    ap.add_argument('--set', default='dev12', choices=['dev12', 'all'])
    ap.add_argument('--ids', default='')
    ap.add_argument('--tag', default='')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    if a.cmd == 'estimate':
        estimate()
    else:
        run(a.run_id, a.ids, a.set, a.tag)
