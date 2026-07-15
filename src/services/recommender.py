"""Recommandations personnalisées de challenges — Phase 5.5.

Approche hybride :
1. Filtrage préalable côté serveur (déjà fait dans le payload : `candidates`)
2. Scoring pondéré déterministe : domaine + gap de sub-skills + difficulté adaptative
3. Bonus IA : Claude Haiku analyse le top-K et écrit une justification pédagogique

On utilise Haiku 4.5 ici (pas Opus) car c'est un scoring léger — cheap + rapide.
"""

import json

import anthropic

from src.config import settings
from src.exceptions import ExternalServiceError
from src.models.recommendations import (
    CandidateChallenge,
    ChallengeRecommendation,
    RecommendationPayload,
    RecommendationResult,
    UserProfileSnapshot,
)
from src.utils.logging import get_logger
from src.utils.metrics import external_errors_total

logger = get_logger("service.recommender")

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


_TITLE_LEVEL = {"Apprenti": 1, "Artisan": 2, "Maître": 3, "Légende": 4}


def _difficulty_target(user: UserProfileSnapshot) -> tuple[int, int]:
    """Retourne (min, max) de difficulté idéale pour l'utilisateur."""
    level = _TITLE_LEVEL.get(user.title, 1)
    # Difficulté ~= niveau, avec une fenêtre +/- 1 pour permettre consolidation & stretch.
    return max(1, level - 1), min(5, level + 1)


def _base_score(user: UserProfileSnapshot, cand: CandidateChallenge) -> tuple[float, str]:
    """Score déterministe [0, 1] + growth_category déduite."""
    score = 0.0

    # Éviter déjà fait
    if cand.challenge_id in user.recently_completed_challenge_ids:
        return 0.0, "already_done"

    # Domaine matché
    if cand.skill_domain == user.skill_domain:
        score += 0.35

    # Difficulté dans la fenêtre
    dmin, dmax = _difficulty_target(user)
    if dmin <= cand.difficulty <= dmax:
        score += 0.25
        if cand.difficulty > _TITLE_LEVEL.get(user.title, 1):
            growth = "stretch"
        elif cand.difficulty == _TITLE_LEVEL.get(user.title, 1):
            growth = "growth"
        else:
            growth = "consolidation"
    else:
        growth = "growth"
        score += 0.05

    # Sub-skills gap : bonus si le challenge cible une zone de faiblesse déclarée
    weak_hit = sum(1 for s in cand.sub_skills if s in user.weak_areas)
    if weak_hit:
        score += min(0.2, 0.1 * weak_hit)

    # Sub-skills alignement avec les forces de l'utilisateur (bonus modeste)
    strength_hit = sum(1 for s in cand.sub_skills if s in user.top_sub_skills)
    if strength_hit:
        score += min(0.1, 0.05 * strength_hit)

    # Popularité — anti-obscurité (permet aux challenges éprouvés d'émerger)
    if cand.completion_count > 50:
        score += 0.05
    if cand.completion_count > 500:
        score += 0.05

    return min(1.0, score), growth


async def recommend_challenges(payload: RecommendationPayload) -> RecommendationResult:
    """Retourne les top-N recommandations personnalisées."""
    logger.info(
        "recommendation_started",
        user_id=payload.user.user_id,
        candidates_count=len(payload.candidates),
    )

    # Phase 1 : score déterministe
    scored: list[tuple[CandidateChallenge, float, str]] = []
    for cand in payload.candidates:
        s, growth = _base_score(payload.user, cand)
        if s > 0:
            scored.append((cand, s, growth))
    scored.sort(key=lambda t: t[1], reverse=True)

    # Phase 2 : ne garder que le top-K pour l'appel Claude (économie de tokens)
    top_k = scored[: max(payload.top_n, 8)]

    if not top_k:
        return RecommendationResult(user_id=payload.user.user_id, recommendations=[])

    # Phase 3 : demander à Claude Haiku de justifier chaque recommandation
    reasons = await _generate_reasons(payload.user, top_k)

    recos = [
        ChallengeRecommendation(
            challenge_id=cand.challenge_id,
            score=round(score, 4),
            reason=reasons.get(cand.challenge_id, ""),
            growth_category=growth,
        )
        for cand, score, growth in top_k[: payload.top_n]
    ]

    logger.info(
        "recommendation_completed",
        user_id=payload.user.user_id,
        returned=len(recos),
    )
    return RecommendationResult(user_id=payload.user.user_id, recommendations=recos)


_REASONS_SCHEMA = {
    "type": "object",
    "properties": {
        "reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "challenge_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["challenge_id", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["reasons"],
    "additionalProperties": False,
}


async def _generate_reasons(
    user: UserProfileSnapshot,
    top_k: list[tuple[CandidateChallenge, float, str]],
) -> dict[str, str]:
    """Utilise Haiku pour générer une justification par challenge."""
    challenges_json = [
        {
            "id": c.challenge_id,
            "title": c.title,
            "skill_domain": c.skill_domain,
            "sub_skills": c.sub_skills,
            "difficulty": c.difficulty,
            "growth_category": growth,
        }
        for c, _, growth in top_k
    ]
    system = (
        "Tu es un mentor Skilluv. Pour chaque challenge recommandé, écris une "
        "raison courte (1-2 phrases, tutoiement, français) expliquant pourquoi "
        "il est pertinent pour cet utilisateur. Sois concret : mentionne un "
        "sub_skill, un lien avec son niveau, ou un axe de progression."
    )
    user_msg = json.dumps(
        {
            "user": {
                "title": user.title,
                "skill_domain": user.skill_domain,
                "top_sub_skills": user.top_sub_skills,
                "weak_areas": user.weak_areas,
                "streak_current": user.streak_current,
            },
            "challenges": challenges_json,
        },
        ensure_ascii=False,
    )
    client = _get_client()
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=2000,
            output_config={"format": {"type": "json_schema", "schema": _REASONS_SCHEMA}},
            system=system,
            messages=[{"role": "user", "content": user_msg}],
        )
    except anthropic.APIError as e:
        external_errors_total.labels(service="claude_api").inc()
        # Non-fatal : on renvoie des raisons vides plutôt que de faire tomber le job.
        logger.warning("recommendation_reasons_failed", error=str(e))
        return {}

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return {r["challenge_id"]: r["reason"] for r in data.get("reasons", [])}
