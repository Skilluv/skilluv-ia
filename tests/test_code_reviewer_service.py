"""Tests unitaires isolés du service `review_code` — trou #3 de la carto.

Jusqu'ici, `code_reviewer` n'était testé QUE via le gRPC servicer (mapping
score/summary/findings). Le service lui-même n'avait aucun test unitaire :
- calcul du `fragments_bonus` selon les paliers de score
- court-circuit sur soumission vide (pas d'appel LLM)
- construction du prompt selon `user_level` (beginner / intermediate / advanced)
- troncature des inputs volumineux (test_output → 2000 chars, source_code → 15000)
- résilience aux champs manquants dans la réponse LLM
- propagation correcte de l'ID de soumission et de challenge

LLM mocké au niveau `get_llm()` — pas d'appel réseau, tests déterministes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.code_review import CodeReviewFinding, CodeReviewPayload
from src.services.code_reviewer import _build_system_prompt, _build_user_prompt, review_code


# =========================================================================
# Helpers
# =========================================================================


def _payload(**overrides) -> CodeReviewPayload:
    """Fabrique un CodeReviewPayload valide avec overrides ponctuels."""
    defaults = dict(
        submission_id="sub-1",
        challenge_id="chal-1",
        user_id="user-1",
        language="python",
        source_code="def foo(): return 42\n",
        challenge_title="Titre",
        challenge_description="Description",
        difficulty=2,
        user_level="intermediate",
    )
    defaults.update(overrides)
    return CodeReviewPayload(**defaults)


def _llm_response(score: int, **overrides) -> dict:
    """Structure minimale attendue par review_code (matche _REVIEW_SCHEMA)."""
    data = {
        "overall_score": score,
        "summary": "Résumé du review.",
        "strengths": ["clarté"],
        "findings": [],
        "learning_resources": [],
    }
    data.update(overrides)
    return data


def _mock_llm_returning(response: dict):
    """Retourne un context manager qui patche `get_llm()` avec un mock async
    dont `complete_structured` renvoie `response`."""
    llm = MagicMock()
    llm.complete_structured = AsyncMock(return_value=response)
    return patch("src.services.code_reviewer.get_llm", return_value=llm), llm


# =========================================================================
# Court-circuit soumission vide (aucun appel LLM)
# =========================================================================


class TestEmptySubmissionShortCircuit:
    async def test_empty_source_returns_score_0_without_llm_call(self):
        llm = MagicMock()
        llm.complete_structured = AsyncMock()
        with patch("src.services.code_reviewer.get_llm", return_value=llm):
            result = await review_code(_payload(source_code=""))
        assert result.overall_score == 0
        assert result.submission_id == "sub-1"
        assert result.challenge_id == "chal-1"
        assert len(result.findings) == 1
        assert result.findings[0].severity == "critical"
        assert result.findings[0].category == "bug"
        # Confirme qu'aucun appel LLM n'a été fait.
        llm.complete_structured.assert_not_called()

    async def test_whitespace_only_source_treated_as_empty(self):
        """Le service utilise `source_code.strip()` — un code = '   \\n\\t'
        doit être équivalent à vide, pas envoyé au LLM (perte de tokens)."""
        llm = MagicMock()
        llm.complete_structured = AsyncMock()
        with patch("src.services.code_reviewer.get_llm", return_value=llm):
            result = await review_code(_payload(source_code="   \n\t  "))
        assert result.overall_score == 0
        llm.complete_structured.assert_not_called()


# =========================================================================
# Calcul du fragments_bonus selon les paliers de score
# =========================================================================


class TestFragmentsBonusCalculation:
    """Paliers documentés dans le service :
       score >= 90 → 5, >= 75 → 3, >= 60 → 1, sinon 0.
    """

    @pytest.mark.parametrize(
        "score,expected_bonus",
        [
            (100, 5),
            (95, 5),
            (90, 5),
            (89, 3),
            (80, 3),
            (75, 3),
            (74, 1),
            (65, 1),
            (60, 1),
            (59, 0),
            (30, 0),
            (0, 0),
        ],
    )
    async def test_bonus_matches_score_tier(self, score, expected_bonus):
        cm, _ = _mock_llm_returning(_llm_response(score))
        with cm:
            result = await review_code(_payload())
        assert result.fragments_bonus == expected_bonus, (
            f"score={score} → attendu bonus={expected_bonus}, "
            f"obtenu {result.fragments_bonus}"
        )
        assert result.overall_score == score


# =========================================================================
# Prompt system selon user_level
# =========================================================================


class TestSystemPromptToneByUserLevel:
    def test_beginner_gets_pedagogical_tone(self):
        prompt = _build_system_prompt(_payload(user_level="beginner"))
        assert "pédagogique" in prompt.lower() or "encourageant" in prompt.lower()

    def test_intermediate_gets_mentor_tone(self):
        prompt = _build_system_prompt(_payload(user_level="intermediate"))
        assert "mentor" in prompt.lower()

    def test_advanced_gets_peer_reviewer_tone(self):
        prompt = _build_system_prompt(_payload(user_level="advanced"))
        assert "peer" in prompt.lower() or "senior" in prompt.lower()

    def test_unknown_user_level_falls_back_to_intermediate(self):
        """Défense en profondeur : si le backend envoie un level bizarre,
        on ne doit pas lever KeyError — le service tombe sur 'intermediate'."""
        prompt = _build_system_prompt(_payload(user_level="galaxy_brain"))
        assert "mentor" in prompt.lower()


# =========================================================================
# User prompt — inclusion des sections et troncatures
# =========================================================================


class TestUserPromptBuilding:
    def test_challenge_description_included_when_present(self):
        prompt = _build_user_prompt(_payload(challenge_description="Résous X"))
        assert "Résous X" in prompt

    def test_challenge_description_section_absent_when_empty(self):
        prompt = _build_user_prompt(_payload(challenge_description=""))
        assert "## Énoncé" not in prompt

    def test_test_output_included_when_present(self):
        prompt = _build_user_prompt(_payload(test_output="FAIL: 3 tests"))
        assert "FAIL: 3 tests" in prompt
        assert "## Sortie des tests" in prompt

    def test_test_output_truncated_at_2000_chars(self):
        big_output = "x" * 5000
        prompt = _build_user_prompt(_payload(test_output=big_output))
        # On ne doit pas voir plus de 2000 'x' consécutifs entre les fences.
        assert "x" * 2001 not in prompt

    def test_source_code_truncated_at_15000_chars(self):
        big_code = "y" * 30000
        prompt = _build_user_prompt(_payload(source_code=big_code))
        assert "y" * 15001 not in prompt

    def test_language_included_in_header(self):
        prompt = _build_user_prompt(_payload(language="rust"))
        assert "rust" in prompt

    def test_difficulty_included_in_header(self):
        prompt = _build_user_prompt(_payload(difficulty=4))
        assert "4/5" in prompt


# =========================================================================
# Robustesse aux réponses LLM partielles
# =========================================================================


class TestLLMResponseRobustness:
    async def test_missing_summary_defaults_to_empty_string(self):
        """Le LLM peut techniquement satisfaire le schema mais omettre summary
        via un contournement — le service doit rester résilient."""
        cm, _ = _mock_llm_returning({
            "overall_score": 70,
            "strengths": [],
            "findings": [],
            "learning_resources": [],
        })
        with cm:
            result = await review_code(_payload())
        assert result.summary == ""

    async def test_missing_findings_defaults_to_empty_list(self):
        cm, _ = _mock_llm_returning({
            "overall_score": 70,
            "summary": "OK",
            "strengths": [],
            "learning_resources": [],
        })
        with cm:
            result = await review_code(_payload())
        assert result.findings == []

    async def test_findings_validated_as_pydantic_models(self):
        """Chaque finding dans data['findings'] doit passer par
        CodeReviewFinding.model_validate — vérifie que le mapping fonctionne
        sur un finding complet."""
        cm, _ = _mock_llm_returning({
            "overall_score": 65,
            "summary": "Correct.",
            "strengths": ["s1"],
            "findings": [
                {
                    "category": "bug",
                    "severity": "high",
                    "line": 12,
                    "title": "Off-by-one",
                    "description": "Boucle mal bornée.",
                    "suggestion": "Utilise range(len(x)-1).",
                },
            ],
            "learning_resources": [],
        })
        with cm:
            result = await review_code(_payload())
        assert len(result.findings) == 1
        finding = result.findings[0]
        assert isinstance(finding, CodeReviewFinding)
        assert finding.category == "bug"
        assert finding.severity == "high"
        assert finding.line == 12
        assert finding.suggestion == "Utilise range(len(x)-1)."

    async def test_missing_score_defaults_to_0_and_zero_bonus(self):
        """Défense en profondeur si le LLM oublie overall_score : score=0,
        bonus=0 — pas de crash."""
        cm, _ = _mock_llm_returning({
            "summary": "",
            "strengths": [],
            "findings": [],
            "learning_resources": [],
        })
        with cm:
            result = await review_code(_payload())
        assert result.overall_score == 0
        assert result.fragments_bonus == 0


# =========================================================================
# Propagation d'identifiants
# =========================================================================


class TestIdentifierPropagation:
    async def test_submission_and_challenge_ids_preserved(self):
        cm, _ = _mock_llm_returning(_llm_response(80))
        with cm:
            result = await review_code(
                _payload(submission_id="SUB-XYZ", challenge_id="CHAL-ABC")
            )
        assert result.submission_id == "SUB-XYZ"
        assert result.challenge_id == "CHAL-ABC"

    async def test_llm_called_with_premium_tier(self):
        """`review_code` utilise le tier PREMIUM (voir docstring service).
        Le mapping PREMIUM → Qwen 7B côté Ollama et Opus côté Claude est
        assumé — vérifie que le service demande bien PREMIUM."""
        from src.llm.base import ModelTier

        cm, llm = _mock_llm_returning(_llm_response(70))
        with cm:
            await review_code(_payload())
        _, kwargs = llm.complete_structured.call_args
        assert kwargs["tier"] == ModelTier.PREMIUM
