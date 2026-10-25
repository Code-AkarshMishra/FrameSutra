"""Groq LLM client configuration with migration from retired model IDs."""
import os
import time
import logging

from langchain_groq import ChatGroq
from core.config import load_project_env
from core.observability import increment

load_project_env()

PROVIDER_NAME = "Groq"
API_KEY_ENV = "GROQ_API_KEY"
MODEL_ENV = "GROQ_MODEL"
DEFAULT_MODEL = "openai/gpt-oss-20b"

# Groq retired llama-3.1-8b-instant for non-enterprise use on 2026-08-16.
# Map the legacy .env value automatically so existing local setups keep working.
LEGACY_MODEL_MAP = {
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
}


def configured_model() -> str:
    configured = os.getenv(MODEL_ENV, "").strip()
    if not configured:
        return DEFAULT_MODEL
    return LEGACY_MODEL_MAP.get(configured.lower(), configured)


def get_llm(temperature: float = 0.2):
    key = os.getenv(API_KEY_ENV, "").strip()
    if not key:
        raise RuntimeError(f"{API_KEY_ENV} is not set. Add it to your .env file.")
    model = configured_model()
    return ChatGroq(
        model=model,
        api_key=key,
        temperature=temperature,
    )


def is_auth_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "401" in msg or "invalid api key" in msg or "unauthorized" in msg


def is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "rate_limited" in msg


def invoke_with_retry(chain, payload, retries: int = 2, base_delay: int = 4, label: str = "llm"):
    for attempt in range(retries + 1):
        try:
            result = chain.invoke(payload)
            increment("llm_success")
            return result
        except Exception as exc:
            increment("llm_errors")
            if is_auth_error(exc):
                raise RuntimeError(
                    f"{PROVIDER_NAME} API key is invalid or expired. "
                    f"Please update {API_KEY_ENV} in your .env file."
                ) from exc
            if is_rate_limit_error(exc):
                increment("llm_rate_limits")
            if not is_rate_limit_error(exc) or attempt == retries:
                raise
            wait = base_delay * (2 ** attempt)
            logging.getLogger("framesutra.provider").warning("provider_rate_limited provider=%s label=%s retry=%d wait_seconds=%d", PROVIDER_NAME, label, attempt + 1, wait)
            time.sleep(wait)
