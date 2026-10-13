"""5b 가상 검사: 모델이 실패·잘못된 위치·다른 행 값을 돌려주는 경우를 실제 응답 조립 경로(Engine.build_response)에 넣어 본다.
실제 모델을 부르지 않는다(호출 0). 결과는 실제 모델 실패율에 넣지 않는다(강제 실패).

  python -B virtual_checks_05b.py   → virtual_checks_05b.json
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'experiments/retrieval-v1/checks'))
sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
os.environ.pop('LOCAL_TRIAL_RETRIEVAL', None)

import test_local_trial_05b as T  # noqa: E402

FREE = '스파이럴덕트를 철판 두께 0.5㎜, 규격 250㎜로 해체할 때 m당 보통인부는 몇 인이야?'
CASES = [
    ('v01_정상(G03 0.6/400 → S2.1 0.084)', T.raw([T.ev('S2.1', '0.084', '인')], conclusion='철판 두께 0.6㎜, 규격 400㎜ 덕트공은 m당 0.084인이에요.'), T.Q, (1,)),
    ('v02_없는 줄(S2.99)', T.raw([T.ev('S2.99', '0.084', '인')], conclusion='0.084인이에요.'), T.Q, (1,)),
    ('v03_모델에 주지 않은 행(S2.5, 표 5행)', T.raw([T.ev('S2.5', '0.050', '인')], conclusion='0.050인이에요.'), T.Q, (1,)),
    ('v04_다른 자료 줄(S9.1)', T.raw([T.ev('S9.1', '0.084', '인')], conclusion='0.084인이에요.'), T.Q, (1,)),
    ('v05_위치 없는 인용(위치 비어 있음)', T.raw([T.ev('', '0.084', '인')], conclusion='0.084인이에요.'), T.Q, (1,)),
    ('v06_옛 방식 조각 ID로 인용', T.raw([T.ev('t:duct', '0.084', '인')], conclusion='0.084인이에요.'), T.Q, (1,)),
    ('v07_가짜 값(0.999)', T.raw([T.ev('S2.1', '0.999', '인')], conclusion='0.999인이에요.'), T.Q, (1,)),
    ('v08_같은 청크의 다른 행 값(0.037, 2행)', T.raw([T.ev('S2.1', '0.037', '인')], conclusion='0.037인이에요.'), T.Q, (1,)),
    ('v09_같은 줄의 다른 규격 값(0.074, 350칸)', T.raw([T.ev('S2.1', '0.074', '인')], conclusion='0.074인이에요.'), T.Q, (1,)),
    ('v10_같은 줄의 왼쪽 묶음 값(0.036, 0.5㎜)', T.raw([T.ev('S2.1', '0.036', '인')], conclusion='0.036인이에요.'), T.Q, (1,)),
    ('v11_자유 질문(0.5㎜·250㎜)에 0.6㎜·250㎜ 값 대체', T.raw([T.ev('S2.6', '0.036', '인')], conclusion='보통인부는 0.036인이에요.'), FREE, (6,)),
    ('v12_시간 초과', TimeoutError('slow'), T.Q, (1,)),
    ('v13_JSON 아님', 'not json', T.Q, (1,)),
    ('v14_금액 표현', T.raw([T.ev('S2.1', '0.084', '인')], conclusion='0.084인이며 약 1,000원이에요.'), T.Q, (1,)),
    ('v15_인용하지 않은 줄의 숫자(2%)', T.raw([T.ev('S2.1', '0.084', '인')], conclusion='0.084인이에요.', explanation='공구손료는 인력품의 2%예요.'), T.Q, (1,)),
    ('v16_모델이 값을 못 찾음(not_found)', T.raw([], status='not_found'), T.Q, (1,)),
]


def main():
    rows = []
    for name, out, q, sel in CASES:
        eng, resp = T.run(out, question=q, selected=sel)
        row = {'case': name, 'search_status': resp['search_status'], 'answer_status': resp['answer_status'], 'answer_status_label': resp['answer_status_label'],
               'reason_code': resp['answer_status_reason']['code'], 'generation_source': resp['generation']['source'], 'detail_code': resp['generation'].get('code'),
               'answer_text': resp['answer'], 'citations': [c['location'] for c in resp.get('citations', [])],
               'values': [v['value'] for v in resp.get('value_claims', []) if v.get('declared')], 'sources_visible': len(resp['sources'])}
        rows.append(row)
        print(f"{name:55s} {resp['search_status']:10s} -> {resp['answer_status']:22s} {row['reason_code']:24s} {row['detail_code']} | cites {row['citations']} | src {row['sources_visible']}")
    (HERE / 'virtual_checks_05b.json').write_text(json.dumps({'note': '강제 실패를 실제 응답 조립 경로에 넣은 가상 검사. 실제 모델 호출 0회. 실제 모델 실패율에 넣지 않는다.', 'rows': rows},
                                                         ensure_ascii=False, indent=1), encoding='utf-8')
    # 브라우저에서 원문 확인 필요 표시를 보기 위한 강제 응답(시간 초과 사례)
    eng, resp = T.run(TimeoutError('slow'))
    (HERE / 'virtual_response_source_check_needed.json').write_text(json.dumps(resp, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
