from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JobResult(BaseModel):
    """Format uniforme de tous les résultats écrits dans Redis."""

    job_id: str
    status: str = Field(description="completed | failed")
    result: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0
    completed_at: datetime


# --- Résultats spécifiques par job_type ---


class PlagiarismMatch(BaseModel):
    """Résultat de comparaison entre deux soumissions."""

    compared_submission_id: str
    compared_user_id: str
    ast_similarity: float
    embedding_similarity: float
    combined_score: float
    is_plagiarism: bool


class PlagiarismResult(BaseModel):
    """Résultat complet d'un job de détection de plagiat."""

    submission_id: str
    challenge_id: str
    matches: list[PlagiarismMatch]
    highest_score: float
    flagged: bool


class TalentMatchResult(BaseModel):
    """Résultat d'un job de matching talent."""

    enterprise_id: str
    matched_talents: list["MatchedTalent"]
    total_candidates: int
    total_matched: int


class MatchedTalent(BaseModel):
    """Talent matché avec un score de pertinence."""

    user_id: str
    username: str
    relevance_score: float
    matching_criteria: list[str] = Field(description="Critères qui ont matché")


class MediaResult(BaseModel):
    """Résultat d'un job de traitement média (replay ou clip)."""

    submission_id: str
    media_type: str = Field(description="replay | clip")
    minio_key: str = Field(description="Chemin dans MinIO")
    file_size_bytes: int
    duration_seconds: float
