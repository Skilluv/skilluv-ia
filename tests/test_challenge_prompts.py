"""Tests des prompts spécialisés par domaine."""

from src.models.challenge import ChallengeParams
from src.services._challenge_prompts import (
    DOMAIN_CONTEXTS,
    build_system_prompt,
    build_user_prompt,
)


class TestDomainContexts:
    def test_all_domains_defined(self) -> None:
        assert "code" in DOMAIN_CONTEXTS
        assert "design" in DOMAIN_CONTEXTS
        assert "game" in DOMAIN_CONTEXTS
        assert "security" in DOMAIN_CONTEXTS

    def test_each_domain_has_required_fields(self) -> None:
        for domain, ctx in DOMAIN_CONTEXTS.items():
            assert "description" in ctx, f"{domain} missing description"
            assert "context" in ctx, f"{domain} missing context"
            assert "examples" in ctx, f"{domain} missing examples"


class TestBuildSystemPrompt:
    def test_code_domain_mentions_test_cases(self) -> None:
        params = ChallengeParams(skill_domain="code", difficulty=3, duration_minutes=30)
        prompt = build_system_prompt(params)
        assert "test cases" in prompt.lower() or "test_cases" in prompt

    def test_design_domain_mentions_criteria(self) -> None:
        params = ChallengeParams(skill_domain="design", difficulty=2, duration_minutes=45)
        prompt = build_system_prompt(params)
        assert "design" in prompt.lower()
        assert any(word in prompt.lower() for word in ["visuel", "ergonomie", "UX", "responsive"])

    def test_game_domain_mentions_gameplay(self) -> None:
        params = ChallengeParams(skill_domain="game", difficulty=3, duration_minutes=60)
        prompt = build_system_prompt(params)
        assert any(word in prompt.lower() for word in ["gameplay", "game", "jeu"])

    def test_security_domain_mentions_ctf(self) -> None:
        params = ChallengeParams(skill_domain="security", difficulty=4, duration_minutes=60)
        prompt = build_system_prompt(params)
        assert "CTF" in prompt or "ctf" in prompt or "flag" in prompt.lower()
        assert "skilluv{" in prompt

    def test_french_language(self) -> None:
        params = ChallengeParams(skill_domain="code", difficulty=1, duration_minutes=15, language="fr")
        prompt = build_system_prompt(params)
        assert "français" in prompt

    def test_english_language(self) -> None:
        params = ChallengeParams(skill_domain="code", difficulty=1, duration_minutes=15, language="en")
        prompt = build_system_prompt(params)
        assert "English" in prompt

    def test_absurd_tone(self) -> None:
        params = ChallengeParams(skill_domain="code", difficulty=2, duration_minutes=15, tone="absurd")
        prompt = build_system_prompt(params)
        assert "absurde" in prompt.lower() or "absurd" in prompt.lower()

    def test_high_difficulty_more_hidden_tests(self) -> None:
        params_low = ChallengeParams(skill_domain="code", difficulty=2, duration_minutes=15)
        params_high = ChallengeParams(skill_domain="code", difficulty=5, duration_minutes=60)
        prompt_low = build_system_prompt(params_low)
        prompt_high = build_system_prompt(params_high)
        # Difficulté haute doit demander plus de tests cachés
        assert "4 tests cachés" in prompt_high or "4 tests" in prompt_high
        assert "2 tests cachés" in prompt_low or "2 tests" in prompt_low

    def test_programming_language_included(self) -> None:
        params = ChallengeParams(
            skill_domain="code", difficulty=3, duration_minutes=30,
            programming_language="python",
        )
        prompt = build_system_prompt(params)
        assert "python" in prompt

    def test_no_ai_allowed(self) -> None:
        params = ChallengeParams(skill_domain="code", difficulty=3, duration_minutes=30, ai_allowed=False)
        prompt = build_system_prompt(params)
        assert "non" in prompt.lower() or "trivialement" in prompt


class TestBuildUserPrompt:
    def test_basic_prompt(self) -> None:
        params = ChallengeParams(skill_domain="code", difficulty=3, duration_minutes=30)
        prompt = build_user_prompt(params)
        assert "code" in prompt
        assert "3/5" in prompt
        assert "30 minutes" in prompt

    def test_with_tags(self) -> None:
        params = ChallengeParams(
            skill_domain="code", difficulty=2, duration_minutes=15,
            tags=["algorithme", "tri"],
        )
        prompt = build_user_prompt(params)
        assert "algorithme" in prompt
        assert "tri" in prompt

    def test_with_programming_language(self) -> None:
        params = ChallengeParams(
            skill_domain="code", difficulty=3, duration_minutes=30,
            programming_language="rust",
        )
        prompt = build_user_prompt(params)
        assert "rust" in prompt
