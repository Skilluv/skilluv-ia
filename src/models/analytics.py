"""Modèles pour les analytics IA — Phase 5.13."""

from pydantic import BaseModel, Field


class TalentStats(BaseModel):
    """Snapshot compact utilisé par les analytics IA."""

    user_id: str
    username: str
    total_fragments: int = 0
    golden_stars: int = 0
    streak_current: int = 0
    challenges_completed_30d: int = 0
    avg_score_30d: float = 0.0
    days_since_last_activity: int = 0
    days_since_signup: int = 0
    profile_active: bool = True
    followers_count: int = 0
    hidden_gem_score_prev: float = 0.0


# --- Hidden gems --------------------------------------------------


class HiddenGemsPayload(BaseModel):
    """Payload : batch de talents à évaluer."""

    talents: list[TalentStats]
    top_n: int = 50


class HiddenGem(BaseModel):
    user_id: str
    username: str
    score: float = Field(ge=0.0, le=1.0)
    signals: list[str] = Field(default_factory=list)


class HiddenGemsResult(BaseModel):
    total_evaluated: int
    gems: list[HiddenGem]


# --- Churn prediction --------------------------------------------


class ChurnPayload(BaseModel):
    """Batch de talents à évaluer pour le risque de churn."""

    talents: list[TalentStats]
    horizon_days: int = 14


class ChurnPrediction(BaseModel):
    user_id: str
    username: str
    churn_risk: float = Field(ge=0.0, le=1.0)
    risk_band: str = Field(description="low | medium | high | critical")
    top_signals: list[str] = Field(default_factory=list)
    recommended_action: str


class ChurnResult(BaseModel):
    total_evaluated: int
    predictions: list[ChurnPrediction]
