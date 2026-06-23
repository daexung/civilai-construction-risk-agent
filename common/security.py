"""
공통 보안 모듈
- 프롬프트 인젝션 탐지
- 시스템 프롬프트 노출 요청 차단
- 비정상 입력값 검증
각 에이전트 노드에서 공통으로 import하여 사용한다.
"""

import logging
import re
import unicodedata

MAX_INPUT_LENGTH = 3000

# 프롬프트 인젝션 / 시스템 프롬프트 탈취 시도 패턴
INJECTION_PATTERNS = [
    # Korean: 기존 지시/규칙 무시
    r'이전\s*(지시|규칙|명령)\s*(들\s*)?(를|을|은|는)?\s*(무시|따르지|잊어|버려)',
    r'위의\s*(지시|규칙|명령)\s*(들\s*)?(를|을|은|는)?\s*(무시|따르지|잊어|버려)',
    r'앞선\s*(지시|규칙|명령)\s*(들\s*)?(를|을|은|는)?\s*(무시|따르지|잊어|버려)',
    r'규칙\s*(을|를)?\s*(무시|따르지|어겨)',
    r'지시\s*(을|를)?\s*(무시|따르지|어겨)',

    # Korean: 역할 변경/탈옥
    r'너는\s*이제',
    r'이제부터\s*너는',
    r'역할\s*(을|를)?\s*(바꿔|변경)',
    r'다른\s*역할로',
    r'개발자\s*모드',
    r'탈옥',
    r'제한\s*(을|를)?\s*해제',

    # Korean: 계산 조작
    r'계산\s*결과\s*(를|을)?\s*(바꿔|조작|변경)',
    r'단가\s*(를|을)?\s*조작',
    r'근거\s*없이\s*(10배|두\s*배|2배|3배|가산|할증)',

    # Korean: 시스템 내부 정보 (동사 없이도 언급 자체를 차단)
    r'시스템\s*프롬프트',
    r'내부\s*(지시|규칙|설정|프롬프트)',

    # English: ignore / disregard / override
    r'ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|messages)',
    r'disregard\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|messages)',
    r'forget\s+(all\s+)?(previous|prior|above)?\s*(instructions|rules|messages)',
    r'override\s+(the\s+)?(system|developer|instruction|rules|policy)',
    r'bypass\s+(the\s+)?(system|developer|instruction|rules|policy)',
    r'disable\s+(the\s+)?(safety|guardrail|policy|rules)',

    # English: role / jailbreak
    r'act\s+as\s+',
    r'pretend\s+to\s+be\s+',
    r'roleplay\s+as\s+',
    r'you\s+are\s+now\s+',
    r'new\s+role',
    r'jailbreak',
    r'\bdan\b',

    # Secrets / internal info (context-specific to reduce false positives)
    r'system\s*prompt',
    r'developer\s*message',
    r'(api|auth|access)\s*(key|token|secret)',
    r'(db|database)\s*(password|credential)',
]

# 시스템 내부 정보 요청 패턴
SYSTEM_INFO_PATTERNS = [
    r'프롬프트\s*(를|을)?\s*(출력|보여|알려|공개)',
    r'시스템\s*프롬프트\s*(를|을)?\s*(출력|보여|알려|공개)',
    r'지시문\s*(를|을)?\s*(출력|보여|알려|공개)',
    r'(설정|규칙)\s*(를|을)?\s*(출력|보여|알려|공개)',
    r'내부\s*(설정|규칙|지시)\s*(를|을)?\s*(출력|보여|알려|공개)',
    r'(show|reveal|print|display)\s+(me\s+)?(your\s+)?(system|developer)\s+(prompt|message|instructions)',
]

BLOCKED_RESPONSE = (
    "보안 정책상 요청을 처리할 수 없습니다. "
    "건설 현장 리스크 관련 질문을 입력해주세요."
)

_BLOCK_REASON_KO = {
    'injection':     '프롬프트 인젝션 시도 차단',
    'system_info':   '시스템 내부 정보 요청 차단',
    'input_too_long': '입력 길이 제한 초과 차단',
}


def normalize_input(user_input: str) -> str:
    """
    보안 검사를 위한 입력 정규화.
    - Unicode NFKC 정규화 (유니코드 우회 방지)
    - lowercase
    - 연속 공백 축약
    """
    text = unicodedata.normalize('NFKC', user_input)
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def block_reason_ko(reason: str) -> str:
    """reason 코드를 한국어 메시지로 변환."""
    return _BLOCK_REASON_KO.get(reason, f'보안 정책 위반 ({reason})')


def check_injection(user_input: str) -> tuple[bool, str]:
    """
    사용자 입력에서 프롬프트 인젝션 및 시스템 정보 탈취 시도를 탐지한다.

    Returns:
        (is_blocked: bool, reason: str)
        reason: 'injection' | 'system_info' | 'input_too_long' | ''
    """
    if not user_input:
        return False, ''

    if len(user_input) > MAX_INPUT_LENGTH:
        logging.warning(f'[SECURITY] 입력 길이 제한 초과: length={len(user_input)}')
        return True, 'input_too_long'

    text = normalize_input(user_input)

    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, text):
            logging.warning(
                f'[SECURITY] 프롬프트 인젝션 탐지: pattern={pattern}, input={user_input[:80]}'
            )
            return True, 'injection'

    for pattern in SYSTEM_INFO_PATTERNS:
        if re.search(pattern, text):
            logging.warning(
                f'[SECURITY] 시스템 정보 요청 탐지: pattern={pattern}, input={user_input[:80]}'
            )
            return True, 'system_info'

    return False, ''


def validate_quantity(value: float, field_name: str = '수량') -> tuple[bool, str]:
    """
    입력 수치가 유효한지 검증한다. 0 이하이면 차단.

    Returns:
        (is_valid: bool, error_msg: str)
    """
    if value <= 0:
        msg = f'{field_name}은 0보다 커야 합니다. 입력값: {value}'
        logging.warning(f'[SECURITY] 비정상 수치 탐지: {msg}')
        return False, msg
    return True, ''
