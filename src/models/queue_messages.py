from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QueueMessage(BaseModel):
    """Format uniforme de tous les messages reçus via Redis Queue."""

    job_id: str = Field(description="UUID v4 unique du job")
    job_type: str = Field(description="Type de job: plagiarism_check | talent_match | replay_generate | clip_generate")
    payload: dict[str, Any] = Field(description="Contenu spécifique au job")
    created_at: datetime = Field(description="Timestamp de création ISO 8601 UTC")
    retry_count: int = Field(default=0, description="Nombre de tentatives déjà effectuées")


# --- Payloads spécifiques par job_type ---


class PlagiarismPayload(BaseModel):
    """Payload pour un job de détection de plagiat."""

    submission_id: str
    challenge_id: str
    source_code: str
    language: str
    compare_with: list["PlagiarismSubmission"]


class PlagiarismSubmission(BaseModel):
    """Soumission à comparer dans un job de plagiat."""

    submission_id: str
    user_id: str
    source_code: str


class TalentMatchPayload(BaseModel):
    """Payload pour un job de matching talent."""

    enterprise_id: str
    criteria: "MatchCriteria"
    candidates: list["TalentSnapshot"]


class MatchCriteria(BaseModel):
    """Critères de recherche d'une entreprise."""

    skill_domains: list[str] = Field(default_factory=list)
    min_fragments: int = 0
    min_title: str | None = None
    country: str | None = None
    languages: list[str] = Field(default_factory=list)
    # Phase 5.4 : description libre du poste, activera le scoring sémantique.
    job_description: str | None = None


class TalentSnapshot(BaseModel):
    """Snapshot minimal d'un talent pour le matching."""

    user_id: str
    username: str
    skill_domains: list[str]
    total_fragments: int
    title: str
    country: str | None = None
    top_languages: list[str] = Field(default_factory=list)
    trust_score: float = 0.0
    # Phase 5.4 : bio pour scoring sémantique (optionnelle).
    bio: str | None = None


class ReplayPayload(BaseModel):
    """Payload pour la génération d'un replay."""

    submission_id: str
    challenge_id: str
    user_id: str
    events: list[dict[str, Any]] = Field(description="Événements d'édition horodatés")
    stats: "SubmissionStats"


class SubmissionStats(BaseModel):
    """Statistiques d'une soumission pour le replay."""

    duration_seconds: int
    keystrokes: int
    tests_passed: int
    tests_total: int
    fragments_earned: int


class ClipPayload(BaseModel):
    """Payload pour la génération d'un clip 30s."""

    submission_id: str
    challenge_id: str
    user_id: str
    clip_type: str = Field(description="top3 | exceptional | absurd")
    replay_key: str = Field(description="Clé MinIO du replay source")
    highlight_start_seconds: int
    highlight_duration_seconds: int = 30
