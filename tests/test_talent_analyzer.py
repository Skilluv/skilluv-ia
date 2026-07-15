"""M3 tests: talent_analyzer service + TalentDetection gRPC servicer.

On mocke `_call_claude_structured` pour éviter tout appel réseau. Les tests
vérifient le comportement du service (dégénérés, mapping, filtrage) et le
mapping proto <-> pydantic complet.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from grpc import aio

from src.grpc_server.generated import skilluv_ai_pb2 as pb2
from src.grpc_server.generated import skilluv_ai_pb2_grpc as pb2_grpc
from src.grpc_server.talent_detection_servicer import (
    TalentDetectionServicer,
    _analyze_to_response,
    _career_to_response,
)
from src.models.talent_analysis import (
    AnalyzePerformancePayload,
    AnalyzePerformanceResult,
    CareerPathPayload,
    CareerPathResult,
    GapItem,
    MissingCriterion,
    NextAction,
    OrientationSuggestion,
    RankReadiness,
    SkillSnapshot,
    StrengthItem,
)
from src.services.talent_analyzer import (
    _load_orientations_catalog,
    analyze_performance,
    suggest_career_path,
)


# =========================================================================
# 1. Orientations catalog
# =========================================================================


class TestOrientationsCatalog:
    def test_catalog_loads(self):
        catalog = _load_orientations_catalog()
        assert "orientations" in catalog
        assert len(catalog["orientations"]) >= 6

    def test_every_orientation_has_required_fields(self):
        for o in _load_orientations_catalog()["orientations"]:
            assert isinstance(o["slug"], str) and o["slug"]
            assert o["critical_skills"], f"{o['slug']} sans critical_skills"
            assert "target_markets" in o
            assert "typical_transition_months" in o

    def test_slugs_are_unique(self):
        slugs = [o["slug"] for o in _load_orientations_catalog()["orientations"]]
        assert len(slugs) == len(set(slugs))


# =========================================================================
# 2. analyze_performance — comportement service (Claude mocké)
# =========================================================================


class TestAnalyzePerformance:
    @pytest.mark.asyncio
    async def test_empty_profile_returns_safe_default_no_llm_call(self):
        payload = AnalyzePerformancePayload(user_id="new-user")
        with patch(
            "src.services.talent_analyzer._call_claude_structured",
            new=AsyncMock(),
        ) as mock_call:
            result = await analyze_performance(payload)
        # Aucun appel LLM sur profil vide
        mock_call.assert_not_called()
        assert result.overall_score == 0.0
        assert result.next_actions[0].action_type == "attempt_challenge"
        assert result.next_actions[0].priority == 1

    @pytest.mark.asyncio
    async def test_non_empty_profile_calls_claude_and_maps_output(self):
        payload = AnalyzePerformancePayload(
            user_id="u-42",
            current_rank="bronze",
            skills=[SkillSnapshot(skill_slug="python", wpc_total=120, evidence_count=8)],
        )
        fake_claude_output = {
            "overall_score": 0.72,
            "strengths": [
                {"skill_slug": "python", "evidence_count": 8, "wpc_total": 120},
            ],
            "gaps": [
                {"skill_slug": "sql", "importance": "critical", "reason": "Manque pour backend."},
            ],
            "next_actions": [
                {"action_type": "attempt_challenge", "target_slug": "sql-basics", "priority": 1},
            ],
            "rank_readiness": {
                "current_rank": "bronze",
                "next_rank": "silver",
                "missing_criteria": [
                    {"criterion": "wpc_total", "current_value": 120.0, "threshold": 200.0},
                ],
                "estimated_days_to_promotion": 30,
            },
        }
        with patch(
            "src.services.talent_analyzer._call_claude_structured",
            new=AsyncMock(return_value=fake_claude_output),
        ) as mock_call:
            result = await analyze_performance(payload)

        mock_call.assert_awaited_once()
        assert result.overall_score == pytest.approx(0.72)
        assert result.strengths[0].skill_slug == "python"
        assert result.gaps[0].importance == "critical"
        assert result.next_actions[0].target_slug == "sql-basics"
        assert result.rank_readiness.next_rank == "silver"
        assert result.rank_readiness.missing_criteria[0].threshold == 200.0
        assert result.rank_readiness.estimated_days_to_promotion == 30


# =========================================================================
# 3. suggest_career_path — comportement service
# =========================================================================


class TestSuggestCareerPath:
    @pytest.mark.asyncio
    async def test_empty_skills_returns_default_generalist_no_llm(self):
        payload = CareerPathPayload(user_id="onboard-1")
        with patch(
            "src.services.talent_analyzer._call_claude_structured", new=AsyncMock()
        ) as mock_call:
            result = await suggest_career_path(payload)
        mock_call.assert_not_called()
        assert result.primary_recommendation == "dev-frontend"

    @pytest.mark.asyncio
    async def test_filters_slugs_not_in_catalog(self):
        payload = CareerPathPayload(
            user_id="u-1",
            skills=[SkillSnapshot(skill_slug="python", wpc_total=200, evidence_count=15)],
            target_market="africa",
        )
        fake_output = {
            "suggestions": [
                {
                    "orientation_slug": "dev-backend",  # valide
                    "confidence": 0.85,
                    "match_reason": "Python solide.",
                    "required_skills_missing": ["sql"],
                    "transition_effort": "medium",
                    "timeline_estimate_months": 5,
                },
                {
                    "orientation_slug": "ninja-astronaut",  # invalide -> filtré
                    "confidence": 0.99,
                    "match_reason": "wat",
                    "required_skills_missing": [],
                    "transition_effort": "low",
                    "timeline_estimate_months": 1,
                },
            ],
            "primary_recommendation": "dev-backend",
            "secondary_recommendations": ["dev-frontend", "orga-fantomatique"],
        }
        with patch(
            "src.services.talent_analyzer._call_claude_structured",
            new=AsyncMock(return_value=fake_output),
        ):
            result = await suggest_career_path(payload)

        # Suggestions filtrées : ninja-astronaut hors catalogue -> retiré
        assert len(result.suggestions) == 1
        assert result.suggestions[0].orientation_slug == "dev-backend"
        # secondary : orga-fantomatique retiré
        assert "dev-frontend" in result.secondary_recommendations
        assert "orga-fantomatique" not in result.secondary_recommendations
        assert result.primary_recommendation == "dev-backend"

    @pytest.mark.asyncio
    async def test_primary_falls_back_when_invalid(self):
        payload = CareerPathPayload(
            user_id="u-2",
            skills=[SkillSnapshot(skill_slug="figma", wpc_total=90, evidence_count=6)],
        )
        fake_output = {
            "suggestions": [
                {
                    "orientation_slug": "ui-designer",
                    "confidence": 0.9,
                    "match_reason": "Figma marqué.",
                    "required_skills_missing": [],
                    "transition_effort": "low",
                    "timeline_estimate_months": 3,
                },
            ],
            "primary_recommendation": "invalid-slug",  # sera remplacé
            "secondary_recommendations": [],
        }
        with patch(
            "src.services.talent_analyzer._call_claude_structured",
            new=AsyncMock(return_value=fake_output),
        ):
            result = await suggest_career_path(payload)
        # primary_recommendation invalide -> fallback sur 1re suggestion valide
        assert result.primary_recommendation == "ui-designer"


# =========================================================================
# 4. Mapping proto <-> pydantic (servicer helpers)
# =========================================================================


class TestAnalyzeMapping:
    def test_full_response_mapping(self):
        result = AnalyzePerformanceResult(
            overall_score=0.65,
            strengths=[StrengthItem(skill_slug="python", evidence_count=5, wpc_total=100)],
            gaps=[GapItem(skill_slug="sql", importance="critical", reason="requis backend")],
            next_actions=[
                NextAction(action_type="seek_mentor", target_slug="mentor-sql", priority=2),
            ],
            rank_readiness=RankReadiness(
                current_rank="bronze",
                next_rank="silver",
                missing_criteria=[
                    MissingCriterion(criterion="wpc_total", current_value=100, threshold=200),
                ],
                estimated_days_to_promotion=45,
            ),
        )
        response = _analyze_to_response(result)
        assert response.overall_score == pytest.approx(0.65)
        assert response.model_version == "claude-sonnet-4-6"
        assert response.strengths[0].skill_slug == "python"
        assert response.gaps[0].importance == "critical"
        assert response.next_actions[0].action_type == "seek_mentor"
        assert response.rank_readiness.next_rank == "silver"
        assert response.rank_readiness.missing_criteria[0].threshold == 200.0
        assert response.rank_readiness.estimated_days_to_promotion == 45


class TestCareerMapping:
    def test_full_response_mapping(self):
        result = CareerPathResult(
            suggestions=[
                OrientationSuggestion(
                    orientation_slug="dev-backend",
                    confidence=0.85,
                    match_reason="Python + SQL solides.",
                    required_skills_missing=["docker"],
                    transition_effort="medium",
                    timeline_estimate_months=4,
                ),
            ],
            primary_recommendation="dev-backend",
            secondary_recommendations=["dev-frontend"],
        )
        response = _career_to_response(result)
        assert response.primary_recommendation == "dev-backend"
        assert list(response.secondary_recommendations) == ["dev-frontend"]
        assert response.model_version.startswith("claude-haiku")
        assert response.suggestions[0].orientation_slug == "dev-backend"
        assert response.suggestions[0].confidence == pytest.approx(0.85)
        assert list(response.suggestions[0].required_skills_missing) == ["docker"]
        assert response.suggestions[0].transition_effort == "medium"


# =========================================================================
# 5. Integration — round-trip aio.grpc réel
# =========================================================================


class TestTalentDetectionOverTheWire:
    @pytest.mark.asyncio
    async def test_analyze_performance_end_to_end(self):
        server = aio.server()
        pb2_grpc.add_TalentDetectionServiceServicer_to_server(
            TalentDetectionServicer(), server
        )
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        fake_output = {
            "overall_score": 0.5,
            "strengths": [],
            "gaps": [],
            "next_actions": [
                {"action_type": "attempt_challenge", "target_slug": "sql-101", "priority": 1},
            ],
            "rank_readiness": {
                "current_rank": "bronze", "next_rank": "silver",
                "missing_criteria": [], "estimated_days_to_promotion": 20,
            },
        }
        try:
            with patch(
                "src.services.talent_analyzer._call_claude_structured",
                new=AsyncMock(return_value=fake_output),
            ):
                async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                    stub = pb2_grpc.TalentDetectionServiceStub(channel)
                    request = pb2.AnalyzePerformanceRequest(user_id="u-1", current_rank="bronze")
                    request.skills.add(skill_slug="python", wpc_total=50, evidence_count=3)
                    response = await stub.AnalyzePerformance(request, timeout=10)
            assert response.overall_score == pytest.approx(0.5)
            assert response.next_actions[0].target_slug == "sql-101"
            assert response.model_version == "claude-sonnet-4-6"
        finally:
            await server.stop(grace=None)

    @pytest.mark.asyncio
    async def test_career_path_end_to_end(self):
        server = aio.server()
        pb2_grpc.add_TalentDetectionServiceServicer_to_server(
            TalentDetectionServicer(), server
        )
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        fake_output = {
            "suggestions": [
                {
                    "orientation_slug": "dev-backend",
                    "confidence": 0.8,
                    "match_reason": "python fort",
                    "required_skills_missing": ["sql"],
                    "transition_effort": "medium",
                    "timeline_estimate_months": 5,
                },
            ],
            "primary_recommendation": "dev-backend",
            "secondary_recommendations": [],
        }
        try:
            with patch(
                "src.services.talent_analyzer._call_claude_structured",
                new=AsyncMock(return_value=fake_output),
            ):
                async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                    stub = pb2_grpc.TalentDetectionServiceStub(channel)
                    request = pb2.CareerPathRequest(
                        user_id="u-1", target_market="africa", max_suggestions=3,
                    )
                    request.skills.add(skill_slug="python", wpc_total=200, evidence_count=15)
                    response = await stub.SuggestCareerPath(request, timeout=10)
            assert response.primary_recommendation == "dev-backend"
            assert response.suggestions[0].confidence == pytest.approx(0.8)
            assert response.model_version.startswith("claude-haiku")
        finally:
            await server.stop(grace=None)
