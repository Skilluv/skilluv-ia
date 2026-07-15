"""Modèles pour les recommandations de challenges — Phase 5.5."""

from pydantic import BaseModel, Field


class UserProfileSnapshot(BaseModel):
    """Snapshot minimal du profil utilisateur pour recommandation."""

    user_id: str
    skill_domain: str
    title: str
    total_fragments: int = 0
    streak_current: int = 0
    top_sub_skills: list[str] = Field(default_factory=list)
    top_languages: list[str] = Field(default_factory=list)
    recently_completed_challenge_ids: list[str] = Field(default_factory=list)
    weak_areas: list[str] = Field(default_factory=list)


class CandidateChallenge(BaseModel):
    """Challenge candidat à recommander."""

    challenge_id: str
    title: str
    skill_domain: str
    sub_skills: list[str] = Field(default_factory=list)
    difficulty: int
    duration_minutes: int
    tags: list[str] = Field(default_factory=list)
    completion_count: int = 0


class RecommendationPayload(BaseModel):
    """Payload d'un job de recommandations."""

    user: UserProfileSnapshot
    candidates: list[CandidateChallenge]
    top_n: int = 5


class ChallengeRecommendation(BaseModel):
    """Un challenge recommandé avec justification."""

    challenge_id: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str
    growth_category: str = Field(
        description="consolidation | growth | stretch — niveau de challenge",
    )


class RecommendationResult(BaseModel):
    """Résultat d'un job de recommandation."""

    user_id: str
    recommendations: list[ChallengeRecommendation]
