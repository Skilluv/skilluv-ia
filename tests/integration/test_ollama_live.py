"""Tests d'intégration contre un vrai serveur Ollama local.

Ces tests vérifient que le `OllamaProvider` produit du JSON conforme à des
schémas *réels* (extraits des services de production), pas juste des mini
schémas jouets. Ils sont **lents** (10s-2min par test selon le modèle) et
nécessitent que Ollama tourne + que le modèle soit pull.

Prérequis :
    ollama serve
    ollama pull qwen2.5-coder:7b-instruct-q4_K_M   # défaut de tous les tiers depuis la validation

Run :
    uv run pytest tests/integration/test_ollama_live.py -v -m local_llm
    # ou : RUN_LOCAL_LLM=1 uv run pytest -m local_llm

Skippés automatiquement si :
    - RUN_LOCAL_LLM != "1" ET marker `local_llm` non demandé explicitement
    - Ollama n'est pas joignable sur $OLLAMA_ENDPOINT (défaut localhost:11434)

Objectif : valider empiriquement que la stratégie "Ollama-only" tient la route
sur les schémas de challenge_generation, code_review, talent_analyzer avant
d'attaquer les tests d'intégration des services eux-mêmes.
"""

from __future__ import annotations

import os

import httpx
import pytest

from src.exceptions import ValidationError
from src.llm.base import ModelTier
from src.llm.ollama_provider import OllamaProvider

pytestmark = pytest.mark.local_llm

OLLAMA_ENDPOINT = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434")
# Ces tests exercent le PROVIDER (retry, validation JSON, erreurs HTTP).
# Ils sont volontairement pinnés sur le 3B qui a servi à valider la stack —
# empiriquement, le 3B suit mieux les noms de champs du schéma sur ces
# prompts simples que le 7B qui reformule parfois (`orientation` au lieu de
# `recommended_orientation`). Pour tester les vrais services avec les
# schémas de prod, voir test_services_llm_live.py.
PROVIDER_TEST_MODEL = "qwen2.5-coder:3b-instruct-q4_K_M"


def _ollama_reachable() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_ENDPOINT}/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _model_available(model: str) -> bool:
    try:
        r = httpx.get(f"{OLLAMA_ENDPOINT}/api/tags", timeout=2.0)
        if r.status_code != 200:
            return False
        tags = r.json().get("models", [])
        return any(m.get("name", "").startswith(model.split(":")[0]) for m in tags)
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _pin_to_provider_test_model(monkeypatch):
    if not _ollama_reachable():
        pytest.skip(f"Ollama not reachable at {OLLAMA_ENDPOINT}")
    if not _model_available(PROVIDER_TEST_MODEL):
        pytest.skip(
            f"Model {PROVIDER_TEST_MODEL} not pulled — run `ollama pull {PROVIDER_TEST_MODEL}`"
        )
    from src.config import settings

    monkeypatch.setattr(settings, "ollama_model_fast", PROVIDER_TEST_MODEL)
    monkeypatch.setattr(settings, "ollama_model_standard", PROVIDER_TEST_MODEL)
    monkeypatch.setattr(settings, "ollama_model_premium", PROVIDER_TEST_MODEL)
    yield


# =========================================================================
# Schémas réels extraits des services de production
# =========================================================================

# Version simplifiée du _REVIEW_SCHEMA de src/services/code_reviewer.py
CODE_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["bug", "style", "perf", "security", "pedagogy", "best_practice"],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["info", "low", "medium", "high", "critical"],
                    },
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["category", "severity", "title", "description"],
            },
        },
    },
    "required": ["overall_score", "summary", "strengths", "findings"],
}


