"""Gemini 호출 클라이언트. 숫자는 여기서 만들지 않는다 — compose가 검증한다."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
TIMEOUT_MS = 20_000


class LLMUnavailable(Exception):
    """LLM을 쓸 수 없거나 호출이 실패했다. 호출부는 기본 문장으로 대신한다."""


def _api_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "GEMINI_API_KEY":
                key = value.strip().strip('"').strip("'")
    return key


def model_name() -> str:
    """LLM_MODEL 환경변수, 없으면 config.json의 모델 이름."""
    env_model = os.environ.get("LLM_MODEL")
    if env_model:
        return env_model
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))["model"]
    raise LLMUnavailable("모델 설정이 없습니다: LLM_MODEL 또는 agent/tools/llm/config.json")


def generate(prompt: str, system: str) -> str:
    """Gemini로 문장을 만든다. AGENT_LLM=on이 아니면 호출 없이 바로 실패한다."""
    if os.environ.get("AGENT_LLM", "off") != "on":
        raise LLMUnavailable("AGENT_LLM=off")
    key = _api_key()
    if not key:
        raise LLMUnavailable("GEMINI_API_KEY가 없습니다")
    model = model_name()
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=model, contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system, temperature=0,
                http_options=types.HttpOptions(timeout=TIMEOUT_MS),
            ),
        )
    except Exception as exc:  # 키·한도·시간 초과 등 무엇이 와도 서비스는 멈추지 않는다
        raise LLMUnavailable(f"{type(exc).__name__}: {str(exc)[:200]}") from exc
    text = (response.text or "").strip()
    if not text:
        raise LLMUnavailable("빈 응답")
    return text
