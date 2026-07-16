"""Factory du LLMProvider — sélection env-based, singleton lazy.

Env : `SKILLUV_AI_LLM_PROVIDER=claude|ollama` (défaut = ollama, voir config).
"""

from __future__ import annotations

from src.config import settings
from src.llm.base import LLMProvider
from src.utils.logging import get_logger

logger = get_logger("llm.factory")

_provider: LLMProvider | None = None


def get_llm() -> LLMProvider:
    """Retourne le provider actif (singleton).

    Le choix se fait au premier appel et reste stable pour la vie du process.
    Reload : redémarrer le service (pas de hot-reload en prod).
    """
    global _provider
    if _provider is None:
        _provider = _create_provider(settings.llm_provider)
        logger.info(
            "llm_provider_selected",
            provider=_provider.name,
            source_env=settings.llm_provider,
        )
    return _provider


def reset_provider_for_tests() -> None:
    """Force la ré-création du singleton — usage tests uniquement."""
    global _provider
    _provider = None


def _create_provider(name: str) -> LLMProvider:
    match name.lower():
        case "claude" | "anthropic":
            from src.llm.claude_provider import ClaudeProvider
            return ClaudeProvider()
        case "ollama" | "local":
            from src.llm.ollama_provider import OllamaProvider
            return OllamaProvider()
        case _:
            raise ValueError(
                f"Unknown LLM provider: {name!r}. Supported: 'claude', 'ollama'."
            )
