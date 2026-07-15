"""Pydantic models for TalentDetectionService (MVP phase IA-M3).

Miroir des messages proto `skilluv_ai.proto` §3. Les snapshots sont fournis
par le backend (source de vérité) — l'IA ne fait AUCUN calcul métier
(pas de rangs, pas de WPC, pas de badges — voir MVP.md §4).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# --- Snapshots reçus du backend --------------------------------------------


class DeliverableSnapshot(BaseModel):
    deliverable_id: str
    skill_slug: str
    wpc: int = Field(ge=0, description="work-proven credits")
    verified_at: str = Field(description="RFC3339")
    verifiable_by: str = Field(
        description="test_suite | llm_evaluation | attestation"
    )
    difficulty: int = Field(ge=1, le=5)


class SkillSnapshot(BaseModel):
    skill_slug: str
    wpc_total: int = Field(ge=0)
    evidence_count: int = Field(ge=0)
    first_evidence_at: str = ""
    last_evidence_at: str = ""


class OrientationSnapshot(BaseModel):
    orientation_slug: str
    completion_ratio: float = Field(ge=0.0, le=1.0)


# --- Payloads gRPC -> service ----------------------------------------------


class AnalyzePerformancePayload(BaseModel):
    user_id: str
    deliverables: list[DeliverableSnapshot] = Field(default_factory=list)
    skills: list[SkillSnapshot] = Field(default_factory=list)
    orientations: list[OrientationSnapshot] = Field(default_factory=list)
    current_rank: str = ""


class CareerPathPayload(BaseModel):
    user_id: str
    skills: list[SkillSnapshot] = Field(default_factory=list)
    working_languages: list[str] = Field(default_factory=list)
    target_market: Literal["africa", "international", ""] = ""
    max_suggestions: int = Field(default=3, ge=1, le=10)


# --- Items retournés -------------------------------------------------------


class StrengthItem(BaseModel):
    skill_slug: str
    evidence_count: int = 0
    wpc_total: int = 0


class GapItem(BaseModel):
    skill_slug: str
    importance: Literal["critical", "nice_to_have"] = "nice_to_have"
    reason: str = ""


class NextAction(BaseModel):
    action_type: Literal["attempt_challenge", "seek_mentor", "take_attestation"]
    target_slug: str
    priority: int = Field(ge=1, le=5, default=3)


class MissingCriterion(BaseModel):
    criterion: str
    current_value: float
    threshold: float


class RankReadiness(BaseModel):
    current_rank: str = ""
    next_rank: str = ""
    missing_criteria: list[MissingCriterion] = Field(default_factory=list)
    estimated_days_to_promotion: int = 0


class OrientationSuggestion(BaseModel):
    orientation_slug: str
    confidence: float = Field(ge=0.0, le=1.0)
    match_reason: str = ""
    required_skills_missing: list[str] = Field(default_factory=list)
    transition_effort: Literal["low", "medium", "high"] = "medium"
    timeline_estimate_months: int = Field(ge=0, default=0)


# --- Results retournés par le service --------------------------------------


class AnalyzePerformanceResult(BaseModel):
    overall_score: float = Field(ge=0.0, le=1.0)
    strengths: list[StrengthItem] = Field(default_factory=list)
    gaps: list[GapItem] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)
    rank_readiness: RankReadiness = Field(default_factory=RankReadiness)


class CareerPathResult(BaseModel):
    suggestions: list[OrientationSuggestion] = Field(default_factory=list)
    primary_recommendation: str = ""
    secondary_recommendations: list[str] = Field(default_factory=list)
