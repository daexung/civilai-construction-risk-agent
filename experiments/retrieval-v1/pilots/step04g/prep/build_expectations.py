"""4g 질문·기대값·근거 확인 기록 생성기(정답 준비용). 검색·선택 경로를 실행하지 않는다. 원문 DB(읽기 전용)와 원문 PDF의 글 층만 읽는다.

  python -B build_expectations.py      # eval/questions_04g_2026-10-12.json, expected_04g_..., evidence_check_04g_... 생성(이미 있으면 중단)

질문 글은 평가 실행기에 전달되는 유일한 입력이다. 기대값 파일은 실행 경로에 전달하지 않는다.
각 기대값은 원문 DB 조각을 읽고 원문 PDF 쪽(prep/pdf_pages/*.png)을 눈으로 대조해 정했다. 절 제목만 보고 만들지 않았다.
"""
import json
import re
import sys
import hashlib
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).parent
W = HERE.parents[2]                      # experiments/retrieval-v1
sys.path.insert(0, str(HERE))
import browse  # noqa: E402

PFX = 'pumsem-2026-errata1:'
EVAL = W / 'eval'
OUT_Q = EVAL / 'questions_04g_2026-10-12.json'
OUT_E = EVAL / 'expected_04g_2026-10-12.json'
OUT_C = EVAL / 'evidence_check_04g_2026-10-12.json'
PDF = W.parents[1] / 'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf'

rt, vs = browse.open_store()
ST = vs.store


def cid_of(suffix):
    c = [x for x in ST.chunk if x == suffix or x.endswith(suffix)]
    assert len(c) == 1, (suffix, c)
    return c[0]


def line_of(cid, *must):
    hits = [ln for ln in ST.lines(cid) if all(m in ln['text'] for m in must)]
    assert len(hits) >= 1, (cid, must)
    return {'n': hits[0]['n'], 'text': hits[0]['text'][:200], 'n_matches': len(hits)}


def sec(s):
    assert PFX + s in vs.sel.sec, s
    return PFX + s


def chunk_rec(suffix, *must, role='required', note=None):
    c = cid_of(suffix)
    ch = ST.chunk[c]
    rec = {'chunk_id': c, 'kind': ch['kind'], 'status': ch['status'], 'issues': ch['issues'], 'section_id': ch['section_id'], 'role': role}
    if must:
        rec['position'] = line_of(c, *must)
    if note:
        rec['note'] = note
    return rec


Q = []
E = []


def add(qid, typ, question, exp):
    Q.append({'id': qid, 'question': question})
    E.append({'id': qid, 'type': typ, 'question': question, **exp})


