"""라우터 및 추출 노드용 Bedrock 모델 관리

에이전트별 모델을 환경변수로 관리하여,
필요시 모델을 독립적으로 변경 가능하도록 지원.
"""

import os
import sys
import boto3

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

from langchain_aws import ChatBedrock

try:
    from logger import get_logger
except ImportError:
    import logging
    def get_logger(name):
        return logging.getLogger(name)

log = get_logger(__name__)

# 에이전트별 모델 환경변수 매핑
AGENT_MODEL_ENV = {
    'router': 'MODEL_ROUTER',           # 질문 분류
    'extractor': 'MODEL_EXTRACTOR',     # 입력값 추출
    'synthesize': 'MODEL_SYNTHESIZE',   # 최종 답변 합성
}

# Fallback & 기본값
DEFAULT_MODEL = os.getenv('BEDROCK_MODEL_ID', 'us.anthropic.claude-haiku-4-5-20251001-v1:0')
DEFAULT_REGION = os.getenv('AWS_BEDROCK_REGION', 'us-east-1')


def get_model_id(agent_name: str) -> str:
    """에이전트별 모델 ID 반환

    Args:
        agent_name: 'router', 'extractor', 'synthesize' 등

    Returns:
        모델 ID 문자열
    """
    env_var = AGENT_MODEL_ENV.get(agent_name)

    if env_var:
        model_id = os.getenv(env_var)
        if model_id:
            log.debug(f"[{agent_name}] 모델: {model_id}")
            return model_id

    # Fallback
    log.debug(f"[{agent_name}] 기본 모델 사용: {DEFAULT_MODEL}")
    return DEFAULT_MODEL


def get_bedrock_client():
    """Bedrock boto3 클라이언트 반환"""
    return boto3.client(
        'bedrock-runtime',
        region_name=DEFAULT_REGION,
    )


def get_bedrock_chat(agent_name: str) -> ChatBedrock:
    """ChatBedrock 인스턴스 반환 (라우터/합성용)

    Args:
        agent_name: 'router', 'synthesize' 등

    Returns:
        ChatBedrock 인스턴스
    """
    model_id = get_model_id(agent_name)
    return ChatBedrock(
        model_id=model_id,
        region_name=DEFAULT_REGION,
    )


# 편의 함수들
def get_router_model_id() -> str:
    """라우터 분류 모델 ID"""
    return get_model_id('router')


def get_extractor_model_id() -> str:
    """입력값 추출 모델 ID"""
    return get_model_id('extractor')


def get_synthesize_model() -> ChatBedrock:
    """최종 답변 합성 모델"""
    return get_bedrock_chat('synthesize')


def get_synthesize_model_id() -> str:
    """최종 답변 합성 모델 ID"""
    return get_model_id('synthesize')
