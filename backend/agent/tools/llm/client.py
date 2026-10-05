"""Gemini 설명 문장 클라이언트. 숫자는 compose에서 검증한다."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Callable

from backend.paths import ROOT
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
TIMEOUT_MS = 20_000
MAX_ATTEMPTS = 3
RETRY_DELAYS = (1, 2)
_CLIENTS: dict[tuple[str, str], object] = {}
_CLIENT_LOCK = Lock()


class LLMUnavailable(Exception):
    """LLM을 쓸 수 없거나 호출이 실패했다. 호출부는 기본 문장으로 대신한다."""

    def __init__(self, message: str, *, attempts: int = 0, provider: str | None = None):
        super().__init__(message)
        self.attempts = attempts
        self.provider = provider


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    attempts: int


def _env_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    env = ROOT / ".env"
    if env.exists():
        # Read only the requested setting; never log or expose the file contents.
        for line in env.read_text(encoding="utf-8").splitlines():
            key, sep, candidate = line.partition("=")
            if sep and key.strip() == name:
                return candidate.strip().strip('"').strip("'") or None
    return None


def provider_name() -> str:
    configured = os.environ.get("LLM_PROVIDER")
    if not configured:
        if CONFIG_PATH.exists():
            configured = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("provider", "studio")
        else:
            configured = "studio"
    provider = configured.strip().lower()
    if provider not in ("vertex", "studio"):
        raise LLMUnavailable(f"지원하지 않는 LLM_PROVIDER: {provider}")
    return provider


def model_name() -> str:
    """LLM_MODEL 환경변수, 없으면 config.json의 모델 이름."""
    env_model = os.environ.get("LLM_MODEL")
    if env_model:
        return env_model
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["model"]
    raise LLMUnavailable("모델 설정이 없습니다: LLM_MODEL 또는 agent/tools/llm/config.json")


def _transient(exc: Exception) -> bool:
    status = getattr(exc, "code", None)
    if callable(status):
        try:
            status = status()
        except Exception:
            status = None
    response = getattr(exc, "response", None)
    status = status or getattr(response, "status_code", None)
    if status in (400, 401, 403, "400", "401", "403"):
        return False
    if status in (429, 503, "429", "503"):
        return True
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    message = f"{type(exc).__name__}: {exc}".upper()
    return any(token in message for token in (
        "UNAVAILABLE", "RESOURCE_EXHAUSTED", "429", "503", "TIMEOUT", "TIMED OUT",
        "CONNECTION RESET", "CONNECTION ERROR", "CONNECTION ABORTED",
        "CONNECTIONERROR", "CONNECTERROR", "CONNECTIONRESET",
    ))


def _safe_error(exc: Exception, secrets: list[str]) -> str:
    message = f"{type(exc).__name__}: {exc}"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    message = re.sub(r"(?i)(key|token|authorization)(\s*[:=]\s*)[^\s,;]+", r"\1\2[REDACTED]", message)
    return message[:200]


def _create_client(provider: str, key: str):
    from google import genai

    return (genai.Client(vertexai=True, api_key=key) if provider == "vertex"
            else genai.Client(api_key=key))


def _get_client(provider: str, key: str):
    """Share one client per provider/key, including concurrent first calls."""
    with _CLIENT_LOCK:
        cache_key = (provider, key)
        if cache_key not in _CLIENTS:
            _CLIENTS[cache_key] = _create_client(provider, key)
        return _CLIENTS[cache_key]


def warmup_client() -> bool:
    """Create the shared client without sending a generation request."""
    if os.environ.get("AGENT_LLM", "off") != "on":
        return False
    provider, key = None, None
    try:
        provider = provider_name()
        key_name = "VERTEX_API_KEY" if provider == "vertex" else "GEMINI_API_KEY"
        key = _env_value(key_name)
        if not key:
            raise LLMUnavailable(f"{key_name} 없음", provider=provider)
        _get_client(provider, key)
    except LLMUnavailable:
        raise
    except Exception as exc:
        raise LLMUnavailable(_safe_error(exc, [key or ""]), provider=provider) from exc
    return True


def generate(
    prompt: str,
    system: str,
    *,
    request_fn: Callable[[str, str, str, int], str] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock_fn: Callable[[], float] = time.monotonic,
    response_schema: dict | None = None,
    model: str | None = None,
    timeout_ms: int = TIMEOUT_MS,
    max_attempts: int = MAX_ATTEMPTS,
    retry_delays: list[float] | tuple[float, ...] = RETRY_DELAYS,
) -> LLMResult:
    """Call the selected Gemini provider, retrying only transient capacity errors."""
    started = clock_fn()
    if timeout_ms <= 0 or max_attempts < 1 or len(retry_delays) < max_attempts - 1:
        raise ValueError("invalid LLM retry or timeout configuration")
    if os.environ.get("AGENT_LLM", "off") != "on":
        raise LLMUnavailable("AGENT_LLM=off", attempts=0)

    provider = provider_name()
    key_name = "VERTEX_API_KEY" if provider == "vertex" else "GEMINI_API_KEY"
    key = _env_value(key_name)
    if not key:
        raise LLMUnavailable(f"{key_name} 없음", attempts=0, provider=provider)
    model = model or model_name()
    secrets = [key, _env_value("GOOGLE_CLOUD_PROJECT") or ""]

    if request_fn is None:
        try:
            if (clock_fn() - started) * 1000 >= timeout_ms:
                raise LLMUnavailable(f"LLM 호출 시간 상한 {timeout_ms}ms 초과", provider=provider)
            client = _get_client(provider, key)
            from google.genai import types
        except Exception as exc:
            raise LLMUnavailable(_safe_error(exc, secrets), attempts=0, provider=provider) from exc

        def request_fn(model_name: str, prompt_text: str, system_text: str, timeout_ms: int) -> str:
            options = {"system_instruction": system_text, "temperature": 0,
                       "http_options": types.HttpOptions(timeout=timeout_ms)}
            if response_schema is not None:
                options.update(response_mime_type="application/json", response_schema=response_schema)
            config = types.GenerateContentConfig(**options)
            response = client.models.generate_content(model=model_name, contents=prompt_text, config=config)
            return (response.text or "").strip()

    last_error: Exception | None = None
    attempt = 0
    for next_attempt in range(1, max_attempts + 1):
        remaining_ms = timeout_ms - int((clock_fn() - started) * 1000)
        if remaining_ms <= 0:
            break
        attempt = next_attempt
        try:
            text = request_fn(model, prompt, system, remaining_ms)
        except Exception as exc:
            last_error = exc
            if not _transient(exc) or attempt == max_attempts:
                raise LLMUnavailable(_safe_error(exc, secrets), attempts=attempt, provider=provider) from exc
            delay = retry_delays[attempt - 1]
            elapsed = clock_fn() - started
            if elapsed + delay + 0.1 >= timeout_ms / 1000:
                break
            sleep_fn(delay)
            continue
        if (clock_fn() - started) * 1000 >= timeout_ms:
            raise LLMUnavailable(f"LLM 호출 시간 상한 {timeout_ms}ms 초과", attempts=attempt, provider=provider)
        if not text:
            raise LLMUnavailable("빈 응답", attempts=attempt, provider=provider)
        return LLMResult(text=text, provider=provider, attempts=attempt)

    message = _safe_error(last_error, secrets) if last_error else f"LLM 호출 시간 상한 {timeout_ms}ms 초과"
    raise LLMUnavailable(message, attempts=attempt, provider=provider)
