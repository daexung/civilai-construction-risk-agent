import os
from dotenv import load_dotenv

load_dotenv()

# [레거시] 노드별 모델 선택은 bedrock_models.py로 이동했다(MODEL_ROUTER/MODEL_EXTRACTOR/
# MODEL_SYNTHESIZE, 폴백 BEDROCK_MODEL_ID). 비용 에이전트만 MODEL_ID를 직접 사용한다.
# 아래 MODEL_ID 상수는 더 이상 router에서 import되지 않는다(미사용).
MODEL_ID = os.getenv("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
# 라우터 분류(classify_question)용 Bedrock 호출 파라미터.
# 응답은 {"intent","domains","missing_for_cost","reason"} JSON. reason이 한글로 길어지면
# 토큰 한도에서 잘려 JSON이 깨지므로(파싱 실패 시 CLARIFY로 폴백) 넉넉히 384로 둔다.
MAX_TOKENS = 384
TEMPERATURE = 0.1

# 최종 응답 합성(synthesize)용 — 분류보다 긴 출력이 필요
SYNTHESIS_MAX_TOKENS = 2500
SYNTHESIS_TEMPERATURE = 0.3

# [레거시] question_type A/B 라벨. 현재 분류는 intent(router.py)·domains 기반이며,
# 아래 dict는 import되지 않는다. 하위호환/로깅 참고용으로만 유지.
# A = 기상 선행(needs_weather), B = 그 외.
QUESTION_TYPES = {
    "A": {
        "name": "기상_악화",
        "description": (
            "비·눈·바람·태풍·한파·폭염 등 기상 원인이 질문에 명시된 공정 지연. "
            "예: '우천으로 타설 지연', '태풍으로 철골 작업 중단'"
        ),
    },
    "B": {
        "name": "현장_변경",
        "description": (
            "기상 원인이 없는 공정 지연·장비 대기·물량 변경·자재 단가 변동 등 모든 현장 변경. "
            "예: '공종이 3일 지연됐어요', '장비 대기 비용 산정', '물량이 늘었어요', '굴착기가 대기 중'"
        ),
    },
}
