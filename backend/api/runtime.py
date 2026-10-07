"""Deployment settings without embedding production hosts or secrets in code."""
import os
from urllib.parse import parse_qs, urlsplit

LOCAL_ORIGINS = ['http://localhost:5173', 'http://127.0.0.1:5173',
                 'http://localhost:3000', 'http://127.0.0.1:3000']


def production() -> bool:
    return os.getenv('APP_ENV', 'development') == 'production'


def allowed_origins() -> list[str]:
    configured = os.getenv('ALLOWED_ORIGINS', '')
    origins = [value.strip().rstrip('/') for value in configured.split(',') if value.strip()]
    if not origins:
        if production():
            raise ValueError('Production requires ALLOWED_ORIGINS')
        return LOCAL_ORIGINS
    for origin in origins:
        url = urlsplit(origin)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.path or url.query or url.fragment or '*' in origin:
            raise ValueError('ALLOWED_ORIGINS must contain exact HTTP origins')
        if production() and url.scheme != 'https':
            raise ValueError('Production origins must use HTTPS')
    return origins


def estimate_max_items() -> int:
    """복수 공종 견적의 공종 수 상한. 기본값은 기존 코드 값(3)이며 ESTIMATE_MAX_ITEMS로만 바꾼다."""
    from backend.agent.estimate.state import max_items_setting
    return max_items_setting()


def estimate_plan_input_enabled() -> bool:
    """구조화 계획(estimate_plan) 입력은 서버의 명시적인 로컬 검사 설정에서만 받는다.

    요청 값으로는 켤 수 없고, 운영(APP_ENV=production)에서는 설정이 있어도 꺼진다.
    """
    return not production() and os.getenv('ESTIMATE_PLAN_INPUT') == 'local'


def validate_production() -> None:
    if not production():
        return
    allowed_origins()
    if os.getenv('ESTIMATE_PLAN_INPUT'):
        raise ValueError('ESTIMATE_PLAN_INPUT is a local test setting and must not be set in production')
    estimate_max_items()
    if len(os.getenv('QUOTA_HASH_SECRET', '')) < 32:
        raise ValueError('Production requires an independent QUOTA_HASH_SECRET of at least 32 characters')
    if urlsplit(os.getenv('SUPABASE_URL', '')).scheme != 'https' or not os.getenv('SUPABASE_PUBLISHABLE_KEY'):
        raise ValueError('Production requires HTTPS Supabase URL and publishable key')
    database = urlsplit(os.getenv('CHAT_DATABASE_URL', ''))
    if not database.hostname or database.hostname in ('localhost', '127.0.0.1'):
        raise ValueError('Production requires an external CHAT_DATABASE_URL')
    if parse_qs(database.query).get('sslmode', [''])[0] not in ('require', 'verify-ca', 'verify-full'):
        raise ValueError('Production database connection must require TLS')
    if database.hostname.endswith('.pooler.supabase.com') and database.port != 5432:
        raise ValueError('Use the Supabase session pooler, not the transaction pooler')
    if os.getenv('AGENT_LLM') not in ('on', 'off'):
        raise ValueError('Production requires an explicit AGENT_LLM=on or off setting')
