import logging

from app.config import get_settings
from app.core.errors import AppError
from app.services.llm.base import ChatMessage, LLMProvider, LLMResponse, ToolCall, ToolSpec, parse_json_object
from app.services.llm.gemini import GeminiProvider
from app.services.llm.groq import GroqProvider

__all__ = [
    "ChatMessage", "ToolSpec", "ToolCall", "LLMResponse", "LLMProvider", "GeminiProvider", "GroqProvider",
    "get_provider", "set_provider_override", "parse_json_object",
]

logger = logging.getLogger("app.llm")
_PROVIDERS: dict[str, type[GeminiProvider] | type[GroqProvider]] = {"gemini": GeminiProvider, "groq": GroqProvider}
_override: LLMProvider | None = None


def set_provider_override(provider: LLMProvider | None) -> None:
    """Tests: force get_provider() to return a FakeProvider (pass None to restore)."""
    global _override
    _override = provider


def get_provider() -> LLMProvider:
    """Build the provider selected by LLM_PROVIDER / LLM_MODEL / LLM_API_KEY / LLM_TIMEOUT_SECONDS."""
    if _override is not None:
        return _override
    s = get_settings()
    cls = _PROVIDERS.get(s.LLM_PROVIDER.strip().lower())
    if cls is None or not s.LLM_API_KEY or not s.LLM_MODEL:
        logger.error(
            "llm_not_configured",
            extra={"provider": s.LLM_PROVIDER, "has_key": bool(s.LLM_API_KEY), "has_model": bool(s.LLM_MODEL)},
        )
        raise AppError("llm_not_configured", "The AI service is not configured.", 503)
    return cls(api_key=s.LLM_API_KEY, model=s.LLM_MODEL, timeout=float(s.LLM_TIMEOUT_SECONDS))
