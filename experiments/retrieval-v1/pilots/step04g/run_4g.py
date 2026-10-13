"""4g 평가 실행기. 고정된 질문 글만 현재 검색·선택·검증 경로에 넣고 결과를 step04g 실행 폴더에 남긴다.

  python -B run_4g.py run --run-id first-20                           # 20문 첫 실행(고정 순서)
  python -B run_4g.py run --run-id rep2 --tag rep2 --ids G15,G16,G07,G09   # 반복 확인(별도 실행 ID·캐시 태그)

- 실행 경로에는 질문 글만 전달한다. 기대값 파일·질문 ID에 따른 규칙은 전달하지 않는다(질문 ID는 원장·결과 파일 이름에만 쓴다).
- 새 유료 호출 상한: 시도 80회·예상 비용 $2(먼저 닿는 쪽). 모델·질문 벡터·추가 조회·재시도를 모두 센다. 4d~4f 캐시·원장은 쓰지 않는다.
- 같은 성공 입력의 캐시는 일반 재실행에만 쓴다. 반복 측정은 --tag를 달리해 캐시를 공유하지 않는다.
- 상한·장애로 못 돌린 질문은 결과에 '미실행'으로 남기고 분모와 따로 보고한다.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
WORK = HERE.parents[1]
sys.path.insert(0, str(WORK / 'src'))
import retrieve as rv  # noqa: E402
import select_verified as sv  # noqa: E402

CAPS = {'cost_usd': 2.0, 'attempts': 80}
LEDGER = HERE / 'ledger_4g.jsonl'
CACHE = HERE / 'cache'
QFILE = WORK / 'eval/questions_04g_2026-10-12.json'


def main(run_id, ids, tag):
    qs = json.loads(QFILE.read_text(encoding='utf-8'))['questions']
    want = set(ids.split(',')) if ids else None
    qs = [q for q in qs if not want or q['id'] in want]
    rt = rv.Retriever()
    caller = sv.ModelCaller(LEDGER, CACHE, CAPS, tag=tag, fallback_cache_dirs=[])
    vs = sv.VerifiedSelector(rt, caller)
    out_dir = HERE / 'runs' / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / 'meta.json').write_text(json.dumps({'run_id': run_id, 'tag': tag, 'started': time.strftime('%Y-%m-%dT%H:%M:%S'), 'versions': vs.versions(),
                                                   'caps': CAPS, 'model': caller.model, 'provider': caller.provider,
                                                   'question_file_sha256': hashlib.sha256(QFILE.read_bytes()).hexdigest(),
                                                   'ids': [q['id'] for q in qs]}, ensure_ascii=False, indent=1), encoding='utf-8')
    not_run = []
    for q in qs:
        f = out_dir / f"{q['id']}.json"
        if f.exists():
            print(q['id'], '이미 있음(건너뜀)')
            continue
        att, cost = caller.totals()
        if att >= CAPS['attempts'] - 3 or cost >= CAPS['cost_usd'] * 0.97:
            not_run.append(q['id'])
            print(q['id'], '상한 근접: 미실행', att, round(cost, 4))
            continue
        api0 = rt.api_calls
        try:
            r = vs.run(q['question'], qid=q['id'], run_id=run_id, fallback=False)
        except Exception as e:  # 실행 장애는 숨기지 않고 기록한다
            r = {'question': q['question'], 'qid': q['id'], 'run_id': run_id, 'method': 'exception', 'error': f'{type(e).__name__}: {str(e)[:300]}',
                 'final': {'status': 'execution_error', 'reasons': []}}
            print(q['id'], '실행 오류', r['error'])
        new_api = rt.api_calls - api0
        if new_api:
            with open(LEDGER, 'a', encoding='utf-8') as lf:
                lf.write(json.dumps({'run_id': run_id, 'qid': q['id'], 'role': 'query_embedding', 'ok': True, 'attempts': new_api,
                                     'cost_usd': round(new_api * 30 / 1e6 * 0.20, 7), 'latency_sec': None,
                                     'started': time.strftime('%Y-%m-%dT%H:%M:%S')}, ensure_ascii=False) + '\n')
        r['query_embedding_calls'] = new_api
        f.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
        fin = r.get('final', {})
        prim = [p['chunk_id'].split(':', 1)[-1][-22:] for p in r.get('validated', {}).get('primary', [])]
        print(q['id'], r.get('method'), fin.get('status'), 'primary', prim, '| rules', [x['rule'] for x in fin.get('reasons', [])],
              '| confirmed', len(fin.get('confirmed_chunks', [])), 'confirm_only', len(fin.get('confirmation_only_chunks', [])),
              'cc', len(r.get('confirmation_context', [])), '| lookups', [l['kind'] for l in r.get('lookups', [])],
              '| calls', [(c.get('role'), c.get('cached')) for c in r.get('calls', [])], '| emb', new_api, '| sec', r.get('latency_sec'))
    att, cost = caller.totals()
    (out_dir / 'summary.json').write_text(json.dumps({'run_id': run_id, 'not_run': not_run, 'attempts_total_ledger': att, 'cost_total_ledger': round(cost, 4),
                                                     'finished': time.strftime('%Y-%m-%dT%H:%M:%S')}, ensure_ascii=False, indent=1), encoding='utf-8')
    print('누적 시도', att, '누적 비용', round(cost, 4), '미실행', not_run)
    rt.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['run'])
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--ids', default='')
    ap.add_argument('--tag', default='')
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    main(a.run_id, a.ids, a.tag)
