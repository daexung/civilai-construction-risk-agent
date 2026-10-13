"""4c 질문 12개와 기대값 고정. 모델 호출 전에 실행한다. 원본은 eval/new_questions_04b_2026-10-12.json(수정하지 않음)."""
import hashlib
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
SRC = HERE.parents[1] / 'eval/new_questions_04b_2026-10-12.json'
# 선택 사유: 지시서가 정한 5개 + 4b에서 정상 처리한 7개(목록·규칙 2·값·다중 공종 2·자료 없음). 선택에는 정답 파일을 썼지만 실행 선택기에는 질문 글만 준다.
PICK = {
    'V02': '지시서 지정: 목록 일부 누락(4b 4/6)', 'V09': '지시서 지정: 같은 절 다른 표 선택', 'V11': '지시서 지정: 자료 낱말 불일치로 거부',
    'V12': '지시서 지정: 소속 미확정 설명·다른 표', 'V20': '지시서 지정: 자료 없음 낱말 근접',
    'V01': '4b 정상: 목록', 'V05': '4b 정상: 규칙+참조', 'V07': '4b 정상: 규칙+주석 표', 'V15': '4b 정상: 값(단위 기준 구분)',
    'V16': '4b 정상: 다중 공종+참조', 'V17': '4b 정상: 부분 참조 상태 보존', 'V19': '4b 정상: 자료 없음 거부',
}
# 허용 상태(모델의 근거 상태). 소속 미확정·부분 참조는 확정(supported)으로 승격하면 안 된다. 자료 없음은 not_found만 허용한다.
ALLOWED = {'V12': ['needs_confirmation'], 'V17': ['needs_confirmation'], 'V19': ['not_found'], 'V20': ['not_found']}
DEFAULT_ALLOWED = ['supported', 'needs_confirmation']


def main():
    raw = SRC.read_bytes()
    d = json.loads(raw.decode('utf-8'))
    Q = {q['id']: q for q in d['questions']}
    out = []
    for qid, why in PICK.items():
        q = Q[qid]
        no_data = q['category'] == 'no_data'
        out.append({
            'id': qid, 'pilot_role': why, 'category': q['category'], 'question': q['question'],
            'is_list': q['category'] == 'list', 'no_data': no_data, 'hold': q.get('interpretation_hold', False),
            'required_chunks': q.get('required_chunks', []),
            'required_sections': q['answer_sections'] if q['category'] == 'list' else [],
            'acceptable_sections': q.get('acceptable_also', []),
            'forbidden_chunks': q.get('forbidden_chunks', []), 'forbidden_sections': q.get('forbidden_sections', []),
            'required_references': q.get('required_references', []), 'required_states': q.get('required_states', {}),
            'expected_values': q.get('expected_values', {}),
            'allowed_status': ALLOWED.get(qid, DEFAULT_ALLOWED),
            'answer_sections': q['answer_sections'],
        })
    res = {'fixed_before_model_calls': True, 'source_file': 'eval/new_questions_04b_2026-10-12.json',
           'source_sha256': hashlib.sha256(raw).hexdigest(),
           'expectation_corrections': [], 'correction_note': '원문 대조(필수 조각 존재·절 일치·기대 값 문자열 포함) 결과 수정 없음',
           'note': '이미 4b에서 결과를 본 개발 자료(독립 평가 아님). 12문 결과를 전체 정확도로 쓰지 않는다.', 'questions': out}
    (HERE / 'expectations_fixed.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    print(len(out), res['source_sha256'])


if __name__ == '__main__':
    main()
