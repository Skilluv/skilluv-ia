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
        # On force max_retries=1 (2 tentatives) pour un test rapide et
        # indépendant de la valeur par défaut de settings.ollama_max_retries.
        p._max_retries = 1
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

    @pytest.mark.asyncio
    async def test_read_timeout_wrapped_as_external_service_error(self):
        """Cas concret en prod : LLM local sur CPU dépasse `_REQUEST_TIMEOUT_S`.
        On veut remonter comme ExternalServiceError, pas une exception nue
        qui remonterait jusqu'au worker et casserait le job envelope."""
        from src.exceptions import ExternalServiceError

        p = OllamaProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.ReadTimeout("timeout after 300s"),
        )
        with (
            patch.object(p, "_get_client", return_value=mock_client),
            pytest.raises(ExternalServiceError, match="Ollama HTTP error"),
        ):
            await p._call_ollama_chat(
                model="test", system="s", user="u", max_tokens=100,
            )

    @pytest.mark.asyncio
    async def test_500_response_wrapped_as_external_service_error(self):
        """Ollama qui répond 500 (crash serveur, GPU OOM, etc.) → erreur claire
        avec le status code en `details`."""
        from src.exceptions import ExternalServiceError

        p = OllamaProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                500,
                text="internal server error",
                request=httpx.Request("POST", "http://ollama/api/chat"),
            )
        )
        with (
            patch.object(p, "_get_client", return_value=mock_client),
            pytest.raises(ExternalServiceError, match="Ollama HTTP error"),
        ):
            await p._call_ollama_chat(
                model="test", system="s", user="u", max_tokens=100,
            )

    @pytest.mark.asyncio
    async def test_404_model_not_pulled_raises_actionable_error(self):
        """Modèle non pull (`ollama pull` oublié) → 404 côté Ollama.
        Message d'erreur doit inclure la commande de fix.
        Régression garante du fix appliqué session 2026-07-22."""
        from src.exceptions import ExternalServiceError

        p = OllamaProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                404,
                text="model 'foo:latest' not found",
                request=httpx.Request("POST", "http://ollama/api/chat"),
            )
        )
        with (
            patch.object(p, "_get_client", return_value=mock_client),
            pytest.raises(ExternalServiceError, match=r"not found.*ollama pull"),
        ):
            await p._call_ollama_chat(
                model="foo:latest", system="s", user="u", max_tokens=100,
            )

    @pytest.mark.asyncio
    async def test_empty_content_raises_actionable_error(self):
        """Ollama répond 200 mais avec content vide (OOM, modèle non chargé).
        Sans le fix, on tombait sur JSONDecodeError → retry inutile → erreur
        opaque après épuisement. On veut une erreur explicite dès le 1er coup.
        Régression garante du fix appliqué session 2026-07-22."""
        from src.exceptions import ExternalServiceError

        p = OllamaProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": ""}},
                request=httpx.Request("POST", "http://ollama/api/chat"),
            )
        )
        with (
            patch.object(p, "_get_client", return_value=mock_client),
            pytest.raises(ExternalServiceError, match="empty content"),
        ):
            await p._call_ollama_chat(
                model="test", system="s", user="u", max_tokens=100,
            )

    @pytest.mark.asyncio
    async def test_whitespace_only_content_also_treated_as_empty(self):
        """Content = '   \\n\\n  ' doit aussi être traité comme vide.
        Sans strip(), un modèle qui bafouille juste du whitespace passerait
        et cascaderait en JSONDecodeError sur `json.loads('   ')`."""
        from src.exceptions import ExternalServiceError

        p = OllamaProvider()
        mock_client = MagicMock()
        mock_client.post = AsyncMock(
            return_value=httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "   \n\n  "}},
                request=httpx.Request("POST", "http://ollama/api/chat"),
            )
        )
        with (
            patch.object(p, "_get_client", return_value=mock_client),
            pytest.raises(ExternalServiceError, match="empty content"),
        ):
            await p._call_ollama_chat(
                model="test", system="s", user="u", max_tokens=100,
            )

    @pytest.mark.asyncio
    async def test_external_errors_metric_incremented_on_failure(self):
        """Chaque échec réseau/protocole doit incrémenter le counter
        `external_errors_total{service='ollama'}` pour l'alerting Prometheus."""
        from src.utils.metrics import external_errors_total

        p = OllamaProvider()
        before = external_errors_total.labels(service="ollama")._value.get()

        mock_client = MagicMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))
        with patch.object(p, "_get_client", return_value=mock_client):
            try:
                await p._call_ollama_chat(
                    model="test", system="s", user="u", max_tokens=100,
                )
            except Exception:
                pass

        after = external_errors_total.labels(service="ollama")._value.get()
        assert after == before + 1
