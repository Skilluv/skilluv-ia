"""Cache Redis pour AnalyzePerformance (économie coûts Claude).

Décision : cache par signature du snapshot (user_id + hash du contenu). Un user
qui rappelle la route sans avoir bougé ses skills/deliverables réutilise la
réponse Sonnet 4.6 → économie ~$0.02/hit.

TTL 1h : suffisant pour absorber les burst de F5 côté frontend sans risquer
que le verdict devienne périmé (un user actif fait de nouvelles submissions
en < 1h de session).

Non caché : SuggestCareerPath (Haiku, $0.005/appel, ROI marginal). CodeReview
et ChallengeGeneration ont leurs propres caches ailleurs.
"""

from __future__ import annotations

import hashlib
import json

from src.models.talent_analysis import (
    AnalyzePerformancePayload,
    AnalyzePerformanceResult,
)
from src.utils.logging import get_logger
from src.utils.redis_client import get_redis

logger = get_logger("service.talent_cache")

_CACHE_PREFIX = "skilluv:cache:analyze_performance"
_CACHE_TTL_SECONDS = 3600  # 1h


def _build_cache_key(payload: AnalyzePerformancePayload) -> str:
    """Clé déterministe = hash du snapshot user + user_id.

    On sort deliverables/skills/orientations pour garantir une clé stable
    quelque soit l'ordre côté backend. Le rank est inclus (change le prompt).
    """
    signature = {
        "user_id": payload.user_id,
        "current_rank": payload.current_rank,
        # deliverables : liste triée par (skill_slug, deliverable_id) pour stabilité
        "deliverables": sorted(
            [d.model_dump() for d in payload.deliverables],
            key=lambda d: (d["skill_slug"], d["deliverable_id"]),
        ),
        "skills": sorted(
            [s.model_dump() for s in payload.skills],
            key=lambda s: s["skill_slug"],
        ),
        "orientations": sorted(
            [o.model_dump() for o in payload.orientations],
            key=lambda o: o["orientation_slug"],
        ),
    }
    raw = json.dumps(signature, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{_CACHE_PREFIX}:{payload.user_id}:{digest}"


async def get_cached_analysis(
    payload: AnalyzePerformancePayload,
) -> AnalyzePerformanceResult | None:
    """Récupère un résultat en cache. None si absent ou erreur Redis (fail-open)."""
    try:
        redis = await get_redis()
        key = _build_cache_key(payload)
        data = await redis.get(key)
        if data is None:
            return None
        result = AnalyzePerformanceResult.model_validate_json(data)
        logger.info(
            "analyze_performance_cache_hit",
            user_id=payload.user_id,
            key_suffix=key.split(":")[-1],
        )
        return result
    except Exception as e:
        logger.warning("analyze_performance_cache_read_error", error=str(e))
        return None


async def cache_analysis(
    payload: AnalyzePerformancePayload,
    result: AnalyzePerformanceResult,
) -> None:
    """Persiste un résultat. Fail-open si Redis down."""
    try:
        redis = await get_redis()
        key = _build_cache_key(payload)
        await redis.set(key, result.model_dump_json(), ex=_CACHE_TTL_SECONDS)
        logger.info(
            "analyze_performance_cached",
            user_id=payload.user_id,
            ttl_seconds=_CACHE_TTL_SECONDS,
        )
    except Exception as e:
        logger.warning("analyze_performance_cache_write_error", error=str(e))
