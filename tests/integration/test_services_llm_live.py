"""Tests d'intégration end-to-end des services LLM contre Ollama local.

Différence avec `test_ollama_live.py` : ici on ne teste PAS le provider seul
avec un mini prompt, on exerce le *vrai chemin* d'un service de production —
prompt system/user réel construit par le service, appel LLM, parsing du JSON,
construction du Pydantic model final.

Ce qu'on valide :
    - Les prompts réels (parfois >1000 tokens) sont bien digérés par Qwen 3B.
    - Le JSON retourné respecte le schéma *et* passe la validation Pydantic
      (contrainte plus stricte que le seul jsonschema : enum Literal, bornes,
      types précis).
    - Aucune régression subtile entre le contrat Claude et le contrat Ollama
      (ex: un champ optionnel non fourni par Ollama qui casserait Pydantic).

Prérequis :
    ollama serve
    ollama pull qwen2.5-coder:7b-instruct-q4_K_M

Note : les 3 tiers pointent sur le 7B en config par défaut (voir src/config.py).
Le 3B avait été essayé pour FAST mais collapse sur les schémas nested type
`OrientationSuggestion` (perte de la structure racine en retry).

Run :
    uv run pytest tests/integration/test_services_llm_live.py -v -m local_llm

Flakiness :
    Certains tests sont marqués `@pytest.mark.flaky` (via pytest-rerunfailures)
    car les LLM locaux out-of-the-box ne sont pas 100% déterministes sur les
    schémas complexes. Politique retenue : jusqu'à 3 essais (2 reruns).
    À supprimer une fois le modèle fine-tuné sur les données Skilluv.
"""

from __future__ import annotations

import os

import httpx
import pytest

from src.llm.base import ModelTier
from src.llm.factory import reset_provider_for_tests

pytestmark = pytest.mark.local_llm

OLLAMA_ENDPOINT = os.environ.get("OLLAMA_ENDPOINT", "http://localhost:11434")
# Modèles requis (= défauts de src/config.py). Depuis la validation empirique,
# les 3 tiers pointent sur le 7B (le 3B collapse sur les schémas nested).
REQUIRED_MODELS = (
    "qwen2.5-coder:7b-instruct-q4_K_M",  # tous les tiers
)


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
        prefix = model.split(":")[0]
        return any(m.get("name", "").startswith(prefix) for m in tags)
    except Exception:
        return False


@pytest.fixture(autouse=True)
def _use_real_ollama(monkeypatch):
    """Utilise le provider Ollama avec la config production (Qwen 7B + 3B).

    Skip si Ollama n'est pas up ou si un des modèles requis n'est pas pull.
    Reset le singleton du factory pour être sûr que la config prend effet
    (sans ça, un test précédent qui aurait initialisé un mock ou claude
    laisserait le singleton en cache).
    """
    if not _ollama_reachable():
        pytest.skip(f"Ollama not reachable at {OLLAMA_ENDPOINT}")
    for m in REQUIRED_MODELS:
        if not _model_available(m):
            pytest.skip(f"Model {m} not pulled — run `ollama pull {m}`")

    from src.config import settings

    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr(settings, "mock_llm", False)
    reset_provider_for_tests()
    yield
    reset_provider_for_tests()


# =========================================================================
# Challenge Generator — service complet
# =========================================================================


class TestChallengeGeneratorLive:
    async def test_generate_simple_challenge_end_to_end(self):
        """Le prompt réel du service produit un challenge valide côté Pydantic."""
        from src.models.challenge import ChallengeParams
        from src.services.challenge_generator import generate_challenge

        params = ChallengeParams(
            skill_domain="code",
            difficulty=2,
            duration_minutes=30,
            # tone=absurd → jamais mis en cache (voir _challenge_cache._is_cacheable),
            # garantit que le LLM est réellement appelé même sans Redis mocké.
            tone="absurd",
            language="fr",
            programming_language="python",
            tags=["fonctions", "boucles"],
        )
        challenge = await generate_challenge(params)

        # Le service a construit un GeneratedChallenge validé par Pydantic —
        # si on arrive ici, tous les champs required sont présents et typés.
        assert challenge.title
        assert challenge.description
        assert challenge.instructions
        assert challenge.difficulty == 2
        assert challenge.duration_minutes == 30
        assert challenge.language == "fr"
        assert challenge.fragment_reward > 0
        # Le LLM doit produire au moins 1 test case (schema le requiert).
        assert len(challenge.test_cases) >= 1
        for tc in challenge.test_cases:
            assert tc.input is not None
            assert tc.expected_output is not None
            assert tc.description


