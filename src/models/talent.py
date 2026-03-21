from pydantic import BaseModel, Field


class TalentProfile(BaseModel):
    """Profil talent pour le matching — données reçues depuis Rust."""

    user_id: str
    username: str
    skill_domains: list[str]
    total_fragments: int
    title: str
    stars: int = 0
    country: str | None = None
    top_languages: list[str] = Field(default_factory=list)
    trust_score: float = 0.0
    streak_days: int = 0


class MatchCriteria(BaseModel):
    """Critères de recherche envoyés par une entreprise."""

    skill_domains: list[str] = Field(default_factory=list)
    min_fragments: int = 0
    min_title: str | None = None
    country: str | None = None
    languages: list[str] = Field(default_factory=list)
    min_trust_score: float = 0.0
