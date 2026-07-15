"""Analytics IA — Phase 5.13.

Deux pipelines batch, calculés côté serveur en pur numpy (pas d'appel LLM à
grande échelle) :

- **Hidden gems** : détecte les profils sous-visibilisés mais très actifs
  (beaucoup de fragments/streak mais peu de followers).
- **Churn prediction** : score le risque qu'un talent décroche dans les
  `horizon_days` prochains jours à partir de signaux comportementaux.

Approche déterministe volontaire : reproductible, testable, cheap. Un futur
raffinement peut brancher un modèle ML (scikit-learn/XGBoost) sur les mêmes
features sans changer l'interface.
"""

from src.models.analytics import (
    ChurnPayload,
    ChurnPrediction,
    ChurnResult,
    HiddenGem,
    HiddenGemsPayload,
    HiddenGemsResult,
    TalentStats,
)
from src.utils.logging import get_logger

logger = get_logger("service.analytics_ai")


# ─── Hidden gems ─────────────────────────────────────────────────


def _hidden_gem_score(t: TalentStats) -> tuple[float, list[str]]:
    """Score [0, 1] mesurant à quel point le talent est un 'diamant caché'.

    Idée : haute activité productive vs faible visibilité sociale.
    """
    if not t.profile_active or t.days_since_signup < 14:
        return 0.0, []

    signals: list[str] = []
    score = 0.0

    # Ratio d'activité (fragments par jour)
    productivity = t.total_fragments / max(t.days_since_signup, 1)
    if productivity > 3:
        score += 0.30
        signals.append(f"productive ({productivity:.1f} fragments/jour)")
    elif productivity > 1:
        score += 0.15

    # Streak actuelle
    if t.streak_current >= 30:
        score += 0.20
        signals.append(f"streak {t.streak_current}j")
    elif t.streak_current >= 7:
        score += 0.10

    # Score moyen récent élevé
    if t.avg_score_30d >= 85:
        score += 0.20
        signals.append(f"score moyen {t.avg_score_30d:.0f}/100")
    elif t.avg_score_30d >= 70:
        score += 0.10

    # Activité soutenue
    if t.challenges_completed_30d >= 15:
        score += 0.15
        signals.append(f"{t.challenges_completed_30d} challenges/30j")
    elif t.challenges_completed_30d >= 5:
        score += 0.07

    # Pénalité si déjà bien connu (beaucoup de followers)
    if t.followers_count > 500:
        score *= 0.5
    elif t.followers_count > 100:
        score *= 0.75
    else:
        # Bonus "under-the-radar"
        if score > 0.4:
            signals.append("peu de followers")
        score = min(1.0, score * 1.1)

    return round(min(1.0, score), 4), signals


async def detect_hidden_gems(payload: HiddenGemsPayload) -> HiddenGemsResult:
    scored: list[tuple[TalentStats, float, list[str]]] = []
    for t in payload.talents:
        score, sig = _hidden_gem_score(t)
        if score >= 0.35:  # cutoff
            scored.append((t, score, sig))
    scored.sort(key=lambda x: x[1], reverse=True)
    gems = [
        HiddenGem(user_id=t.user_id, username=t.username, score=s, signals=sig)
        for t, s, sig in scored[: payload.top_n]
    ]
    logger.info(
        "hidden_gems_detected",
        evaluated=len(payload.talents),
        returned=len(gems),
    )
    return HiddenGemsResult(total_evaluated=len(payload.talents), gems=gems)


# ─── Churn prediction ────────────────────────────────────────────


def _churn_score(t: TalentStats, horizon_days: int) -> tuple[float, list[str], str]:
    """Renvoie (risk [0,1], signaux top-3, action recommandée)."""
    if not t.profile_active:
        return 1.0, ["profil désactivé"], "réactivation prioritaire"

    signals: list[tuple[str, float]] = []

    # Inactivité récente
    if t.days_since_last_activity >= horizon_days:
        signals.append((f"inactif depuis {t.days_since_last_activity}j", 0.45))
    elif t.days_since_last_activity >= max(3, horizon_days // 2):
        signals.append((f"inactif depuis {t.days_since_last_activity}j", 0.25))
    elif t.days_since_last_activity >= 2:
        signals.append(("activité en baisse", 0.08))

    # Streak cassée
    if t.streak_current == 0 and t.days_since_signup > 14:
        signals.append(("streak à 0", 0.15))
    elif t.streak_current < 3:
        signals.append(("streak fragile", 0.06))

    # Peu de challenges récents
    if t.challenges_completed_30d == 0:
        signals.append(("aucun challenge sur 30j", 0.20))
    elif t.challenges_completed_30d <= 2:
        signals.append(("faible engagement", 0.08))

    # Scores en baisse → frustration
    if 0 < t.avg_score_30d < 50:
        signals.append((f"scores faibles ({t.avg_score_30d:.0f})", 0.15))

    # Nouveaux inscrits qui décrochent
    if t.days_since_signup < 30 and t.total_fragments < 20:
        signals.append(("onboarding fragile", 0.15))

    risk = sum(w for _, w in signals)
    risk = min(1.0, risk)

    # Bandes
    if risk >= 0.75:
        band, action = "critical", "email personnalisé mentor + reward comeback"
    elif risk >= 0.5:
        band, action = "high", "drip email + challenge suggéré (easy win)"
    elif risk >= 0.25:
        band, action = "medium", "push notification + rappel streak"
    else:
        band, action = "low", "aucune action"

    # Top-3 signaux
    signals.sort(key=lambda s: s[1], reverse=True)
    top = [s for s, _ in signals[:3]]
    return round(risk, 4), top, action


async def predict_churn(payload: ChurnPayload) -> ChurnResult:
    predictions: list[ChurnPrediction] = []
    for t in payload.talents:
        risk, sig, action = _churn_score(t, payload.horizon_days)
        predictions.append(
            ChurnPrediction(
                user_id=t.user_id,
                username=t.username,
                churn_risk=risk,
                risk_band=("critical" if risk >= 0.75 else "high" if risk >= 0.5 else "medium" if risk >= 0.25 else "low"),
                top_signals=sig,
                recommended_action=action,
            )
        )
    predictions.sort(key=lambda p: p.churn_risk, reverse=True)
    logger.info("churn_predicted", evaluated=len(payload.talents))
    return ChurnResult(total_evaluated=len(payload.talents), predictions=predictions)
