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


def validate_production() -> None:
    if not production():
        return
    allowed_origins()
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
