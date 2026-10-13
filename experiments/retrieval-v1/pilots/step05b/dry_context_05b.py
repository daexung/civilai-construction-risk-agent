"""5b 드라이런: 실제 DB·저장된 선택 응답 재생으로 모델에 줄 문맥(위치 식별자·줄)을 확인한다. 답변 생성 모델은 호출하지 않는다.

  python -B dry_context_05b.py G01 G03 G08 G10 FREE
선택·대조·목록 응답은 저장된 응답 재생(호출 0)이어야 한다. 새 호출이 필요하면 멈춘다(fallback=False, 한도 0).
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
os.environ['LOCAL_TRIAL_RETRIEVAL'] = 'on'

from backend.api import local_trial as lt  # noqa: E402
from backend.api import local_trial_answer as ta  # noqa: E402

FREE = '스파이럴덕트를 철판 두께 0.5㎜, 규격 250㎜로 해체할 때 m당 보통인부는 몇 인이야?'
QS = {q['id']: q['question'] for q in json.loads((HERE.parent / 'step05/trial_questions_05.json').read_text(encoding='utf-8'))['questions']}
QS['FREE'] = FREE


def main(ids):
    lt.CAPS['attempts'] = 0           # 새 유료 호출이 필요하면 ModelCaller가 cap_reached로 거절한다(드라이런 보호)
    e = lt.Engine()
    out = {}
    for qid in ids:
        q = QS[qid]
        captured = []

        def fake_generate(question, sources, request_id=''):
            ctx, provided, trunc = ta.build_context(sources)
            captured.append((ctx, provided, trunc))
            return {'source': 'verified_source', 'state': 'failed', 'code': 'dry_run'}
        e.generate = fake_generate
        r = e.vs.run(q, qid='dry-' + qid, run_id='dry-5b', fallback=False)
        calls = [(c.get('role'), c.get('cached'), c.get('ok')) for c in r.get('calls', [])]
        resp = e.build_response(q, 'dry-' + qid, r)
        print('=' * 100)
        print(qid, q)
        print('search status', resp['status'], '| answer_status', resp['answer_status'], '| calls', calls)
        for ctx, provided, trunc in captured:
            print(f'--- 모델 입력 문맥 ({len(ctx)}자, 잘림 {trunc}) ---')
            print(ctx)
            print('provided', {a: sorted(p['lines']) for a, p in provided.items()}, '/ n_total', {a: p['n_total'] for a, p in provided.items()})
        out[qid] = {'status': resp['status'], 'calls': calls, 'context_chars': [len(c[0]) for c in captured]}
    (HERE / 'dry_context_05b.json').write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('ledger attempts', e.totals(), '| query embedding api calls', e.rt.api_calls)


if __name__ == '__main__':
    main(sys.argv[1:] or ['G01', 'G03', 'G08', 'G10', 'FREE'])