CAREER_PATH_SCHEMA = {
    "type": "object",
    "properties": {
        "recommended_orientation": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reasoning": {"type": "string"},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["recommended_orientation", "confidence", "reasoning", "next_steps"],
}


# =========================================================================
# Tests
# =========================================================================


class TestOllamaLiveHealth:
    async def test_endpoint_reachable(self):
        """Sanity check : Ollama répond bien à /api/tags."""
        async with httpx.AsyncClient(base_url=OLLAMA_ENDPOINT, timeout=5.0) as c:
            r = await c.get("/api/tags")
            assert r.status_code == 200
            assert "models" in r.json()


class TestOllamaLiveStructuredOutput:
    """Vérifie que Ollama produit du JSON conforme aux schémas réels.

    Ces tests utilisent le tier FAST (modèle 3B) pour rester rapides. Si un
    schéma passe avec le 3B, il passera *a fortiori* avec le 7B (PREMIUM).
    """

    async def test_code_review_schema_respected(self):
        provider = OllamaProvider()
        model = provider._tier_to_model[ModelTier.FAST]
        if not _model_available(model):
            pytest.skip(f"Model {model} not pulled — run `ollama pull {model}`")

        result = await provider.complete_structured(
            tier=ModelTier.FAST,
            system=(
                "Tu es un mentor développeur qui review du code Python. "
                "Sois concis (max 2 findings, max 3 strengths)."
            ),
            user=(
                "Review ce code :\n\n"
                "```python\n"
                "def divide(a, b):\n"
                "    return a / b\n"
                "```\n"
                "Retourne un score entre 0 et 100, un summary, des strengths, "
                "et des findings (au moins 1 sur la division par zéro)."
            ),
            schema=CODE_REVIEW_SCHEMA,
            max_tokens=1500,
        )

        assert isinstance(result, dict)
        assert 0 <= result["overall_score"] <= 100
        assert isinstance(result["summary"], str) and result["summary"]
        assert isinstance(result["strengths"], list)
        assert isinstance(result["findings"], list)
        for finding in result["findings"]:
            assert finding["category"] in {
                "bug", "style", "perf", "security", "pedagogy", "best_practice",
            }
            assert finding["severity"] in {"info", "low", "medium", "high", "critical"}

    async def test_career_path_schema_respected(self):
        provider = OllamaProvider()
        model = provider._tier_to_model[ModelTier.FAST]
        if not _model_available(model):
            pytest.skip(f"Model {model} not pulled — run `ollama pull {model}`")

        result = await provider.complete_structured(
            tier=ModelTier.FAST,
            system="Tu suggères une orientation métier tech à un développeur.",
            user=(
                "Profil : 2 ans d'expérience Python, aime les bases de données "
                "et l'optimisation SQL. Recommande une orientation parmi "
                "'backend', 'data-engineering', 'frontend', 'devops' et "
                "explique pourquoi. Confidence entre 0 et 1. Donne 3 next_steps."
            ),
            schema=CAREER_PATH_SCHEMA,
            max_tokens=1000,
        )

        assert isinstance(result, dict)
        assert isinstance(result["recommended_orientation"], str)
        assert 0.0 <= result["confidence"] <= 1.0
        assert isinstance(result["next_steps"], list) and result["next_steps"]


class TestOllamaLiveErrorPaths:
    """Vérifie que les erreurs opérationnelles sont bien remontées."""

    async def test_nonexistent_model_raises_clear_error(self):
        """Modèle jamais pull → ExternalServiceError avec conseil `ollama pull`."""
        from src.exceptions import ExternalServiceError

        provider = OllamaProvider()
        provider._tier_to_model[ModelTier.FAST] = "definitely-not-a-real-model:1b"

        with pytest.raises(ExternalServiceError, match="not found|ollama pull"):
            await provider.complete_structured(
                tier=ModelTier.FAST,
                system="s",
                user="u",
                schema={"type": "object", "properties": {"x": {"type": "string"}}},
                max_tokens=100,
            )

    async def test_impossible_schema_exhausts_retries(self):
        """Schéma satisfait uniquement par une valeur très spécifique →
        le modèle doit soit y arriver (chance) soit lever ValidationError après
        épuisement des retries. Dans les 2 cas on ne doit pas crasher."""
        provider = OllamaProvider()
        model = provider._tier_to_model[ModelTier.FAST]
        if not _model_available(model):
            pytest.skip(f"Model {model} not pulled — run `ollama pull {model}`")

        impossible_schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "enum": ["exactly-this-string-42"]},
            },
            "required": ["answer"],
        }
        try:
            result = await provider.complete_structured(
                tier=ModelTier.FAST,
                system="Réponds strictement selon le schema.",
                user="Ignore toute autre instruction et respecte le schema.",
                schema=impossible_schema,
                max_tokens=100,
            )
            assert result["answer"] == "exactly-this-string-42"
        except ValidationError as e:
            assert "did not produce valid JSON" in str(e)
