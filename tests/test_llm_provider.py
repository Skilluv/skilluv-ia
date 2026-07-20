"""Tests unitaires de l'abstraction LLM (base, factory, ClaudeProvider, OllamaProvider).

Aucun appel réseau réel : Anthropic + Ollama sont mockés au niveau HTTP/SDK.
Un test intégration Ollama existe séparément avec le marker @local_llm.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.exceptions import ValidationError
from src.llm import ModelTier
from src.llm.claude_provider import ClaudeProvider
from src.llm.factory import get_llm, reset_provider_for_tests
from src.llm.ollama_provider import OllamaProvider

# =========================================================================
# ModelTier
# =========================================================================


class TestModelTier:
    def test_three_tiers_defined(self):
        assert ModelTier.PREMIUM.value == "premium"
        assert ModelTier.STANDARD.value == "standard"
        assert ModelTier.FAST.value == "fast"


# =========================================================================
# Factory
# =========================================================================


class TestFactory:
    def teardown_method(self):
        reset_provider_for_tests()

    def test_default_from_settings(self):
        with patch("src.llm.factory.settings") as s:
            s.llm_provider = "ollama"
            s.mock_llm = False
            provider = get_llm()
        assert provider.name == "ollama"

    def test_claude_selection(self):
        with patch("src.llm.factory.settings") as s:
            s.llm_provider = "claude"
            s.mock_llm = False
            provider = get_llm()
        assert provider.name == "claude"

    def test_singleton_stable(self):
        with patch("src.llm.factory.settings") as s:
            s.llm_provider = "ollama"
            s.mock_llm = False
            p1 = get_llm()
            p2 = get_llm()
        assert p1 is p2

    def test_unknown_raises(self):
        with patch("src.llm.factory.settings") as s:
            s.llm_provider = "nonsense"
            s.mock_llm = False
            with pytest.raises(ValueError, match="Unknown LLM provider"):
                get_llm()

    def test_mock_flag_overrides_provider_selection(self):
        """SKILLUV_AI_MOCK_CLAUDE=1 court-circuite le provider configuré."""
        with patch("src.llm.factory.settings") as s:
            s.llm_provider = "claude"
            s.mock_llm = True
            provider = get_llm()
        assert provider.name == "mock"


# =========================================================================
# ClaudeProvider — mapping tier -> model
# =========================================================================


class TestClaudeProviderTierMapping:
    def test_premium_is_opus(self):
        assert ClaudeProvider().model_for_tier(ModelTier.PREMIUM) == "claude-opus-4-7"

    def test_standard_is_sonnet(self):
        assert ClaudeProvider().model_for_tier(ModelTier.STANDARD) == "claude-sonnet-4-6"

    def test_fast_is_haiku(self):
        assert ClaudeProvider().model_for_tier(ModelTier.FAST).startswith("claude-haiku")


# =========================================================================
# OllamaProvider — validation, retry, schema hint
# =========================================================================


def _mock_ollama_response(content: str) -> httpx.Response:
    """Construit une Response httpx factice émulant /api/chat."""
    return httpx.Response(
        200,
        json={"message": {"role": "assistant", "content": content}},
        request=httpx.Request("POST", "http://ollama/api/chat"),
    )


SAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
    },
    "required": ["name", "score"],
    "additionalProperties": False,
}


class TestOllamaProviderTierMapping:
    def test_model_version_prefixed_ollama(self):
        p = OllamaProvider()
        version = p.model_for_tier(ModelTier.PREMIUM)
        assert version.startswith("ollama:")


class TestOllamaProviderStructured:
    @pytest.mark.asyncio
    async def test_valid_json_returned_directly(self):
        p = OllamaProvider()
        content = json.dumps({"name": "Alice", "score": 82})
        with patch.object(
            p, "_call_ollama_chat", new=AsyncMock(return_value=content),
        ):
            result = await p.complete_structured(
                tier=ModelTier.FAST,
                system="sys",
                user="usr",
                schema=SAMPLE_SCHEMA,
            )
        assert result == {"name": "Alice", "score": 82}

    @pytest.mark.asyncio
    async def test_invalid_json_retried_then_recovers(self):
        p = OllamaProvider()
        good = json.dumps({"name": "Bob", "score": 55})
        with patch.object(
            p,
            "_call_ollama_chat",
            new=AsyncMock(side_effect=["not json at all", good]),
        ):
            result = await p.complete_structured(
                tier=ModelTier.FAST, system="sys", user="usr", schema=SAMPLE_SCHEMA,
            )
        assert result["name"] == "Bob"

    @pytest.mark.asyncio
    async def test_schema_violation_retried_then_recovers(self):
        p = OllamaProvider()
        bad = json.dumps({"name": "Charlie"})  # manque 'score'
        good = json.dumps({"name": "Charlie", "score": 40})
        with patch.object(
            p,
            "_call_ollama_chat",
            new=AsyncMock(side_effect=[bad, good]),
        ):
            result = await p.complete_structured(
                tier=ModelTier.FAST, system="sys", user="usr", schema=SAMPLE_SCHEMA,
            )
        assert result["score"] == 40

    @pytest.mark.asyncio
    async def test_persistent_invalid_raises_validation_error(self):
        p = OllamaProvider()
        with patch.object(
            p,
            "_call_ollama_chat",
            new=AsyncMock(side_effect=["broken 1", "broken 2"]),
        ), pytest.raises(ValidationError, match="did not produce valid JSON"):
            await p.complete_structured(
                tier=ModelTier.FAST,
                system="sys",
                user="usr",
                schema=SAMPLE_SCHEMA,
            )

    @pytest.mark.asyncio
    async def test_prompt_correction_injected_on_retry(self):
        """Vérifie que le prompt de retry mentionne l'erreur — permet au modèle
        de corriger sa sortie plutôt que de re-halluciner à l'aveugle."""
        p = OllamaProvider()
        calls: list[tuple[str, str]] = []

        async def spy(*, model, system, user, max_tokens):
            calls.append((system, user))
            if len(calls) == 1:
                return "invalid"
            return json.dumps({"name": "X", "score": 1})

        with patch.object(p, "_call_ollama_chat", new=spy):
            await p.complete_structured(
                tier=ModelTier.FAST, system="sys", user="usr", schema=SAMPLE_SCHEMA,
            )
        assert len(calls) == 2
        _, retry_user = calls[1]
        assert "Correction" in retry_user or "invalide" in retry_user.lower()


class TestOllamaProviderHTTP:
    @pytest.mark.asyncio
    async def test_http_error_wrapped_as_external_service_error(self):
        from src.exceptions import ExternalServiceError

        p = OllamaProvider()
        # httpx.AsyncClient mocké pour lever une erreur réseau
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused"),
        )
        with (
            patch.object(p, "_get_client", return_value=mock_client),
            pytest.raises(ExternalServiceError, match="Ollama HTTP error"),
        ):
            await p._call_ollama_chat(
                model="test", system="s", user="u", max_tokens=100,
            )
