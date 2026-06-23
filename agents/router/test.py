"""
end-to-end 테스트 — 실행할 때마다 랜덤 케이스 1개 선택
실행: python test.py (construction_risk_agent-router 폴더에서)
"""
import random
import sys
from langchain_core.messages import HumanMessage
from logger import get_logger
from graph import graph

log = get_logger(__name__)

TEST_CASES = [
    # ── 단독 — 에이전트 1개만 의미 있게 응답 ──────────────────────
    {
        'name': 'A-1 | 단독 — 기상 (의사결정 질문, 비용 산정 의도 없음)',
        'expected_type': 'A',
        'query': '내일 태풍 예보가 있는데 철골 세우기 작업을 중단해야 할까요?',
    },
    {
        'name': 'B-1 | 단독 — 장비 에이전트만 응답',
        'expected_type': 'B',
        'query': '타워크레인 50×12 1대가 자재 반입 지연으로 4일 대기 중입니다. 추가 비용이 얼마인가요?',
    },
    {
        'name': 'B-2 | 단독 — 자재 에이전트만 응답',
        'expected_type': 'B',
        'query': 'H파일을 100톤 추가로 발주해야 하는데, 추가 자재비가 얼마나 들까요?',
    },
    {
        'name': 'B-3 | 단독 — 인건비 에이전트만 응답',
        'expected_type': 'B',
        'query': '콘크리트 타설 200㎥ 공사에 필요한 인건비를 산출해 주세요.',
    },

    # ── 복합 — 2개 이상의 에이전트가 함께 응답/연계 ────────────────
    {
        'name': 'A-2 | 복합 — 기상 체인 (weather → 장비+인건비 자동 연계)',
        'expected_type': 'A',
        'query': '폭설로 콘크리트 타설이 이틀째 멈춰 있습니다. 대응 방안을 알려주세요.',
    },
    {
        'name': 'B-4 | 복합 — 장비 + 인건비',
        'expected_type': 'B',
        'query': '철골 세우기 공정이 3일 지연돼서 장비가 대기 중입니다. 장비 대기 비용과 투입 인력 인건비를 각각 산정해 주세요.',
    },
    {
        'name': 'B-5 | 복합 — 자재 + 장비',
        'expected_type': 'B',
        'query': '자재 반입 지연으로 콘크리트 펌프차가 5일째 대기 중이고, 철근도 200톤 추가 발주해야 합니다. 장비 대기 비용과 추가 자재비를 모두 산정해 주세요.',
    },
    {
        'name': 'B-6 | 복합 — 자재 + 인건비',
        'expected_type': 'B',
        'query': '철근 200톤을 추가 발주했고, 그 철근 가공·설치에 필요한 인건비도 함께 알고 싶습니다. 추가 자재비와 인건비를 모두 산정해 주세요.',
    },
    {
        'name': 'B-7 | 복합 — 장비 + 자재 + 인건비 전체',
        'expected_type': 'B',
        'query': '방수공사 물량이 늘어나서 자재비, 투입 인력 인건비, 장비 대기 비용을 모두 산정해 주세요.',
    },
    {
        'name': 'B-8 | 경계 — 전부 무관 (모든 에이전트 거절 시 안내 메시지 확인)',
        'expected_type': 'B',
        'query': '오늘 현장 회식 메뉴 추천해주세요.',
    },
]

_STUB_MARKER = '미구현'


def run_test(case: dict):
    print(f'\n{"="*65}')
    print(f'[테스트] {case["name"]}')
    print(f'예상 분류: {case["expected_type"]}')
    print(f'질문: {case["query"]}')
    print('=' * 65)

    log.info(f"=== 테스트 시작: {case['name']} ===")
    log.info(f"질문: {case['query']}")

    try:
        result = graph.invoke({
            'messages': [HumanMessage(content=case['query'])],
            'project_id': 'PJT-001',
        })
    except Exception:
        log.exception('graph.invoke 실패')
        raise

    actual_type = result.get('question_type', '?')

    # 분류 정확도 출력
    match = '✅' if actual_type == case['expected_type'] else '❌'
    print(f'\n{match} 분류 결과: {actual_type} (예상: {case["expected_type"]})')
    log.info(f"분류 결과: {actual_type} (예상: {case['expected_type']}, 일치: {match == '✅'})")

    # 에이전트 응답 출력 (stub 제외) — 콘솔에만 표시, 로그는 디버깅 정보만 기록
    for key, label in [
        ('weather_response', '기상 에이전트'),
        ('equipment_response', '장비 에이전트'),
        ('labor_cost_response', '인건비 에이전트'),
        ('material_response', '자재 에이전트'),
    ]:
        resp = result.get(key)
        if resp and _STUB_MARKER not in resp:
            print(f'\n[{label}]\n{resp}')

    final_response = result.get('final_response')
    if final_response:
        print(f'\n{"─"*65}\n[최종 답변]\n{final_response}')

    log.debug("--- 처리 완료 ---")

if __name__ == '__main__':
    import sys
    case = random.choice(TEST_CASES)
    run_test(case)
