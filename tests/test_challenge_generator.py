"""Tests du service de génération de challenges."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.challenge import ChallengeParams, GeneratedChallenge
from src.services._challenge_prompts import build_system_prompt
from src.services.challenge_generator import (
    _calculate_fragment_reward,
    _extract_json,
    generate_challenge,
)


class TestCalculateFragmentReward:
    def test_basic_reward(self) -> None:
        params = ChallengeParams(skill_domain="code", difficulty=3, duration_minutes=30)
        reward = _calculate_fragment_reward(params)
        # difficulty=3, duration_factor=2 (30//15), complexity=1.3 (no ai)
        assert reward == int(3 * 2 * 1.3)

    def test_absurd_tone_bonus(self) -> None:
        params = ChallengeParams(
            skill_domain="code", difficulty=2, duration_minutes=15, tone="absurd"
        )
        reward = _calculate_fragment_reward(params)
        # difficulty=2, duration_factor=1, complexity=1.8 (absurd+no_ai)
        assert reward == int(2 * 1 * 1.8)

    def test_ai_allowed_reduces_reward(self) -> None:
        params_no_ai = ChallengeParams(
            skill_domain="code", difficulty=3, duration_minutes=30, ai_allowed=False
        )
        params_ai = ChallengeParams(
            skill_domain="code", difficulty=3, duration_minutes=30, ai_allowed=True
        )
        assert _calculate_fragment_reward(params_no_ai) > _calculate_fragment_reward(params_ai)

    def test_high_difficulty_high_duration(self) -> None:
        params = ChallengeParams(skill_domain="security", difficulty=5, duration_minutes=180)
        reward = _calculate_fragment_reward(params)
        assert reward > 50  # Doit être conséquent


class TestBuildSystemPrompt:
    def test_french_prompt(self) -> None:
        params = ChallengeParams(
            skill_domain="code", difficulty=3, duration_minutes=30, language="fr"
        )
        prompt = build_system_prompt(params)
        assert "français" in prompt
        assert "30 minutes" in prompt
        assert "3/5" in prompt

    def test_english_prompt(self) -> None:
        params = ChallengeParams(
            skill_domain="code", difficulty=3, duration_minutes=30, language="en"
        )
        prompt = build_system_prompt(params)
        assert "English" in prompt

    def test_programming_language_included(self) -> None:
        params = ChallengeParams(
            skill_domain="code",
            difficulty=3,
            duration_minutes=30,
            programming_language="python",
        )
        prompt = build_system_prompt(params)
        assert "python" in prompt

    def test_security_domain(self) -> None:
        params = ChallengeParams(skill_domain="security", difficulty=4, duration_minutes=60)
        prompt = build_system_prompt(params)
        assert "sécurité" in prompt.lower() or "CTF" in prompt

    def test_absurd_tone(self) -> None:
        params = ChallengeParams(
            skill_domain="code", difficulty=2, duration_minutes=15, tone="absurd"
        )
        prompt = build_system_prompt(params)
        assert "absurde" in prompt.lower() or "drôle" in prompt.lower()


class TestExtractJson:
    def test_clean_json(self) -> None:
        data = _extract_json('{"title": "Hello"}')
        assert data["title"] == "Hello"

    def test_code_fences(self) -> None:
        data = _extract_json('```json\n{"title": "Hello"}\n```')
        assert data["title"] == "Hello"

    def test_text_before_json(self) -> None:
        data = _extract_json('Here is the challenge:\n{"title": "Hello"}')
        assert data["title"] == "Hello"

    def test_text_around_json(self) -> None:
        data = _extract_json('Sure!\n{"title": "Hello"}\nHope this helps!')
        assert data["title"] == "Hello"

    def test_invalid_json_raises(self) -> None:
        from src.exceptions import ValidationError

        with pytest.raises(ValidationError):
            _extract_json("not json at all")


class TestGenerateChallenge:
    @pytest.fixture
    def mock_claude_response(self) -> dict:
        return {
            "title": "Le Tri des Pingouins",
            "description": "## Contexte\nDes pingouins doivent être triés...",
            "instructions": "1. Implémenter la fonction sort_penguins\n2. ...",
            "starter_code": "def sort_penguins(penguins: list) -> list:\n    pass",
            "test_cases": [
                {
                    "input": "[3, 1, 2]",
                    "expected_output": "[1, 2, 3]",
                    "description": "Tri simple",
                    "is_hidden": False,
                },
                {
                    "input": "[]",
                    "expected_output": "[]",
                    "description": "Liste vide",
                    "is_hidden": False,
                },
                {
                    "input": "[1]",
                    "expected_output": "[1]",
                    "description": "Un seul élément",
                    "is_hidden": False,
                },
                {
                    "input": "[5, 5, 5]",
                    "expected_output": "[5, 5, 5]",
                    "description": "Doublons",
                    "is_hidden": True,
                },
                {
                    "input": "[10, 9, 8, 7, 6, 5, 4, 3, 2, 1]",
                    "expected_output": "[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]",
                    "description": "Ordre inverse",
                    "is_hidden": True,
                },
            ],
            "evaluation_criteria": "Complexité O(n log n), gestion des edge cases",
            "tags": ["algorithme", "tri"],
        }

    @pytest.mark.asyncio
    async def test_generate_challenge_success(self, mock_claude_response: dict) -> None:
        mock_provider = MagicMock()
        mock_provider.complete_structured = AsyncMock(return_value=mock_claude_response)

        with patch(
            "src.services.challenge_generator.get_llm",
            return_value=mock_provider,
        ):
            params = ChallengeParams(
                skill_domain="code",
                difficulty=3,
                duration_minutes=30,
                tone="fun",
                language="fr",
                programming_language="python",
            )
            result = await generate_challenge(params)

        assert isinstance(result, GeneratedChallenge)
        assert result.title == "Le Tri des Pingouins"
        assert result.difficulty == 3
        assert result.skill_domain == "code"
        assert len(result.test_cases) == 5
        assert result.fragment_reward > 0
        assert result.language == "fr"

    @pytest.mark.asyncio
    async def test_generate_challenge_strips_markdown_fences(
        self, mock_claude_response: dict
    ) -> None:
        """Backward compat : le provider gère l'unwrap/validation en amont,
        challenge_generator ne fait plus de parsing text-based."""
        mock_provider = MagicMock()
        mock_provider.complete_structured = AsyncMock(return_value=mock_claude_response)
        with patch(
            "src.services.challenge_generator.get_llm",
            return_value=mock_provider,
        ):
            params = ChallengeParams(skill_domain="code", difficulty=2, duration_minutes=15)
            result = await generate_challenge(params)
        assert result.title == "Le Tri des Pingouins"

    @pytest.mark.asyncio
    async def test_generate_challenge_invalid_json_raises(self) -> None:
        """Si le provider raise ValidationError, elle se propage."""
        from src.exceptions import ValidationError as SkilluvValidationError

        mock_provider = MagicMock()
        mock_provider.complete_structured = AsyncMock(
            side_effect=SkilluvValidationError("JSON invalide", {})
        )
        with patch(
            "src.services.challenge_generator.get_llm",
            return_value=mock_provider,
        ):
            params = ChallengeParams(skill_domain="code", difficulty=1, duration_minutes=10)
            with pytest.raises(Exception) as exc_info:
                await generate_challenge(params)
            assert "JSON invalide" in str(exc_info.value)
