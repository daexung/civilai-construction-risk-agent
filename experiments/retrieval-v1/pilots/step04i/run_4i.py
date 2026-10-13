"""4i 비교 실행기: 저장된 응답만으로 네 가지 보류 권한 방식(가·나·다·라)을 재생한다. 새 모델·임베딩·외부 호출 0.

  python -B run_4i.py --method ga --set 60          # 가: 4h 기준선(낱말 부재 권한 유지, 대조 경고 권한 유지)
  python -B run_4i.py --method na --set g20         # 나: 낱말 부재 권한 해제
  python -B run_4i.py --method da --set dev         # 다: 대조 경고 권한 해제
  python -B run_4i.py --method ra --set g09         # 라: 둘 다 해제

- 비교용 복사본(select_verified_cmp.py)에서 최종 상태·근거 역할·정상/검토용/진단 분류를 다시 계산한다(결과 JSON의 이유를 지우는 집계가 아니다).
- 캐시 미스는 외부 호출하지 않고 '미실행'으로 기록한다. 로컬이 아닌 소켓 연결은 즉시 막는다(시도 횟수를 기록).
- 질문 벡터는 기존 캐시만 쓴다(embed_queries=False).
"""
import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
WORK = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(WORK / 'src'))
sys.path.insert(0, str(WORK / 'pilots/step04d'))

BLOCKED = []
_orig_connect = socket.socket.connect


def _guard(self, addr):
    host = addr[0] if isinstance(addr, tuple) else addr
    if host not in ('127.0.0.1', '::1', 'localhost') and not str(host).startswith('/'):
        BLOCKED.append(str(host))
        raise ConnectionError(f'4i: 로컬이 아닌 연결 차단 {host}')
    return _orig_connect(self, addr)


socket.socket.connect = _guard

import retrieve as rv  # noqa: E402
import select_verified_cmp as sv  # noqa: E402
import specs  # noqa: E402

METHODS = {'ga': {'weak_term': True, 'warning': True}, 'na': {'weak_term': False, 'warning': True},
           'da': {'weak_term': True, 'warning': False}, 'ra': {'weak_term': False, 'warning': False}}
CACHES = [WORK / 'pilots/step04h/cache', WORK / 'pilots/step04g/cache', WORK / 'pilots/step04f/cache', WORK / 'pilots/step04e/cache', WORK / 'pilots/step04d/cache']


class ReplayOnly:
    """저장된 성공 응답만 돌려준다. 없으면 미실행(replay_cache_miss). 쓰기 없음."""

    def __init__(self, tag=''):
        os.environ['AGENT_LLM'] = 'on'
        from backend.agent.tools.llm import client as llm
        self.provider, self.model = llm.provider_name(), llm.model_name()
        self.tag = tag
        self.hits, self.misses = 0, 0

    def totals(self):
        return 0, 0.0

    def call(self, role, system, prompt, schema, qid=None, run_id=None):
        key = sv.sha([self.model, self.provider, system, prompt, schema, sv.CONFIG['llm'], self.tag])
        for d in CACHES:
            f = d / f'{key}.json'
            if f.exists():
                rec = json.loads(f.read_text(encoding='utf-8'))
                if rec.get('ok'):
                    self.hits += 1
                    rec.update(cached=True, cache_source=d.parent.name, cost_usd=0.0, attempts=0, replay=True)
                    return rec
        self.misses += 1
        return {'ok': False, 'error': 'replay_cache_miss', 'attempts': 0, 'cost_usd': 0.0, 'cached': False, 'role': role, 'replay': True}


def questions(which):
    out = []
    if which == '60':
        for s in specs.load_specs():
            if s.get('tasks'):
                for k, t in enumerate(s['tasks']):
                    out.append((f"{s['id']}_{k}", t['query'], ''))
            else:
                out.append((s['id'], s['question'], ''))
    elif which == 'g20':
        for c in json.loads((WORK / 'eval/questions_04g_2026-10-12.json').read_text(encoding='utf-8'))['questions']:
            out.append(('4g_' + c['id'], c['question'], ''))
    elif which == 'dev':
        for fn in ('pilots/step04e/dev_cases_4e.json', 'pilots/step04f/dev_cases_4f.json'):
            d = json.loads((WORK / fn).read_text(encoding='utf-8'))
            for v in d.values():
                if isinstance(v, list) and v and isinstance(v[0], dict) and 'question' in v[0] and 'expected_lookup' not in v[0]:
                    for c in v:
                        out.append((c['id'], c['question'], ''))
        d = json.loads((WORK / 'pilots/step04h/dev_cases_4h.json').read_text(encoding='utf-8'))
        for c in d['new_cases']:
            out.append((c['id'], c['question'], ''))
    elif which == 'g09':
        q = [c for c in json.loads((WORK / 'eval/questions_04g_2026-10-12.json').read_text(encoding='utf-8'))['questions'] if c['id'] == 'G09'][0]['question']
        for tag in ('', 'rep2', 'rep3'):
            out.append((f"4g_G09{'_' + tag if tag else '_first'}", q, tag))
    return out


def main(method, which):
    sv.AUTH.update(METHODS[method])
    rt = rv.Retriever(embed_queries=False)
    out_dir = HERE / 'runs' / f'{method}-{which}'
    out_dir.mkdir(parents=True, exist_ok=True)
    vs = None
    stats = {'replayed_cases': 0, 'not_run': [], 'cache_hits': 0, 'cache_misses': 0, 'errors': []}
    for qid, q, tag in questions(which):
        f = out_dir / f'{qid}.json'
        if f.exists():
            continue
        caller = ReplayOnly(tag)
        if vs is None:
            vs = sv.VerifiedSelector(rt, caller)      # 구조 저장소 적재가 무거우므로 한 번만 만들고 질문마다 재생기(태그)만 바꾼다
        vs.caller = caller
        try:
            r = vs.run(q, qid=qid, run_id=f'{method}-{which}', fallback=False)
        except Exception as e:
            r = {'question': q, 'qid': qid, 'method': 'exception', 'error': f'{type(e).__name__}: {str(e)[:200]}', 'final': {'status': 'execution_error', 'reasons': []}}
            stats['errors'].append((qid, r['error']))
        miss = caller.misses
        stats['cache_hits'] += caller.hits
        stats['cache_misses'] += miss
        r['replay_misses'] = miss
        r['auth'] = dict(METHODS[method])
        if miss or r.get('method') == 'exception':
            stats['not_run'].append(qid)
        else:
            stats['replayed_cases'] += 1
        f.write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
    stats['external_connection_attempts_blocked'] = len(BLOCKED)
    (out_dir / 'summary.json').write_text(json.dumps({'method': method, 'set': which, **stats, 'code_sha256': sv.hashlib.sha256(Path(sv.__file__).read_bytes()).hexdigest(),
                                                       'finished': time.strftime('%Y-%m-%dT%H:%M:%S')}, ensure_ascii=False, indent=1), encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    print(method, which, json.dumps(stats, ensure_ascii=False))
    rt.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--method', required=True, choices=list(METHODS))
    ap.add_argument('--set', required=True, choices=['60', 'g20', 'dev', 'g09'])
    a = ap.parse_args()
    main(a.method, a.set)
