"""Tests des analytics IA — Phase 5.13."""

import pytest

from src.models.analytics import ChurnPayload, HiddenGemsPayload, TalentStats
from src.services.analytics_ai import detect_hidden_gems, predict_churn


def _talent(**overrides) -> TalentStats:
    base = {
        "user_id": "u1",
        "username": "alice",
        "total_fragments": 300,
        "golden_stars": 5,
        "streak_current": 10,
        "challenges_completed_30d": 8,
        "avg_score_30d": 78.0,
        "days_since_last_activity": 1,
        "days_since_signup": 90,
        "profile_active": True,
        "followers_count": 20,
    }
    base.update(overrides)
    return TalentStats(**base)


@pytest.mark.asyncio
async def test_hidden_gem_detects_active_low_visibility_talent():
    talents = [
        _talent(
            user_id="gem",
            total_fragments=800,
            streak_current=45,
            challenges_completed_30d=25,
            avg_score_30d=88.0,
            followers_count=15,
        ),
        _talent(
            user_id="star",  # already famous, should be filtered out or downscored
            total_fragments=800,
            streak_current=45,
            followers_count=5000,
        ),
        _talent(user_id="new", days_since_signup=5),  # too fresh
    ]
    result = await detect_hidden_gems(HiddenGemsPayload(talents=talents, top_n=10))
    ids = [g.user_id for g in result.gems]
    assert "gem" in ids
    assert "new" not in ids
    # 'star' peut être inclus, mais 'gem' doit avoir un score >= à 'star'
    gem_score = next(g.score for g in result.gems if g.user_id == "gem")
    assert gem_score >= 0.5


@pytest.mark.asyncio
async def test_churn_flags_inactive_talent():
    talents = [
        _talent(
            user_id="churn",
            days_since_last_activity=30,
            streak_current=0,
            challenges_completed_30d=0,
            avg_score_30d=40.0,
        ),
        _talent(user_id="healthy"),
    ]
    result = await predict_churn(ChurnPayload(talents=talents, horizon_days=14))
    by_id = {p.user_id: p for p in result.predictions}
    assert by_id["churn"].churn_risk > by_id["healthy"].churn_risk
    assert by_id["churn"].risk_band in ("high", "critical")
    assert by_id["healthy"].risk_band == "low"


@pytest.mark.asyncio
async def test_churn_deactivated_profile_is_max_risk():
    result = await predict_churn(
        ChurnPayload(talents=[_talent(user_id="off", profile_active=False)])
    )
    assert result.predictions[0].churn_risk == 1.0
    assert result.predictions[0].risk_band == "critical"
