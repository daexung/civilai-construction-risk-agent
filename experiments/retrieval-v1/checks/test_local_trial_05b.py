"""5b단계 답변 계층 점검(모델·DB 호출 없음).
실행: .venv\\Scripts\\python -B -m pytest experiments/retrieval-v1/checks/test_local_trial_05b.py -q

- 모델은 원문 위치만 고르고 인용문은 코드가 모델에 준 줄에서 가져온다
- 없는 줄·다른 자료·모델에 주지 않은 행·모양이 틀린 식별자는 거절한다(비슷한 식별자로 맞추지 않는다)
- 값은 인용한 줄 안에 있어야 하고 질문의 치수 조건과 같은 열·행 묶음·순서 위치여야 한다(다른 행·열 값 거절)
- 검색 상태와 답변 상태 분리, 생성 실패·검증 실패 → 원문 확인 필요(모델 성공으로 세지 않음)
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.pop('LOCAL_TRIAL_RETRIEVAL', None)

from backend.api import local_trial as lt  # noqa: E402
from backend.api import local_trial_answer as ta  # noqa: E402

ANN = ' [공동값 full-p978-o1:c{n}: 0.5·0.6 7행에 표시된 같은 값(여러 행에 표시된 같은 값을 중복 합산하지 않음)]'
RIGHT = (' | 0.6' + ANN.format(n=21) + ' | 규격(㎜) 300 350 400 450 500 550 600' + ANN.format(n=22) +
         ' | 덕트공 (인) 0.064 0.074 0.084 0.104 0.114 0.123 0.132' + ANN.format(n=23) +
         ' | 보통인부 (인) 0.043 0.049 0.056 0.069 0.076 0.082 0.088' + ANN.format(n=24))
LEFT = [('0.5', 'ø150이하', '0.036', '0.024'), ('0.5', '160', '0.037', '0.025'), ('0.5', '180', '0.041', '0.028'),
        ('0.5', '200', '0.045', '0.030'), ('0.6', '225', '0.050', '0.033'), ('0.6', '250', '0.055', '0.036'), ('0.6', '275', '0.059', '0.040')]
DUCT_LINES = [f'철판두께 (㎜) {t} | 규격 (㎜) {g} | 덕트공 (인) {d} | 보통인부 (인) {b}' + RIGHT for t, g, d, b in LEFT]
DUCT_FRAME = ['기준: (m당)', '머리글: 철판두께 (㎜) | 규격 (㎜) | 덕트공 (인) | 보통인부 (인) | 철판두께 (㎜) | 규격(㎜) | 덕트공 (인) | 보통인부 (인)']
G01_FRAME = ['기준: (개당)', '머리글: 구분 | 단위 | 수 량 (규격) ø50mm | 수 량 (규격) ø65~80mm | 수 량 (규격) ø100~125mm | 수 량 (규격) ø150mm']
G01_LINE = '배관공 | 단위 인 | 수 량 (규격) ø50mm 0.415 | 수 량 (규격) ø65~80mm 0.476 | 수 량 (규격) ø100~125mm 0.569 | 수 량 (규격) ø150mm 0.727'
NOTE = ['① 본 품은 옥내배관에 적산열량계를 설치하는 기준이다.', '② 본 품은 가배관 철거를 포함한다.', '⑤ 공구손료는 인력품의 2%로 계상한다.']


def source(cid, kind, texts, frame=(), selected=(1,), div='유지관리부문', no='4-1-3', title='스파이럴덕트 해체'):
    legend, notes = {}, {}
    lines = [{'n': i, 'text': t, 'display': ta.compact(t, legend, notes), 'selected': i in selected, 'page': 978, 'search_uid': f'u{i}'}
             for i, t in enumerate(texts, 1)]
    return {'id': cid, 'kind': kind, 'division': div, 'section_no': no, 'section_title': title, 'pdf_page': 978, 'frame': list(frame), 'lines': lines,
            'shared_legend': [{'n': k, 'text': t} for k, t in sorted(notes.items())]}


def duct(selected=(1,)):
    return [source('r:note', '설명', NOTE), source('t:duct', '표', DUCT_LINES, DUCT_FRAME, selected)]


def ctx(sources):
    c, provided, trunc = ta.build_context(sources)
    assert not trunc
    return c, provided


def raw(evidence, status='answered', conclusion='답입니다.', explanation='', unmatched=()):
    return {'status': status, 'conclusion': conclusion, 'explanation': explanation, 'evidence': evidence, 'unmatched_conditions': list(unmatched)}


def ev(loc, value='', unit=''):
    return {'location': loc, 'value': value, 'unit': unit}


Q = '철판 두께 0.6㎜, 규격 400㎜짜리 스파이럴덕트를 해체하려면 m당 덕트공이 몇 인이야?'


# ---------------------------------------------------------------- 문맥: 모델에 준 줄만 위치 식별자를 가진다
def test_context_gives_only_selected_rows_with_location_ids_and_compact_marks():
    c, provided = ctx(duct(selected=(1,)))
    assert sorted(provided['S2']['lines']) == [1] and provided['S2']['n_total'] == 7
    assert 'S2.1 ' in c and 'S2.2 ' not in c                       # 선택하지 않은 행은 주지 않는다
    assert '[공동값#1]' in c and '공동값 full-p978' not in c       # 긴 표지는 짧은 표지 + 관계 설명
    assert '공동값#1: 0.5·0.6 7행에 표시된 같은 값' in c
    assert sorted(provided['S1']['lines']) == [1, 2, 3]            # 설명은 전체 줄


def test_context_refuses_when_over_budget_instead_of_silently_trimming():
    big = [source('t:big', '표', ['가 | ' + '1' * 800] * 5, DUCT_FRAME, selected=())]
    _, _, truncated = ta.build_context(big)
    assert truncated


# ---------------------------------------------------------------- 정상: 위치만 고르면 코드가 인용문을 가져온다
def test_valid_value_answer_quotes_come_from_code_lines_not_model_text():
    _, provided = ctx(duct())
    out = ta.validate(raw([ev('S2.1', '0.084', '인')], conclusion='철판 두께 0.6㎜, 규격 400㎜ 덕트공은 m당 0.084인이에요.'), Q, provided)
    assert out['state'] == 'answered' and out['code'] == 'verified'
    c = out['citations'][0]
    assert c['quote'] == DUCT_LINES[0] and c['chunk_id'] == 't:duct' and c['line'] == 1          # DB 원문 줄 그대로
    assert c['unit_basis'] == '기준: (m당)' and c['first_cell'] == '철판두께 (㎜) 0.5'
    assert '[공동값#' in c['display'] and c['shared_notes'][0]['cell'] == 'full-p978-o1:c21'
    v = out['values'][0]
    assert v['column_name'] == '덕트공 (인)' and v['alignment'] == 'column_row' and v['matches_question_conditions'] is True
    assert [x['number'] for x in v['conditions']] == [0.6, 400.0] and all(x['ok'] for x in v['conditions'])
    assert v['row_label'] == '0.6'                                                       # 값이 속한 오른쪽 묶음의 첫 칸(왼쪽 0.5 칸이 아님)
    assert [x['cell'] for x in v['conditions']] == ['0.6', '규격(㎜) 400']               # 조건이 맞은 칸(목록 칸은 같은 순서 위치의 값)


def test_location_with_brackets_is_accepted_but_not_other_forms():
    _, provided = ctx(duct())
    ok = raw([ev('[S2.1]', '0.084', '인')], conclusion='0.084인이에요.')
    assert ta.validate(ok, Q, provided)['state'] == 'answered'


# ---------------------------------------------------------------- 위치 거절(비슷한 식별자로 맞추지 않음)
@pytest.mark.parametrize('loc,code', [
    ('S2.99', 'line_missing'),                      # 없는 줄
    ('S2.5', 'line_not_provided'),                  # 같은 표의 다른 행이지만 모델에 주지 않음
    ('S9.1', 'source_not_provided'),                # 다른(주지 않은) 자료
    ('S2.1 덕트공 0.084', 'location_malformed'),    # 글이 붙은 식별자
    ('t:duct', 'location_malformed'),               # 옛 조각 ID 방식
    ('s2.1', 'location_malformed'),
    ('', 'location_malformed'),
])
def test_bad_locations_are_rejected(loc, code):
    _, provided = ctx(duct())
    out = ta.validate(raw([ev(loc, '0.084', '인')], conclusion='0.084인이에요.'), Q, provided)
    assert out['state'] == 'failed' and out['code'] == code


def test_citation_without_location_or_with_empty_evidence_fails():
    _, provided = ctx(duct())
    assert ta.validate(raw([]), Q, provided)['code'] == 'citations_missing'
    assert ta.validate(raw([{'value': '0.084'}]), Q, provided)['code'] == 'schema'
    assert ta.validate({'status': 'answered'}, Q, provided)['code'] == 'schema'
    assert ta.validate(raw([ev('S2.1')], status='maybe'), Q, provided)['code'] == 'schema'


# ---------------------------------------------------------------- 값: 가짜·다른 행·다른 열·다른 조건
def test_fake_value_and_other_row_value_are_rejected_even_if_in_the_chunk():
    _, provided = ctx(duct(selected=(1,)))
    fake = ta.validate(raw([ev('S2.1', '0.999', '인')], conclusion='0.999인이에요.'), Q, provided)
    assert fake['state'] == 'failed' and fake['code'] == 'value_not_in_line'
    # 0.037은 같은 표 2행의 값(원문 청크 안에는 있음). 모델에 준 1행 줄에는 없으므로 통과하면 안 된다.
    other = ta.validate(raw([ev('S2.1', '0.037', '인')], conclusion='0.037인이에요.'), Q, provided)
    assert other['state'] == 'failed' and other['code'] == 'value_not_in_line'


def test_value_in_wrong_column_position_is_not_accepted():
    _, provided = ctx(duct())
    # 0.074는 규격 350 칸의 값(목록 둘째). 질문은 400(셋째). 같은 줄에 있어도 위치가 다르다.
    out = ta.validate(raw([ev('S2.1', '0.074', '인')], conclusion='0.074인이에요.'), Q, provided)
    assert out['state'] == 'condition_unconfirmed' and out['code'] == 'condition_not_in_row'


def test_value_from_the_other_half_of_the_table_is_not_accepted():
    _, provided = ctx(duct())
    # 0.036은 좌측(0.5㎜·ø150이하) 값. 같은 줄에 규격 400·0.6㎜가 있어도 열 묶음이 다르다.
    out = ta.validate(raw([ev('S2.1', '0.036', '인')], conclusion='0.036인이에요.'), Q, provided)
    assert out['state'] == 'condition_unconfirmed' and out['code'] == 'condition_not_in_row'


def test_free_question_05_and_250_never_gets_the_06_value():
    q = '철판 두께 0.5㎜, 규격 250㎜ 스파이럴덕트를 해체하면 m당 보통인부는 몇 인이야?'
    _, provided = ctx(duct(selected=(6,)))          # 6행: 철판 0.6 · 규격 250 · 0.055/0.036
    out = ta.validate(raw([ev('S2.6', '0.055', '인')], conclusion='0.055인이에요.'), q, provided)
    assert out['state'] == 'condition_unconfirmed' and out['code'] == 'condition_not_in_row'
    assert out['rejected_claim']['conditions'][0] == {'number': 0.5, 'ok': False, 'where': 'row', 'cell': None}
    # 0.5㎜·400㎜ 조합도 마찬가지(0.5는 왼쪽, 400은 오른쪽 묶음)
    _, p1 = ctx(duct(selected=(1,)))
    out2 = ta.validate(raw([ev('S2.1', '0.084', '인')], conclusion='0.084인이에요.'), '철판 0.5㎜ 규격 400㎜ 덕트공은?', p1)
    assert out2['state'] == 'condition_unconfirmed'


def test_undeclared_number_in_answer_text_still_gets_the_same_cell_check():
    _, provided = ctx(duct())
    good = raw([ev('S2.1', '0.084', '인')], conclusion='덕트공 0.084인, 보통인부 0.056인이에요.')
    out = ta.validate(good, Q, provided)
    assert out['state'] == 'answered' and {v['value'] for v in out['values']} == {'0.084', '0.056'}
    bad = raw([ev('S2.1', '0.084', '인')], conclusion='덕트공 0.084인, 보통인부 0.043인이에요.')    # 0.043은 규격 300의 값
    assert ta.validate(bad, Q, provided)['state'] == 'condition_unconfirmed'


def test_numbers_not_in_cited_lines_or_question_fail():
    _, provided = ctx(duct())
    out = ta.validate(raw([ev('S2.1', '0.084', '인')], conclusion='0.084인이며 3개소면 합계가 달라져요.'), Q, provided)
    assert out['state'] == 'failed' and out['code'] == 'numbers'
    # 인용하지 않은 줄(공구손료 2%)의 숫자는 쓸 수 없다
    out = ta.validate(raw([ev('S2.1', '0.084', '인')], conclusion='0.084인이에요.', explanation='공구손료는 2%예요.'), Q, provided)
    assert out['state'] == 'failed' and out['code'] == 'numbers'
    out = ta.validate(raw([ev('S2.1', '0.084', '인'), ev('S1.3')], conclusion='0.084인이에요.', explanation='공구손료는 2%예요.'), Q, provided)
    assert out['state'] == 'answered'


def test_wide_row_table_column_binding():
    s = [source('t:g01', '표', [G01_LINE, G01_LINE.replace('배관공', '보통인부')], G01_FRAME, selected=(1,), div='기계설비부문', no='6-2-2', title='적산열량계')]
    _, provided = ctx(s)
    q = '건물 기계실 배관 ø100㎜에 적산열량계를 설치하면 개당 배관공은 몇 인이야?'
    ok = ta.validate(raw([ev('S1.1', '0.569', '인')], conclusion='ø100㎜는 0.569인이에요.'), q, provided)
    assert ok['state'] == 'answered' and ok['values'][0]['conditions'][0]['where'] == 'column_header'
    assert ok['values'][0]['column_name'].endswith('ø100~125mm')
    for wrong in ('0.476', '0.727', '0.415'):            # 같은 줄의 다른 규격 열
        out = ta.validate(raw([ev('S1.1', wrong, '인')], conclusion=f'{wrong}인이에요.'), q, provided)
        assert out['state'] == 'condition_unconfirmed', wrong
    # 범위 안 값(110)은 100~125 열로 본다. 범위 밖(130)은 이 줄에 맞는 열이 없다.
    q110 = q.replace('100', '110')
    assert ta.validate(raw([ev('S1.1', '0.569', '인')], conclusion='0.569인이에요.'), q110, provided)['state'] == 'answered'
    q130 = q.replace('100', '130')
    assert ta.validate(raw([ev('S1.1', '0.569', '인')], conclusion='0.569인이에요.'), q130, provided)['state'] == 'condition_unconfirmed'


def test_range_and_inequality_boundaries_are_condition_labels_not_values():
    frame = ['기준: (일당)', '머리글: 구분 | 단위 | 수량 | 나무높이(m) | 시공량(주)']
    line = '조경공 보통인부 | 단위 인 인 | 수량 3 1 | 나무높이(m) 1.2~1.5이하 | 시공량(주) 140'
    s = [source('t:g10', '표', [line], frame, selected=(1,), div='공통부문', no='4-2-3', title='식재'),
         source('r:g10', '설명', ['③ 나무높이가 1.5m를 초과할 때는 나무높이에 비례하여 시공량을 감할 수 있다.'], div='공통부문', no='4-2-3', title='식재')]
    _, provided = ctx(s)
    q = '나무 높이 2m짜리 관목을 군식으로 심을 때도 표의 일당 시공량을 그대로 적용하면 돼?'
    # 표 행의 경계값 1.5를 가리키며 설명(S2.1)을 근거로 답하는 것은 통과한다
    ok = ta.validate(raw([ev('S1.1', '1.5', 'm'), ev('S2.1')], conclusion='1.5m를 초과하면 시공량을 감할 수 있어 표를 그대로 적용하면 안 돼요.'), q, provided)
    assert ok['state'] == 'answered' and ok['values'][0]['alignment'] == 'condition_boundary'
    # 같은 행의 시공량 140을 2m 조건의 값으로 쓰면 거절된다(2m는 이 행의 범위가 아니다)
    bad = ta.validate(raw([ev('S1.1', '140', '주')], conclusion='2m에서도 140주를 적용해요.'), q, provided)
    assert bad['state'] == 'condition_unconfirmed'
    # 표 칸의 범위 끝값(125)은 답변 글에 나와도 값으로 기록하지 않는다
    s2 = [source('t:g01', '표', [G01_LINE], G01_FRAME, selected=(1,), div='기계설비부문', no='6-2-2', title='적산열량계')]
    _, p2 = ctx(s2)
    out = ta.validate(raw([ev('S1.1', '0.569', '인')], conclusion='ø100~125mm 규격은 0.569인이에요.'),
                      '건물 기계실 배관 ø100㎜에 적산열량계를 설치하면 개당 배관공은 몇 인이야?', p2)
    assert out['state'] == 'answered' and [v['value'] for v in out['values']] == ['0.569']


def test_indicator_part_word_is_not_an_instruction_leak():
    s = [source('t:g01', '표', [G01_LINE], G01_FRAME, selected=(1,), div='기계설비부문', no='6-2-2', title='적산열량계'),
         source('r:g01', '설명', ['④ 전선관 배관 및 입선, 지시부 설치는 별도 계상한다.'], div='기계설비부문', no='6-2-2', title='적산열량계')]
    _, provided = ctx(s)
    q = '건물 기계실 배관 ø100㎜에 적산열량계를 설치하면 개당 배관공은 몇 인이야?'
    ok = ta.validate(raw([ev('S1.1', '0.569', '인'), ev('S2.1')], conclusion='0.569인이에요.', explanation='지시부 설치는 별도로 계상해요.'), q, provided)
    assert ok['state'] == 'answered'
    assert ta.validate(raw([ev('S1.1', '0.569', '인')], conclusion='0.569인이며 지시에 따라 계산했어요.'), q, provided)['code'] == 'instruction_leak'


def test_unit_must_appear_in_row_or_frame():
    _, provided = ctx(duct())
    out = ta.validate(raw([ev('S2.1', '0.084', '㎡')], conclusion='0.084㎡예요.'), Q, provided)
    assert out['state'] == 'failed' and out['code'] == 'unit_not_in_row'


# ---------------------------------------------------------------- 모델이 값을 못 찾음 / 형식 위반
def test_model_unmatched_conditions_are_filtered_to_question_wording():
    _, provided = ctx(duct())
    out = ta.validate(raw([], status='condition_unconfirmed', unmatched=['철판 두께 0.6㎜', '지어낸 조건']), Q, provided)
    assert out['state'] == 'condition_unconfirmed' and out['unmatched'] == ['철판 두께 0.6㎜']
    assert ta.validate(raw([], status='not_found'), Q, provided)['code'] == 'model_unmatched'


@pytest.mark.parametrize('conclusion,code', [('0.084인이에요. 금액은 1,000원이에요.', 'money'), ('제공된 문맥에 따르면 0.084인이에요.', 'instruction_leak'),
                                             ('S2.1에 따라 0.084인이에요.', 'instruction_leak'), ('3-9-9 절의 0.084인이에요.', 'section')])
def test_text_checks(conclusion, code):
    _, provided = ctx(duct())
    out = ta.validate(raw([ev('S2.1', '0.084', '인')], conclusion=conclusion), Q, provided)
    assert out['state'] == 'failed' and out['code'] == code


# ---------------------------------------------------------------- 상태 매핑
@pytest.mark.parametrize('search,gen,expected', [
    ('supported', {'state': 'answered'}, ('confirmed', 'verified')),
    ('supported', {'state': 'condition_unconfirmed', 'code': 'model_unmatched'}, ('condition_unconfirmed', 'model_unmatched')),
    ('supported', {'state': 'condition_unconfirmed', 'code': 'condition_not_in_row'}, ('condition_unconfirmed', 'condition_not_in_row')),
    ('supported', {'state': 'failed', 'code': 'numbers'}, ('source_check_needed', 'validation_failed')),
    ('supported', {'state': 'failed', 'code': 'location_malformed'}, ('source_check_needed', 'validation_failed')),
    ('supported', {'state': 'failed', 'code': 'generation_failed'}, ('source_check_needed', 'generation_failed')),
    ('supported', {'state': 'failed', 'code': 'context_budget'}, ('source_check_needed', 'context_budget')),
    ('supported', None, ('source_check_needed', 'generation_failed')),
    ('needs_confirmation', None, ('needs_confirmation', 'search_needs_confirmation')),
    ('not_found', None, ('not_found', 'search_not_found')),
])
def test_answer_state_mapping(search, gen, expected):
    assert ta.answer_state(search, gen) == expected


def test_supported_search_is_never_confirmed_without_a_verified_answer():
    for g in (None, {'state': 'failed', 'code': 'x'}, {'state': 'condition_unconfirmed'}, {}):
        assert ta.answer_state('supported', g)[0] != 'confirmed'


# ---------------------------------------------------------------- 연결부(Engine): 생성 실패·상태 전달·인용 표시 일치
class _LLM:
    def __init__(self, out):
        self.out = out

    def generate(self, *a, **k):
        if isinstance(self.out, Exception):
            raise self.out
        return type('R', (), {'text': json.dumps(self.out) if not isinstance(self.out, str) else self.out, 'attempts': 1, 'provider': 'stub'})()


class _Caller:
    usage: list = []

    def totals(self):
        return 0, 0.0


class _Eng(lt.Engine):
    def __init__(self, out, sources):
        import threading
        self.llm, self.qa_model, self.prompt, self.rows = _LLM(out), 'm', 'p', []
        self.caller, self.lock, self.sources = _Caller(), threading.Lock(), sources
        self.sv = type('SV', (), {'PRICE': {'input_per_m': 0.3, 'output_per_m': 2.5}})
        self.versions = {'release_id': 'r', 'chunk_set_id': 'c', 'select_verified_code_sha256': 'h' * 64}

    def totals(self):
        return 0, 0.0

    def ledger_add(self, qid, ok, attempts, latency, cost):
        self.rows.append((qid, ok))

    def source_of(self, cid, role, validated, note=None):
        return next((s for s in self.sources if s['id'] == cid), None)

    def short_label(self, cid):
        return cid

    def review_note(self, cid, r):
        return ''


def run(out, question=Q, selected=(1,), search='supported'):
    eng = _Eng(out, duct(selected))
    r = {'final': {'status': search, 'answer_evidence_chunks': ['r:note', 't:duct'], 'review_chunks': [], 'reasons': []}, 'validated': {}, 'diagnostic_candidates': []}
    return eng, eng.build_response(question, 'rid', r)


def test_engine_confirmed_marks_exact_cited_lines_only():
    eng, resp = run(raw([ev('S2.1', '0.084', '인')], conclusion='덕트공은 0.084인이에요.'))
    assert resp['status'] == 'supported' and resp['search_status'] == 'supported'
    assert resp['answer_status'] == 'confirmed' and resp['answer_status_label'] == '답변 확인'
    assert resp['generation']['source'] == 'llm' and eng.rows == [('rid', True)]
    duct_src = next(s for s in resp['sources'] if s['id'] == 't:duct')
    assert duct_src['cited'] and [l['n'] for l in duct_src['lines'] if l['cited']] == [1]
    note_src = next(s for s in resp['sources'] if s['id'] == 'r:note')
    assert not note_src['cited'] and not any(l['cited'] for l in note_src['lines'])
    assert resp['citations'][0]['location'] == 'S2.1' and resp['value_claims'][0]['value'] == '0.084'
    assert resp.get('applicability', 'unknown') == 'unknown'


def test_engine_condition_unconfirmed_keeps_sources_and_never_answers_with_other_row():
    q = '철판 두께 0.5㎜, 규격 250㎜ 스파이럴덕트를 해체하면 m당 덕트공은 몇 인이야?'
    eng, resp = run(raw([ev('S2.6', '0.055', '인')], conclusion='0.055인이에요.'), question=q, selected=(6,))
    assert resp['answer_status'] == 'condition_unconfirmed' and resp['status'] == 'supported'
    assert '0.055' not in resp['answer'] and resp['sources']          # 값을 쓰지 않고 원문은 계속 보인다
    assert resp['generation']['source'] == 'verified_source' and not resp['citations']
    assert any(c['code'] == 'condition_unconfirmed' for c in resp['confirmations'])


def test_engine_model_failure_modes_become_source_check_needed_with_distinct_reasons():
    cases = [(TimeoutError('slow'), 'generation_failed'), ('not json', 'validation_failed'),
             (raw([ev('S2.99', '0.084', '인')], conclusion='0.084인이에요.'), 'validation_failed'),
             (raw([ev('S2.1', '0.777', '인')], conclusion='0.777인이에요.'), 'validation_failed')]
    for out, reason in cases:
        eng, resp = run(out)
        assert resp['answer_status'] == 'source_check_needed', out
        assert resp['answer_status_reason']['code'] == reason
        assert resp['status'] == 'supported' and resp['sources'] and resp['generation']['source'] == 'verified_source'
        assert not resp['citations'] and not any(s['cited'] for s in resp['sources'])


def test_engine_needs_confirmation_and_not_found_unchanged():
    _, resp = run(None, search='needs_confirmation')
    assert resp['answer_status'] == 'needs_confirmation' and not resp['sources'] and resp['related']
    _, resp = run(None, search='not_found')
    assert resp['answer_status'] == 'not_found' and not resp['sources'] and not resp['review_material']


# ---------------------------------------------------------------- 5b 저장 결과(있을 때만)
RESULT = Path(__file__).resolve().parents[1] / 'pilots/step05b/trial_results_05b_final.json'


@pytest.mark.skipif(not RESULT.exists(), reason='5b 최종 결과 파일 없음')
def test_saved_5b_results_state_consistency():
    rows = json.loads(RESULT.read_text(encoding='utf-8'))['rows']
    for r in rows:
        x = r.get('response')
        if not x:
            continue
        a = x['answer_status']
        assert x['search_status'] == x['status']
        if a == 'confirmed':
            assert x['generation']['source'] == 'llm' and x['citations']
            cited_lines = {(c['chunk_id'], c['line']) for c in x['citations']}
            shown = {(s['id'], l['n']) for s in x['sources'] for l in s['lines'] if l.get('cited')}
            assert cited_lines == shown                                  # 인용 위치와 출처 카드 표시가 일치
            for c in x['citations']:                                     # 인용문은 원문 줄 그대로
                src = next(s for s in x['sources'] if s['id'] == c['chunk_id'])
                assert next(l for l in src['lines'] if l['n'] == c['line'])['text'] == c['quote']
        else:
            assert not x['citations'] and not any(l.get('cited') for s in x['sources'] for l in s['lines'])
        if a in ('condition_unconfirmed', 'source_check_needed'):
            assert x['sources']                                          # 원문은 계속 열어 볼 수 있다
        if a == 'needs_confirmation':
            assert not x['sources']
        if a == 'not_found':
            assert not (x['sources'] or x['review_material'] or x['related'])
        assert x.get('applicability', 'unknown') == 'unknown'