# ---------------- 값·품·단일 작업 6
add('G01', 'value', '건물 기계실 배관 ø100㎜에 건물용 적산열량계를 설치하면 개당 배관공은 몇 인이야?', {
    'risk': ['similar_tables_same_page', 'unit_basis'],
    'answer': '건물용 적산열량계 설치(기계설비 6-2-2), 수량(규격) ø100~125mm 열의 배관공 0.569인(개당). 보통인부도 0.569인.',
    'values': [{'label': '배관공', 'value': '0.569', 'unit': '인/개', 'column': 'ø100~125mm', 'unit_basis': '(개당)'}],
    'required_chunks': [chunk_rec('t:full-p736-o104146', '배관공', '0.569', note='표 기준 (개당), 열 ø100~125mm')],
    'recommended_chunks': [chunk_rec('complete-82c206c61e21:full-p736:n104176#0', note='[주] ③ 밸브·스트레이너·주위배관 설치 품은 별도 계상, ④ 전선관 배관·입선·지시부 별도')],
    'required_value_tokens': ['0.569'],
    'forbidden_sections': [sec('mech:6-2-1'), sec('mech:6-2-3')],
    'forbidden_note': '같은 쪽의 세대용(개당, ø13~32)·다음 쪽의 산업용(대당, 플랜트배관공)을 건물용 근거로 쓰면 안 된다',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation'], 'pdf_pages': [736]})

add('G02', 'value', '외벽에 방수모르타르를 15㎜ 두께로 바르려는데 ㎡당 미장공은 몇 인 들어?', {
    'risk': ['similar_tables_siblings', 'unit_basis', 'condition_table'],
    'answer': '방수모르타르 바름(건축 6-4-3), ㎡당, 15㎜이하 열의 미장공 0.056인(보통인부 0.043인). 외벽이면 높이(층수)에 따른 할증률(주석 표)을 가산할 수 있다.',
    'values': [{'label': '미장공', 'value': '0.056', 'unit': '인/㎡', 'column': '15㎜이하', 'unit_basis': '(㎡당)'}],
    'required_chunks': [chunk_rec('t:full-p662-o97235', '미장공', '0.056', note='표 기준 (㎡당), 열 15㎜이하')],
    'recommended_chunks': [chunk_rec('t:full-p662-o97262', note='[주석 표] 외벽 높이 할증률(층수별)'),
                           chunk_rec('complete-82c206c61e21:full-p662:n97258#0', note='[주] ③ 외벽은 높이에 따라 할증률 가산')],
    'required_value_tokens': ['0.056'],
    'forbidden_sections': [sec('arch:6-4-1'), sec('arch:6-4-2')],
    'forbidden_note': '같은 쪽의 시멘트 액체방수(바닥/수직부)·폴리머 시멘트 모르타르방수(1종/2종)는 다른 공법의 품이다',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation'], 'pdf_pages': [662]})

add('G03', 'value', '철판 두께 0.6㎜, 규격 400㎜짜리 스파이럴덕트를 해체하려면 m당 덕트공이 몇 인이야?', {
    'risk': ['two_block_table', 'shared_values', 'similar_tables_siblings', 'unit_basis'],
    'answer': '스파이럴덕트 해체(유지관리 4-1-3), m당, 철판두께 0.6㎜·규격 400㎜ 행의 덕트공 0.084인(보통인부 0.056인). 표는 두 블록(왼쪽 ø150~275, 오른쪽 300~600)이며 400㎜는 오른쪽 블록.',
    'values': [{'label': '덕트공', 'value': '0.084', 'unit': '인/m', 'column': '규격 400(철판두께 0.6)', 'unit_basis': '(m당)'},
               {'label': '보통인부', 'value': '0.056', 'unit': '인/m', 'column': '규격 400(철판두께 0.6)', 'unit_basis': '(m당)'}],
    'required_chunks': [chunk_rec('t:full-p978-o141173', note='오른쪽 블록(철판두께 0.6, 규격 300~600): 덕트공 0.064 0.074 0.084 0.104 0.114 0.123 0.132 / 보통인부 0.043 0.049 0.056 0.069 0.076 0.082 0.088')],
    'required_value_tokens': ['0.084'],
    'forbidden_sections': [sec('maint:4-1-2'), sec('maint:4-1-4'), sec('maint:4-1-5')],
    'forbidden_note': '각형덕트 해체·배관보온 해체·덕트보온 해체는 다른 품이다',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation'], 'pdf_pages': [978]})

add('G04', 'value', '잔디를 줄떼로 깔려고 하는데 하루에 몇 ㎡ 깔 수 있어?', {
    'risk': ['colloquial', 'inflected', 'similar_tables_siblings', 'daily_basis'],
    'answer': '잔디붙임(공통 4-1-1), 일당, 줄떼 170㎡(조경공 1인·보통인부 4인). 평떼는 150㎡. 구어체 "깔다"=붙임.',
    'values': [{'label': '시공량 줄떼', 'value': '170', 'unit': '㎡/일', 'column': '줄떼', 'unit_basis': '(일당)'}],
    'required_chunks': [chunk_rec('t:full-p147-o13556', '줄떼', '170', note='표 기준 (일당), 줄떼 170 / 평떼 150')],
    'recommended_chunks': [chunk_rec('complete-82c206c61e21:full-p147:n13582#0', note='[주] ② 줄떼는 10~30㎝ 간격 표준')],
    'required_value_tokens': ['170'],
    'forbidden_sections': [sec('common:4-1-2')],
    'forbidden_note': '판형잔디붙임(185㎡, 굴착기 포함)은 다른 품이다',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation'], 'pdf_pages': [147]})

add('G05', 'value', '관경 400㎜ 철근콘크리트관을 수밀밴드로 접합하면서 부설하면 하루에 몇 본 할 수 있어?', {
    'risk': ['similar_tables_same_page', 'shared_values', 'daily_basis'],
    'answer': '수밀밴드 접합 및 부설(토목 6-6-2), 일당, 관경 400㎜ 시공량 11본. 구성: 배관공(수도) 2인·보통인부 1인·양중장비 1대(관경 250~800 구간).',
    'values': [{'label': '시공량', 'value': '11', 'unit': '본/일', 'column': '관경 400', 'unit_basis': '(일당)'}],
    'required_chunks': [chunk_rec('t:full-p429-o57142', '400', '11', note='표 기준 (일당), 관경 400 → 시공량 11본, 배관공(수도) 2·보통인부 1·양중장비 1')],
    'required_value_tokens': ['11'],
    'forbidden_sections': [sec('civil:6-6-3'), sec('civil:6-6-1'), sec('civil:6-5-2')],
    'forbidden_note': '같은 쪽의 절단(개소당)·소켓관 접합·밴드 접합(다른 관종)은 다른 품이다',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation'], 'pdf_pages': [429]})

add('G06', 'value', '발코니에 앵커형 3단 안전난간대를 25m 설치하고 해체하려는데 비계공이 몇 인 들어?', {
    'risk': ['unit_basis', 'condition_table', 'missing_condition'],
    'answer': '안전난간대 설치 및 해체(공통 2-8-11), 10m당, 앵커형 3단 비계공 0.70인. 난간기둥 간격에 따라 요율(1.0m이하 110%, 1.5m이하 100%, 1.5m초과 90%)을 적용한다. 질문에 간격이 없다.',
    'values': [{'label': '비계공', 'value': '0.70', 'unit': '인/10m', 'column': '앵커형 3단', 'unit_basis': '(10m당)'}],
    'required_chunks': [chunk_rec('t:full-p110-o8812', '비계공', '0.70', note='표 기준 (10m당), 앵커형 3단 0.70'),
                        chunk_rec('t:full-p110-o8849', note='칸 안 표: 난간기둥 간격별 요율 1.0m이하 110% / 1.5m이하 100% / 1.5m초과 90%')],
    'recommended_chunks': [chunk_rec('complete-82c206c61e21:full-p110:n8868#0', note='[주] ② 2단·3단 정의, ④ 발끝막이판·보호망은 별도 계상')],
    'required_value_tokens': ['0.70', '110%'],
    'forbidden_sections': [sec('common:2-8-12')],
    'forbidden_note': '계단난간대(10개소당, 브라켓형·앵커형)는 다른 품이다',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation'],
    'status_note': '난간기둥 간격이 질문에 없어 조건 표를 함께 전달하면 충분. 보류도 허용한다', 'pdf_pages': [110]})

# ---------------- 규칙·참조·조건 4
add('G07', 'rule_negation', '송풍기를 설치하는 품에 송풍기 기초나 방진가대 설치도 같이 들어 있어?', {
    'risk': ['negation_exclusion'],
    'answer': '아니오. 송풍기 설치(기계설비 4-2-1) [주] ④ "송풍기 기초 및 방진가대, 전기배선 및 입선, 송풍기 주위 연결시설물은 제외되어 있다." 제외 조건.',
    'required_chunks': [chunk_rec('complete-82c206c61e21:full-p729:n103599#0', '④', '제외', note='[주] ④ 제외 조건')],
    'recommended_chunks': [chunk_rec('t:full-p728-o103564', note='송풍기 설치 표(대당)')],
    'required_text_tokens': ['제외되어 있다'],
    'forbidden_sections': [sec('mech:4-2-2'), sec('mech:4-2-3'), sec('mech:4-2-4'), sec('mech:4-2-5')],
    'forbidden_note': '배기팬·유인팬·레인지후드 설치는 다른 품이다',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation'], 'pdf_pages': [728, 729]})

add('G08', 'rule_reference', '폴리머 시멘트 모르타르방수를 바르는데 모르타르 배합은 어느 기준을 따라야 해?', {
    'risk': ['reference_resolved', 'similar_tables_siblings'],
    'answer': '폴리머 시멘트 모르타르방수 바름(건축 6-4-2) [주] ③ 모르타르 배합(시멘트, 모래)은 [건축부문] 9-1-1 모르타르 배합을 따른다(참조 resolved). 9-1-1은 ㎥당 보통인부(모래체가름 포함 0.66/제외 0.43)와 배합용적비별 재료량.',
    'required_chunks': [chunk_rec('complete-82c206c61e21:full-p662:n97227#0', '③', '9-1-1', note='[주] ③ 참조 문장')],
    'required_reference': {'expression': '9-1-1 모르타르 배합', 'section_id': sec('arch:9-1-1'), 'expected_target_status': 'resolved',
                           'target_chunks_any': [cid_of('w:arch:9-1-1'), cid_of('t:full-p679-o98733'), cid_of('t:full-p679-o98759')],
                           'note': '참조 대상 절의 내용이 최종 문맥에 읽을 수 있게 전달돼야 한다. 적용 여부는 판단하지 않는다(applicability unknown)'},
    'forbidden_sections': [sec('arch:6-4-1'), sec('arch:6-4-3')],
    'forbidden_note': '같은 참조 문장을 가진 시멘트 액체방수·방수모르타르 바름은 질문 대상이 아니다',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation'], 'pdf_pages': [662]})

add('G09', 'rule_unconfirmed', '호퍼스케일 30톤 이상 계량기를 설치하는 품에 기계 설치까지 들어 있어?', {
    'risk': ['membership_unconfirmed', 'negation_exclusion', 'must_hold'],
    'answer': '계량기 설치(기계설비 12-2-2) [주] ① "기계설치는 제외되어 있다"(PDF 776쪽, 표 다음 쪽 비고 아래). 표: Hopper Scale 대(30Ton이상) 계장공 10.8인·보통인부 7.2인(대당). 이 [주]는 DB에서 소속 미확정 설명(가까운 표에 붙이지 않음)이므로 확정 근거가 아니라 확인용 문맥으로 전달되고 보류(needs_confirmation)해야 한다.',
    'required_chunks': [chunk_rec('t:full-p775-o109468', 'HopperScale', '규격 대(30Ton이상)', note='Hopper Scale 대(30Ton이상) 계장공 10.8·보통인부 7.2(대)'),
                        chunk_rec('complete-82c206c61e21:full-p776:n109525#0', '①', '제외', role='required_unconfirmed',
                                  note='소속 미확정 [주] ①. 확정 근거로 올리면 안 되고 확인용으로 읽을 수 있어야 한다')],
    'recommended_chunks': [chunk_rec('complete-82c206c61e21:full-p776:n109522#0', note='비고: 옥외 노출 10% 가산, 시험조정 가산')],
    'required_text_tokens': ['기계설치는 제외되어 있다'],
    'forbidden_sections': [sec('mech:12-2-1'), sec('mech:12-2-3')],
    'forbidden_note': '자동제어기기 설치·도압배관은 다른 품이다',
    'status_expected': 'needs_confirmation', 'status_acceptable': ['needs_confirmation'],
    'status_note': 'supported이면 소속 미확정 설명을 확정으로 올린 것(승격 실패)', 'pdf_pages': [775, 776]})

add('G10', 'rule_condition', '나무 높이 2m짜리 관목을 군식으로 심을 때도 표의 일당 시공량을 그대로 적용하면 돼?', {
    'risk': ['condition_exceeds_table', 'similar_tables_siblings'],
    'answer': '식재(군식)(공통 4-2-3) [주] ③ "나무높이가 1.5m를 초과할 때는 나무높이에 비례하여 시공량을 감할 수 있다." 표의 나무높이 구간은 1.5m 이하까지다. 그대로 적용하지 않고 감할 수 있다.',
    'required_chunks': [chunk_rec('complete-82c206c61e21:full-p150:n13876#0', '③', '1.5m를 초과', note='[주] ③ 나무높이 1.5m 초과 조건'),
                        chunk_rec('t:full-p149-o13841', note='표(일당): 나무높이 0.3미만 440 ~ 1.2~1.5이하 140(주)')],
    'required_text_tokens': ['1.5m를 초과할 때는'],
    'forbidden_sections': [sec('common:4-2-2')],
    'forbidden_note': '단식 식재는 다른 품이다',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation'], 'pdf_pages': [149, 150]})

# ---------------- 공종 목록 4
add('G11', 'list', '수전 설치 품에는 어떤 종류가 있어?', {
    'risk': ['list_clear_scope'],
    'answer': '기계설비 7-2-1 매립형 욕조수전·7-2-2 샤워수전·7-2-3 세면기수전·7-2-4 씽크수전·7-2-5 손빨래수전 설치(5개).',
    'list_required_sections': [sec(f'mech:7-2-{i}') for i in range(1, 6)],
    'list_acceptable_additional': [sec('civil:6-8-6')],
    'list_forbidden_sections': [],
    'list_note': '새들분수전 분기(토목 6-8-6)는 수전 설치는 아니나 이름이 겹쳐 허용 추가로 본다',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation']})

add('G12', 'list', '난간을 설치하는 품은 어떤 게 있어?', {
    'risk': ['list_clear_scope', 'multi_division', 'homonym_temporary_vs_permanent'],
    'answer': '제목에 난간이 들어가고 설치하는 품: 공통 2-8-11 안전난간대·2-8-12 계단난간대·2-8-13 안전난간대(토목)·2-8-14 엘리베이터 난간틀·2-8-17 강재거푸집 작업용 난간(설치 및 해체), 건축 8-2-1 용접식난간·8-2-2 앵커고정식난간 설치. 유지관리 2-1-20 재래난간 철거공은 철거라 허용 추가.',
    'list_required_sections': [sec(s) for s in ('common:2-8-11', 'common:2-8-12', 'common:2-8-13', 'common:2-8-14', 'common:2-8-17', 'arch:8-2-1', 'arch:8-2-2')],
    'list_acceptable_additional': [sec('maint:2-1-20')],
    'list_forbidden_sections': [],
    'list_note': '가설 난간(설치 및 해체)과 영구 난간(설치)이 부문에 걸쳐 있다',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation']})

add('G13', 'list', '방수 관련 품에는 어떤 것들이 있어?', {
    'risk': ['list_broad_scope', 'homonym'],
    'answer': '제목에 방수가 들어간 건축 6-1-2·6-1-3·6-1-4·6-4-1·6-4-2·6-4-3·6-4-4·6-5-1·6-5-2·6-5-3(10개)이 핵심. 터널 방수(토목 3-4-1), 기존방수층 철거·제거(유지관리 3-2-10·3-2-11)와 건축 6장의 도막·시트 등은 허용 추가. 기계설비 10-4-2 방수구 설치는 소방 방수구라 방수 공사가 아니다.',
    'list_required_sections': [sec(s) for s in ('arch:6-1-2', 'arch:6-1-3', 'arch:6-1-4', 'arch:6-4-1', 'arch:6-4-2', 'arch:6-4-3', 'arch:6-4-4', 'arch:6-5-1', 'arch:6-5-2', 'arch:6-5-3')],
    'list_acceptable_additional': [sec(s) for s in ('civil:3-4-1', 'maint:3-2-10', 'maint:3-2-11', 'arch:6-1-1', 'arch:6-2-1', 'arch:6-2-2', 'arch:6-2-3',
                                                    'arch:6-3-1', 'arch:6-3-2', 'arch:6-3-3', 'arch:6-6-1')],
    'list_forbidden_sections': [sec('mech:10-4-2')],
    'list_note': '넓은 범위라 범위 확인 필요 보류도 허용',
    'status_expected': 'supported', 'status_acceptable': ['supported', 'needs_confirmation']})

add('G14', 'list', '접합 품에는 어떤 종류가 있어?', {
    'risk': ['list_ambiguous_scope', 'multi_division'],
    'answer': '"접합"은 토목 관부설(24개 절)과 기계설비 배관(19개 절) 등 여러 부문에 걸쳐 범위가 모호하다. 완전한 목록을 확정하지 말고 범위(부문·관종) 확인이 필요하다고 보류해야 한다.',
    'list_required_sections': [],
    'list_acceptable_additional': [x['section_id'] for x in vs.sel.sec.values() if x['level'] == 'section' and '접합' in x['title']],
    'list_forbidden_sections': [],
    'list_note': '범위 모호. supported로 완전한 목록을 주장하면 실패. needs_confirmation(범위 확인)이 기대',
    'status_expected': 'needs_confirmation', 'status_acceptable': ['needs_confirmation']})

# ---------------- 자료 없음 4 (검색 점검 근거는 evidence_check에 기록)
add('G15', 'no_data', '지중에 광케이블을 포설하는 품은 몇 인이야?', {
    'risk': ['no_data_new_target'],
    'answer': '현재 원문에 광케이블·광섬유·광통신·케이블 포설 품이 없다(원문 DB 조각 글과 원문 PDF 글 층 모두 0건). 읽은 범위 안에서 근거 없음.',
    'status_expected': 'not_found', 'status_acceptable': ['not_found'],
    'must_have_no_context': True, 'no_data_check': {'terms': ['광케이블', '광섬유', '광통신', '케이블포설', '케이블 포설']}})

add('G16', 'no_data', '시멘트 벽돌을 공장에서 제조하는 품은 얼마야?', {
    'risk': ['no_data_same_target_other_task'],
    'answer': '벽돌 쌓기·치장쌓기 등 시공 품은 있으나 벽돌 제조(생산) 품은 원문에 없다. 같은 대상의 다른 작업이므로 벽돌 쌓기 품을 근거로 쓰면 안 된다.',
    'status_expected': 'not_found', 'status_acceptable': ['not_found'],
    'must_have_no_context': True, 'forbidden_sections': [sec('arch:2-1-1'), sec('arch:2-1-2'), sec('arch:2-1-3')],
    'no_data_check': {'terms': ['벽돌제조', '벽돌 제조', '벽돌생산', '벽돌 생산', '벽돌공장'], 'related_terms': ['벽돌']}})

add('G17', 'no_data', '지열 히트펌프로 난방 열원을 설치하는 품은 얼마야?', {
    'risk': ['no_data_same_topic_other_method'],
    'answer': '난방 열원으로 보일러 설치 등은 있으나 지열·히트펌프는 원문에 없다(0건). 같은 주제의 다른 공법이므로 보일러 설치 품을 근거로 쓰면 안 된다.',
    'status_expected': 'not_found', 'status_acceptable': ['not_found'],
    'must_have_no_context': True,
    'no_data_check': {'terms': ['지열', '히트펌프', '열펌프'], 'related_terms': ['보일러 설치', '난방']}})

add('G18', 'no_data', '에스컬레이터를 설치하는 품은 몇 인이야?', {
    'risk': ['no_data_new_target'],
    'answer': '에스컬레이터·승강기 설치 품은 원문에 없다(0건). 엘리베이터는 가설 안전시설(난간틀, 추락방호망)만 있다.',
    'status_expected': 'not_found', 'status_acceptable': ['not_found'],
    'must_have_no_context': True, 'forbidden_sections': [sec('common:2-8-14'), sec('common:2-8-15')],
    'no_data_check': {'terms': ['에스컬레이터', '승강기'], 'related_terms': ['엘리베이터']}})

# ---------------- 번호·범위 모호 2
nums = {}
for x in vs.sel.sec.values():
    if x['level'] == 'section':
        nums.setdefault(x['number'], []).append(x)


def alts(*ns):
    return [x['section_id'] for n in ns for x in sorted(nums[n], key=lambda y: y['order'])]


add('G19', 'scope', '4-1-1 몇 인이야?', {
    'risk': ['number_general_expression'],
    'answer': '4-1-1은 공통(잔디붙임)·토목(철도안전처리)·건축(먹매김)·기계설비(일반펌프 설치)·유지관리(배관 해체) 5개 부문에 본문 절이 있다. 한 부문을 고르지 않고 부문별 대안과 부문 선택 필요를 기대한다. 대안을 정답·계산 대상으로 표시하면 안 된다.',
    'alternatives_sections': alts('4-1-1'),
    'status_expected': 'needs_confirmation', 'status_acceptable': ['needs_confirmation'], 'must_not_confirm_one_division': True})

add('G20', 'scope', '7-1-1과 7-1-2 일당 시공량이 얼마야?', {
    'risk': ['number_multiple'],
    'answer': '7-1-1은 공통(메쌓기)·토목(수중공사)·건축(금속기와 잇기)·기계설비(소변기 설치), 7-1-2는 공통(찰쌓기)·토목(예인선 조합)·건축(금속판 평잇기)·기계설비(대변기 설치)에 있다. 번호마다 부문별 대안과 부문 선택 필요를 기대한다.',
    'alternatives_sections': alts('7-1-1', '7-1-2'),
    'status_expected': 'needs_confirmation', 'status_acceptable': ['needs_confirmation'], 'must_not_confirm_one_division': True})

assert len(Q) == 20 and len({q['id'] for q in Q}) == 20

# ---------------- 반복 확인 위험 사례 4 (질문 고정 시 지정)
REPEAT = {'ids': ['G15', 'G16', 'G07', 'G09'],
          'why': {'G15': '자료 없음(새 대상)', 'G16': '같은 대상 다른 작업(자료 없음)', 'G07': '부정·제외 조건', 'G09': '소속 미확정 자료(보류 유지)'},
          'runs': 3, 'note': '첫 실행 + 별도 실행 ID 2회(캐시 태그 분리). 좋은 응답만 대표값으로 쓰지 않는다'}

# ---------------- 근거 확인 기록
body = ST.corpus_norm
chk = {'method': '원문 DB 조각 글(공백 제거·NFKC·소문자) 부분 문자열 + 원문 PDF 글 층(pymupdf) 쪽별 검색. 검색·선택 경로 미사용',
       'db_chunks': len(ST.chunk), 'no_data': {}}
import pymupdf  # noqa: E402
doc = pymupdf.open(str(PDF))
pages = [re.sub(r'\s+', '', doc[i].get_text()).lower() for i in range(len(doc))]
chk['pdf_pages'] = len(doc)


def secs_with(term, limit=8):
    out = {}
    for c, ch in ST.chunk.items():
        if term in ch['text']:
            k = ch['section_id'].replace(PFX, '') + ' ' + vs.sel.sec[ch['section_id']]['title'][:20]
            out[k] = out.get(k, 0) + 1
    return dict(list(out.items())[:limit]), len(out)


for e in E:
    nd = e.get('no_data_check')
    if not nd:
        continue
    rec = {'question': e['question'], 'terms': {}, 'related_terms': {}}
    for t in nd['terms']:
        tn = re.sub(r'\s+', '', t).lower()
        rec['terms'][t] = {'db_chunk_hits': body.count(tn), 'pdf_page_hits': [i + 1 for i, p in enumerate(pages) if tn in p][:10]}
    for t in nd.get('related_terms', []):
        tn = re.sub(r'\s+', '', t).lower()
        s, n = secs_with(t, 8)
        rec['related_terms'][t] = {'db_chunk_hits': body.count(tn), 'sections_n': n, 'sections_sample': s,
                                   'pdf_page_hits_n': sum(1 for p in pages if tn in p)}
    chk['no_data'][e['id']] = rec

chk['list_enumeration'] = {
    'G11_수전_titles': [x['section_id'].replace(PFX, '') + ' ' + x['title'] for x in vs.sel.sec.values() if x['level'] == 'section' and '수전' in x['title']],
    'G12_난간_titles': [x['section_id'].replace(PFX, '') + ' ' + x['title'] for x in vs.sel.sec.values() if x['level'] == 'section' and '난간' in x['title']],
    'G13_방수_titles': [x['section_id'].replace(PFX, '') + ' ' + x['title'] for x in vs.sel.sec.values() if x['level'] == 'section' and '방수' in x['title']],
    'G14_접합_n': sum(1 for x in vs.sel.sec.values() if x['level'] == 'section' and '접합' in x['title']),
}
chk['scope_enumeration'] = {n: [(x['division'], x['title']) for x in sorted(nums[n], key=lambda y: y['order'])] for n in ('4-1-1', '7-1-1', '7-1-2')}
chk['pdf_pages_read_by_eye'] = {'directory': 'experiments/retrieval-v1/pilots/step04g/prep/pdf_pages', 'pages': sorted(int(p.stem[1:]) for p in (HERE / 'pdf_pages').glob('p*.png'))}
chk['overlap_with_previous_questions'] = {
    'used_sections_count': len(browse.used_sections()),
    'answer_sections_in_used': sorted({s for e in E for s in ([c['section_id'] for c in e.get('required_chunks', [])] + e.get('list_required_sections', []))
                                       if s in browse.used_sections()})}

assert not OUT_Q.exists() and not OUT_E.exists(), '이미 고정됨: 덮어쓰지 않는다'
src_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
meta = {'fixed_on': '2026-10-12', 'purpose': '4g 독립 평가용 새 질문 20개(결과를 보기 전 고정). 정답 준비에 검색·선택 경로를 쓰지 않았다.',
        'release': 'rk-complete-82c206c61e21-37f81b5cfb1b', 'chunk_set': 'cs-37f81b5cfb1b-46f4f035c0fa'}
OUT_Q.write_text(json.dumps({**meta, 'questions': Q}, ensure_ascii=False, indent=1), encoding='utf-8')
OUT_E.write_text(json.dumps({**meta, 'builder_sha256': src_hash, 'repeat_risk_cases': REPEAT, 'expected': E}, ensure_ascii=False, indent=1), encoding='utf-8')
OUT_C.write_text(json.dumps({**meta, **chk}, ensure_ascii=False, indent=1), encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
print('questions', len(Q), 'hash', hashlib.sha256(OUT_Q.read_bytes()).hexdigest())
print('overlap', chk['overlap_with_previous_questions']['answer_sections_in_used'])
for k, v in chk['no_data'].items():
    print(k, {t: (r['db_chunk_hits'], r['pdf_page_hits']) for t, r in v['terms'].items()})
rt.close()
