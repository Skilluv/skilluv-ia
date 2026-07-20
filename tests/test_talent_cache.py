"""Tests du cache Redis pour AnalyzePerformance.

Verifie :
- Clé déterministe (même snapshot -> même clé, ordre indifférent)
- Sensibilité aux changements (skill ajouté / rank changé -> clé différente)
- Intégration dans analyze_performance : hit -> pas d'appel LLM
- Fail-open : Redis down -> le service continue
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.models.talent_analysis import (
    AnalyzePerformancePayload,
    AnalyzePerformanceResult,
    DeliverableSnapshot,
    RankReadiness,
    SkillSnapshot,
)
from src.services._talent_cache import _build_cache_key, get_cached_analysis
from src.services.talent_analyzer import analyze_performance


def _payload(**over) -> AnalyzePerformancePayload:
    base = dict(
        user_id="u-1",
        current_rank="bronze",
        skills=[SkillSnapshot(skill_slug="python", wpc_total=100, evidence_count=5)],
        deliverables=[
            DeliverableSnapshot(
                deliverable_id="d-1", skill_slug="python", wpc=40,
                verified_at="2026-07-01T00:00:00Z", verifiable_by="test_suite",
                difficulty=3,
            )
        ],
        orientations=[],
    )
    base.update(over)
    return AnalyzePerformancePayload(**base)


class TestBuildCacheKey:
    def test_identical_payloads_same_key(self):
        assert _build_cache_key(_payload()) == _build_cache_key(_payload())

    def test_order_of_skills_irrelevant(self):
        p1 = _payload(
            skills=[
                SkillSnapshot(skill_slug="python", wpc_total=100, evidence_count=5),
                SkillSnapshot(skill_slug="sql", wpc_total=50, evidence_count=3),
            ]
        )
        p2 = _payload(
            skills=[
                SkillSnapshot(skill_slug="sql", wpc_total=50, evidence_count=3),
                SkillSnapshot(skill_slug="python", wpc_total=100, evidence_count=5),
            ]
        )
        assert _build_cache_key(p1) == _build_cache_key(p2)

    def test_different_rank_different_key(self):
        assert _build_cache_key(_payload(current_rank="bronze")) != _build_cache_key(
            _payload(current_rank="silver")
        )

    def test_added_skill_changes_key(self):
        p1 = _payload()
        p2 = _payload(
            skills=[
                SkillSnapshot(skill_slug="python", wpc_total=100, evidence_count=5),
                SkillSnapshot(skill_slug="sql", wpc_total=10, evidence_count=1),
            ]
        )
        assert _build_cache_key(p1) != _build_cache_key(p2)

    def test_key_contains_user_id_prefix(self):
        key = _build_cache_key(_payload(user_id="alice"))
        assert "alice" in key


class TestGetCachedAnalysisFailOpen:
    @pytest.mark.asyncio
    async def test_redis_error_returns_none(self):
        with patch(
            "src.services._talent_cache.get_redis",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            assert await get_cached_analysis(_payload()) is None


class TestAnalyzePerformanceCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_bypasses_llm(self):
        cached = AnalyzePerformanceResult(
            overall_score=0.42,
            rank_readiness=RankReadiness(current_rank="bronze"),
        )
        with (
            patch(
                "src.services.talent_analyzer.get_cached_analysis",
                new=AsyncMock(return_value=cached),
            ),
            patch(
                "src.services.talent_analyzer._call_claude_structured",
                new=AsyncMock(),
            ) as mock_llm,
            patch(
                "src.services.talent_analyzer.cache_analysis",
                new=AsyncMock(),
            ) as mock_write,
        ):
            result = await analyze_performance(_payload())
        assert result.overall_score == pytest.approx(0.42)
        mock_llm.assert_not_called()
        mock_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_miss_calls_llm_and_writes_cache(self):
        fake_llm = {
            "overall_score": 0.7,
            "strengths": [],
            "gaps": [],
            "next_actions": [
                {"action_type": "attempt_challenge", "target_slug": "sql", "priority": 1}
            ],
            "rank_readiness": {
                "current_rank": "bronze", "next_rank": "silver",
                "missing_criteria": [], "estimated_days_to_promotion": 10,
            },
        }
        with (
            patch(
                "src.services.talent_analyzer.get_cached_analysis",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "src.services.talent_analyzer._call_claude_structured",
                new=AsyncMock(return_value=fake_llm),
            ) as mock_llm,
            patch(
                "src.services.talent_analyzer.cache_analysis",
                new=AsyncMock(),
            ) as mock_write,
        ):
            result = await analyze_performance(_payload())
        mock_llm.assert_awaited_once()
        mock_write.assert_awaited_once()
        assert result.overall_score == pytest.approx(0.7)

    @pytest.mark.asyncio
    async def test_empty_profile_skips_cache_entirely(self):
        empty = AnalyzePerformancePayload(user_id="new-user")
        with (
            patch(
                "src.services.talent_analyzer.get_cached_analysis",
                new=AsyncMock(),
            ) as mock_get,
            patch(
                "src.services.talent_analyzer.cache_analysis",
                new=AsyncMock(),
            ) as mock_write,
        ):
            result = await analyze_performance(empty)
        # profil vide = short-circuit avant même le check cache
        mock_get.assert_not_called()
        mock_write.assert_not_called()
        assert result.overall_score == 0.0
