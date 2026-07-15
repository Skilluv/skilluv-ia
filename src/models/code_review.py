"""Modèles de payload/résultat pour le code review IA — Phase 5.2."""

from pydantic import BaseModel, Field


class CodeReviewPayload(BaseModel):
    """Payload d'un job de code review pédagogique."""

    submission_id: str
    challenge_id: str
    user_id: str
    language: str
    source_code: str
    challenge_title: str = ""
    challenge_description: str = ""
    difficulty: int = 1
    # Optionnel : output des tests / erreurs runtime pour enrichir le prompt.
    test_output: str | None = None
    # "beginner" | "intermediate" | "advanced" — module le ton pédagogique.
    user_level: str = "intermediate"


class CodeReviewFinding(BaseModel):
    """Une remarque individuelle."""

    category: str = Field(description="bug | style | perf | security | pedagogy | best_practice")
    severity: str = Field(description="info | low | medium | high | critical")
    line: int | None = None
    title: str
    description: str
    suggestion: str | None = None


class CodeReviewResult(BaseModel):
    """Résultat complet d'un code review."""

    submission_id: str
    challenge_id: str
    overall_score: int = Field(ge=0, le=100, description="Score global sur 100")
    summary: str
    strengths: list[str] = Field(default_factory=list)
    findings: list[CodeReviewFinding] = Field(default_factory=list)
    learning_resources: list[str] = Field(default_factory=list)
    fragments_bonus: int = 0