# =========================================================================
# Code Reviewer — service complet
# =========================================================================


class TestCodeReviewerLive:
    async def test_review_python_code_end_to_end(self):
        """Un code Python simple doit produire un review Pydantic-valide."""
        from src.models.code_review import CodeReviewPayload
        from src.services.code_reviewer import review_code

        payload = CodeReviewPayload(
            submission_id="test-sub-001",
            challenge_id="test-chal-001",
            user_id="test-user-001",
            language="python",
            source_code=(
                "def divide(a, b):\n"
                "    return a / b\n"
                "\n"
                "print(divide(10, 0))\n"
            ),
            challenge_title="Division sécurisée",
            challenge_description="Écris une fonction qui divise deux nombres.",
            difficulty=1,
            user_level="beginner",
        )
        result = await review_code(payload)

        assert result.submission_id == "test-sub-001"
        assert 0 <= result.overall_score <= 100
        assert result.summary
        assert isinstance(result.strengths, list)
        assert isinstance(result.findings, list)
        # Tous les findings passent la validation Pydantic (enum category/severity).
        for f in result.findings:
            assert f.category in {
                "bug", "style", "perf", "security", "pedagogy", "best_practice",
            }
            assert f.severity in {"info", "low", "medium", "high", "critical"}
            assert f.title
            assert f.description

    async def test_empty_submission_short_circuits_without_llm(self):
        """Soumission vide → le service court-circuite (pas d'appel LLM).

        Ce test valide qu'on n'appelle PAS Qwen pour rien — utile pour éviter
        des latences absurdes sur cas trivial."""
        from src.models.code_review import CodeReviewPayload
        from src.services.code_reviewer import review_code

        payload = CodeReviewPayload(
            submission_id="test-empty",
            challenge_id="test-chal-empty",
            user_id="test-user-empty",
            language="python",
            source_code="   \n\n  ",
        )
        result = await review_code(payload)

        assert result.overall_score == 0
        summary_lower = result.summary.lower()
        assert "vide" in summary_lower or "soumis" in summary_lower
        assert len(result.findings) == 1
        assert result.findings[0].severity == "critical"


# =========================================================================
# Talent Analyzer — suggest_career_path (FAST tier, plus léger)
# =========================================================================


class TestTalentAnalyzerLive:
    # Marker flaky : ce test est probabiliste sur Qwen 7B. On observe ~50-70%
    # de succès en 1 essai out-of-the-box (langue mélangée dans les enums,
    # extra fields hallucinés, structure racine parfois perdue en retry).
    # Le budget max reste raisonnable : 3 essais * ~5 min ≈ 15 min pire cas.
    # À ré-évaluer une fois le modèle fine-tuné sur les données Skilluv.
    @pytest.mark.flaky(reruns=2, reruns_delay=5)
    async def test_suggest_career_path_end_to_end(self):
        """SuggestCareerPath produit un CareerPathResult Pydantic-valide."""
        from src.models.talent_analysis import CareerPathPayload, SkillSnapshot
        from src.services.talent_analyzer import suggest_career_path

        payload = CareerPathPayload(
            user_id="test-user-career",
            skills=[
                SkillSnapshot(skill_slug="python", wpc_total=120, evidence_count=8),
                SkillSnapshot(skill_slug="postgresql", wpc_total=80, evidence_count=5),
                SkillSnapshot(skill_slug="sql-optimization", wpc_total=60, evidence_count=4),
            ],
            working_languages=["fr", "en"],
            target_market="international",
            max_suggestions=3,
        )
        result = await suggest_career_path(payload)

        # Validation Pydantic implicite — si on arrive ici tous les enum
        # (transition_effort, confidence borné) ont été respectés par Qwen.
        assert isinstance(result.suggestions, list)
        assert 1 <= len(result.suggestions) <= 3
        for s in result.suggestions:
            assert s.orientation_slug
            assert 0.0 <= s.confidence <= 1.0
            assert s.transition_effort in {"low", "medium", "high"}
            assert s.timeline_estimate_months >= 0
