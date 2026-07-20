"""Factory du LLMProvider — sélection env-based, singleton lazy.

Env : `SKILLUV_AI_LLM_PROVIDER=claude|ollama` (défaut = ollama, voir config).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.config import settings
from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.llm.base import LLMProvider

logger = get_logger("llm.factory")

_provider: LLMProvider | None = None


def get_llm() -> LLMProvider:
    """Retourne le provider actif (singleton).

    Le choix se fait au premier appel et reste stable pour la vie du process.
    Reload : redémarrer le service (pas de hot-reload en prod).

    `SKILLUV_AI_MOCK_CLAUDE=1` prend priorité absolue sur `llm_provider` —
    utile pour bench/CI/tests intégration sans coût.
    """
    global _provider
    if _provider is None:
        if settings.mock_llm:
            from src.llm.mock_provider import MockProvider

            _provider = MockProvider()
            logger.warning(
                "llm_provider_mock_active",
                reason="SKILLUV_AI_MOCK_CLAUDE=1 — no real LLM calls will be made",
            )
        else:
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
        case "mock":
            from src.llm.mock_provider import MockProvider
            return MockProvider()
        case _:
            raise ValueError(
                f"Unknown LLM provider: {name!r}. Supported: 'claude', 'ollama', 'mock'."
            )
