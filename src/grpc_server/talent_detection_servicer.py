"""gRPC servicer for TalentDetectionService (MVP phase IA-M3).

Expose `AnalyzePerformance` et `SuggestCareerPath`. Mappe proto <-> pydantic
et délègue à `services.talent_analyzer`.
"""

from __future__ import annotations

import grpc

from src.exceptions import ExternalServiceError, ValidationError
from src.models.talent_analysis import (
    AnalyzePerformancePayload,
    AnalyzePerformanceResult,
    CareerPathPayload,
    CareerPathResult,
    DeliverableSnapshot,
    OrientationSnapshot,
    SkillSnapshot,
)
from src.services.talent_analyzer import analyze_performance, suggest_career_path
from src.utils.logging import get_logger

from src.grpc_server.generated import skilluv_ai_pb2 as pb2
from src.grpc_server.generated import skilluv_ai_pb2_grpc as pb2_grpc

logger = get_logger("grpc.talent_detection_servicer")

_MODEL_VERSION_ANALYZE = "claude-sonnet-4-6"
_MODEL_VERSION_CAREER = "claude-haiku-4-5-20251001"


# --- proto -> pydantic ----------------------------------------------------


def _build_analyze_payload(request: pb2.AnalyzePerformanceRequest) -> AnalyzePerformancePayload:
    return AnalyzePerformancePayload(
        user_id=request.user_id,
        deliverables=[
            DeliverableSnapshot(
                deliverable_id=d.deliverable_id,
                skill_slug=d.skill_slug,
                wpc=d.wpc,
                verified_at=d.verified_at,
                verifiable_by=d.verifiable_by,
                difficulty=d.difficulty or 1,
            )
            for d in request.deliverables
        ],
        skills=[
            SkillSnapshot(
                skill_slug=s.skill_slug,
                wpc_total=s.wpc_total,
                evidence_count=s.evidence_count,
                first_evidence_at=s.first_evidence_at,
                last_evidence_at=s.last_evidence_at,
            )
            for s in request.skills
        ],
        orientations=[
            OrientationSnapshot(
                orientation_slug=o.orientation_slug,
                completion_ratio=o.completion_ratio,
            )
            for o in request.orientations
        ],
        current_rank=request.current_rank,
    )


def _build_career_payload(request: pb2.CareerPathRequest) -> CareerPathPayload:
    return CareerPathPayload(
        user_id=request.user_id,
        skills=[
            SkillSnapshot(
                skill_slug=s.skill_slug,
                wpc_total=s.wpc_total,
                evidence_count=s.evidence_count,
                first_evidence_at=s.first_evidence_at,
                last_evidence_at=s.last_evidence_at,
            )
            for s in request.skills
        ],
        working_languages=list(request.working_languages),
        target_market=request.target_market or "",
        max_suggestions=request.max_suggestions if request.max_suggestions > 0 else 3,
    )


# --- pydantic -> proto ----------------------------------------------------


def _analyze_to_response(result: AnalyzePerformanceResult) -> pb2.AnalyzePerformanceResponse:
    response = pb2.AnalyzePerformanceResponse(
        overall_score=result.overall_score,
        model_version=_MODEL_VERSION_ANALYZE,
    )
    for s in result.strengths:
        response.strengths.add(
            skill_slug=s.skill_slug, evidence_count=s.evidence_count, wpc_total=s.wpc_total,
        )
    for g in result.gaps:
        response.gaps.add(skill_slug=g.skill_slug, importance=g.importance, reason=g.reason)
    for a in result.next_actions:
        response.next_actions.add(
            action_type=a.action_type, target_slug=a.target_slug, priority=a.priority,
        )
    response.rank_readiness.current_rank = result.rank_readiness.current_rank
    response.rank_readiness.next_rank = result.rank_readiness.next_rank
    response.rank_readiness.estimated_days_to_promotion = (
        result.rank_readiness.estimated_days_to_promotion
    )
    for c in result.rank_readiness.missing_criteria:
        response.rank_readiness.missing_criteria.add(
            criterion=c.criterion, current_value=c.current_value, threshold=c.threshold,
        )
    return response


def _career_to_response(result: CareerPathResult) -> pb2.CareerPathResponse:
    response = pb2.CareerPathResponse(
        primary_recommendation=result.primary_recommendation,
        secondary_recommendations=list(result.secondary_recommendations),
        model_version=_MODEL_VERSION_CAREER,
    )
    for s in result.suggestions:
        response.suggestions.add(
            orientation_slug=s.orientation_slug,
            confidence=s.confidence,
            match_reason=s.match_reason,
            required_skills_missing=list(s.required_skills_missing),
            transition_effort=s.transition_effort,
            timeline_estimate_months=s.timeline_estimate_months,
        )
    return response


# --- servicer -------------------------------------------------------------


class TalentDetectionServicer(pb2_grpc.TalentDetectionServiceServicer):
    async def AnalyzePerformance(
        self,
        request: pb2.AnalyzePerformanceRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.AnalyzePerformanceResponse:
        payload = _build_analyze_payload(request)
        logger.info(
            "grpc_analyze_performance_received",
            user_id=payload.user_id,
            skills=len(payload.skills),
            deliverables=len(payload.deliverables),
        )
        try:
            result = await analyze_performance(payload)
        except ExternalServiceError as e:
            await context.abort(grpc.StatusCode.UNAVAILABLE, f"llm upstream: {e}")
        except ValidationError as e:
            await context.abort(grpc.StatusCode.INTERNAL, f"llm invalid output: {e}")
        return _analyze_to_response(result)

    async def SuggestCareerPath(
        self,
        request: pb2.CareerPathRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.CareerPathResponse:
        payload = _build_career_payload(request)
        logger.info(
            "grpc_career_path_received",
            user_id=payload.user_id,
            skills=len(payload.skills),
            target_market=payload.target_market,
        )
        try:
            result = await suggest_career_path(payload)
        except ExternalServiceError as e:
            await context.abort(grpc.StatusCode.UNAVAILABLE, f"llm upstream: {e}")
        except ValidationError as e:
            await context.abort(grpc.StatusCode.INTERNAL, f"llm invalid output: {e}")
        return _career_to_response(result)


__all__ = ["TalentDetectionServicer"]
