"""Tests du service de matching talent."""

import pytest

from src.models.queue_messages import MatchCriteria, TalentMatchPayload, TalentSnapshot
from src.services.talent_matcher import (
    _compute_relevance,
    _passes_filters,
    match_talents,
)


def _make_candidate(**kwargs) -> TalentSnapshot:
    """Helper pour créer un candidat avec des valeurs par défaut."""
    defaults = {
        "user_id": "user-001",
        "username": "kofi",
        "skill_domains": ["code"],
        "total_fragments": 1200,
        "title": "Artisan",
        "country": "BJ",
        "top_languages": ["python", "rust"],
        "trust_score": 0.85,
    }
    defaults.update(kwargs)
    return TalentSnapshot(**defaults)


# === Tests Filtres ===


class TestPassesFilters:
    def test_passes_all_filters(self) -> None:
        candidate = _make_candidate()
        criteria = MatchCriteria(
            skill_domains=["code"],
            min_fragments=500,
            min_title="Artisan",
            country="BJ",
        )
        assert _passes_filters(candidate, criteria) is True

    def test_fails_domain_filter(self) -> None:
        candidate = _make_candidate(skill_domains=["design"])
        criteria = MatchCriteria(skill_domains=["code"])
        assert _passes_filters(candidate, criteria) is False

    def test_fails_fragments_filter(self) -> None:
        candidate = _make_candidate(total_fragments=100)
        criteria = MatchCriteria(min_fragments=500)
        assert _passes_filters(candidate, criteria) is False

    def test_fails_title_filter(self) -> None:
        candidate = _make_candidate(title="Apprenti")
        criteria = MatchCriteria(min_title="Maître")
        assert _passes_filters(candidate, criteria) is False

    def test_fails_country_filter(self) -> None:
        candidate = _make_candidate(country="GH")
        criteria = MatchCriteria(country="BJ")
        assert _passes_filters(candidate, criteria) is False

    def test_no_criteria_passes_all(self) -> None:
        candidate = _make_candidate()
        criteria = MatchCriteria()
        assert _passes_filters(candidate, criteria) is True

    def test_legende_passes_maitre_filter(self) -> None:
        candidate = _make_candidate(title="Légende")
        criteria = MatchCriteria(min_title="Maître")
        assert _passes_filters(candidate, criteria) is True

    def test_multi_domain_match(self) -> None:
        candidate = _make_candidate(skill_domains=["code", "security"])
        criteria = MatchCriteria(skill_domains=["security"])
        assert _passes_filters(candidate, criteria) is True


# === Tests Scoring ===


class TestComputeRelevance:
    def test_perfect_candidate_high_score(self) -> None:
        candidate = _make_candidate(
            title="Légende",
            total_fragments=8000,
            trust_score=0.95,
            top_languages=["python", "rust"],
        )
        criteria = MatchCriteria(
            skill_domains=["code"],
            min_fragments=1000,
            languages=["python", "rust"],
        )
        score, matching = _compute_relevance(candidate, criteria)
        assert score > 80.0

    def test_mediocre_candidate_lower_score(self) -> None:
        candidate = _make_candidate(
            title="Apprenti",
            total_fragments=200,
            trust_score=0.3,
            top_languages=[],
        )
        criteria = MatchCriteria(
            skill_domains=["code"],
            min_fragments=100,
            languages=["python"],
        )
        score, _ = _compute_relevance(candidate, criteria)
        assert score < 50.0

    def test_matching_criteria_reported(self) -> None:
        candidate = _make_candidate(
            top_languages=["python", "rust"],
            trust_score=0.9,
        )
        criteria = MatchCriteria(
            skill_domains=["code"],
            languages=["python"],
        )
        _, matching = _compute_relevance(candidate, criteria)
        assert any("domains" in m for m in matching)
        assert any("python" in m for m in matching)
        assert any("trust" in m for m in matching)

    def test_no_criteria_still_scores(self) -> None:
        candidate = _make_candidate()
        criteria = MatchCriteria()
        score, _ = _compute_relevance(candidate, criteria)
        assert score > 0


# === Tests Intégration ===


class TestMatchTalents:
    @pytest.mark.asyncio
    async def test_basic_matching(self) -> None:
        payload = TalentMatchPayload(
            enterprise_id="ent-001",
            criteria=MatchCriteria(
                skill_domains=["code"],
                min_fragments=500,
            ),
            candidates=[
                _make_candidate(user_id="u1", username="kofi", total_fragments=2000),
                _make_candidate(user_id="u2", username="aicha", total_fragments=300),
                _make_candidate(user_id="u3", username="mamadou", total_fragments=800),
            ],
        )
        result = await match_talents(payload)

        assert result.enterprise_id == "ent-001"
        assert result.total_candidates == 3
        assert result.total_matched == 2  # aicha filtrée (300 < 500)
        # kofi (2000) devrait être devant mamadou (800)
        assert result.matched_talents[0].user_id == "u1"
        assert result.matched_talents[1].user_id == "u3"

    @pytest.mark.asyncio
    async def test_no_candidates_match(self) -> None:
        payload = TalentMatchPayload(
            enterprise_id="ent-001",
            criteria=MatchCriteria(
                skill_domains=["security"],
                min_fragments=10000,
            ),
            candidates=[
                _make_candidate(skill_domains=["code"], total_fragments=500),
            ],
        )
        result = await match_talents(payload)
        assert result.total_matched == 0
        assert result.matched_talents == []

    @pytest.mark.asyncio
    async def test_empty_candidates(self) -> None:
        payload = TalentMatchPayload(
            enterprise_id="ent-001",
            criteria=MatchCriteria(),
            candidates=[],
        )
        result = await match_talents(payload)
        assert result.total_matched == 0

    @pytest.mark.asyncio
    async def test_sorted_by_relevance(self) -> None:
        payload = TalentMatchPayload(
            enterprise_id="ent-001",
            criteria=MatchCriteria(skill_domains=["code"]),
            candidates=[
                _make_candidate(
                    user_id="u1", username="junior",
                    title="Apprenti", total_fragments=100, trust_score=0.3,
                ),
                _make_candidate(
                    user_id="u2", username="senior",
                    title="Légende", total_fragments=9000, trust_score=0.95,
                ),
                _make_candidate(
                    user_id="u3", username="mid",
                    title="Maître", total_fragments=4000, trust_score=0.7,
                ),
            ],
        )
        result = await match_talents(payload)

        assert result.total_matched == 3
        # Ordre : senior > mid > junior
        assert result.matched_talents[0].user_id == "u2"
        assert result.matched_talents[1].user_id == "u3"
        assert result.matched_talents[2].user_id == "u1"
        # Scores décroissants
        scores = [t.relevance_score for t in result.matched_talents]
        assert scores == sorted(scores, reverse=True)
