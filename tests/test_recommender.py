"""Tests du recommender — Phase 5.5.

Les tests couvrent uniquement la partie déterministe (`_base_score` +
`recommend_challenges` avec injection LLM mockée) — l'appel Haiku est stubbé.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.models.recommendations import (
    CandidateChallenge,
    RecommendationPayload,
    UserProfileSnapshot,
)
from src.services.recommender import _base_score, recommend_challenges


def _cand(**over) -> CandidateChallenge:
    base = {
        "challenge_id": "c1",
        "title": "Test",
        "skill_domain": "code",
        "sub_skills": ["python"],
        "difficulty": 2,
        "duration_minutes": 30,
        "completion_count": 100,
    }
    base.update(over)
    return CandidateChallenge(**base)


def _user(**over) -> UserProfileSnapshot:
    base = {
        "user_id": "u1",
        "skill_domain": "code",
        "title": "Artisan",
        "total_fragments": 500,
        "streak_current": 5,
        "top_sub_skills": ["python"],
        "top_languages": ["python"],
        "weak_areas": ["async"],
    }
    base.update(over)
    return UserProfileSnapshot(**base)


def test_base_score_zero_for_already_completed():
    u = _user(recently_completed_challenge_ids=["c1"])
    s, _ = _base_score(u, _cand())
    assert s == 0.0


def test_base_score_favors_domain_and_difficulty_match():
    u = _user()
    s_match, _ = _base_score(u, _cand(difficulty=2, sub_skills=["python"]))
    s_wrong_domain, _ = _base_score(u, _cand(difficulty=2, skill_domain="design"))
    assert s_match > s_wrong_domain


def test_base_score_growth_categories():
    u = _user()  # Artisan (level 2)
    _, g_growth = _base_score(u, _cand(difficulty=2))
    _, g_stretch = _base_score(u, _cand(difficulty=3))
    _, g_consol = _base_score(u, _cand(difficulty=1))
    assert g_growth == "growth"
    assert g_stretch == "stretch"
    assert g_consol == "consolidation"


def test_base_score_bonus_on_weak_areas():
    u = _user(weak_areas=["async"])
    s_weak, _ = _base_score(u, _cand(sub_skills=["async"]))
    s_neutral, _ = _base_score(u, _cand(sub_skills=["strings"]))
    assert s_weak > s_neutral


@pytest.mark.asyncio
async def test_recommend_challenges_returns_top_n():
    payload = RecommendationPayload(
        user=_user(),
        candidates=[
            _cand(challenge_id=f"c{i}", difficulty=(i % 5) + 1)
            for i in range(20)
        ],
        top_n=3,
    )
    with patch(
        "src.services.recommender._generate_reasons", new=AsyncMock(return_value={})
    ):
        result = await recommend_challenges(payload)
    assert len(result.recommendations) == 3
    # scores triés décroissants
    scores = [r.score for r in result.recommendations]
    assert scores == sorted(scores, reverse=True)
