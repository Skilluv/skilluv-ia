"""Cache des challenges générés dans Redis.

Évite de re-appeler Claude API pour des paramètres similaires.
La clé de cache est un hash des paramètres de génération.

Stratégie :
- Clé : skilluv:cache:challenge:{hash_params}
- TTL : configurable (défaut 7 jours)
- Le cache est optionnel : si Redis échoue, on génère normalement
- Les challenges en mode "absurd" ne sont jamais cachés (on veut de la variété)
"""

import hashlib
import json

from src.config import settings
from src.models.challenge import ChallengeParams, GeneratedChallenge
from src.utils.logging import get_logger
from src.utils.redis_client import get_redis

logger = get_logger("challenge_cache")

CACHE_TTL_SECONDS = 7 * 24 * 3600  # 7 jours
CACHE_PREFIX = "skilluv:cache:challenge"


def _build_cache_key(params: ChallengeParams) -> str:
    """Construit une clé de cache déterministe à partir des paramètres."""
    key_data = {
        "domain": params.skill_domain,
        "difficulty": params.difficulty,
        "duration": params.duration_minutes,
        "mode": params.mode,
        "tone": params.tone,
        "ai_allowed": params.ai_allowed,
        "language": params.language,
        "programming_language": params.programming_language or "",
        "tags": sorted(params.tags),
        # Champs v2 : sinon collision entre challenges de même params mais
        # d'orientation ou mode training différents.
        "orientation_slug": params.orientation_slug,
        "is_training": params.is_training,
        "project_id": params.project_id,
    }
    raw = json.dumps(key_data, sort_keys=True)
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"{CACHE_PREFIX}:{digest}"


def _is_cacheable(params: ChallengeParams) -> bool:
    """Détermine si un challenge peut être mis en cache.

    Les challenges absurdes ne sont pas cachés pour garantir la variété.
    """
    return params.tone != "absurd"


async def get_cached_challenge(params: ChallengeParams) -> GeneratedChallenge | None:
    """Cherche un challenge en cache. Retourne None si absent ou erreur."""
    if not _is_cacheable(params):
        return None

    try:
        redis = await get_redis()
        key = _build_cache_key(params)
        data = await redis.get(key)

        if data is None:
            return None

        challenge = GeneratedChallenge.model_validate_json(data)
        logger.info("cache_hit", key=key, title=challenge.title)
        return challenge

    except Exception as e:
        logger.warning("cache_read_error", error=str(e))
        return None


async def cache_challenge(params: ChallengeParams, challenge: GeneratedChallenge) -> None:
    """Met un challenge en cache."""
    if not _is_cacheable(params):
        return

    try:
        redis = await get_redis()
        key = _build_cache_key(params)
        await redis.set(key, challenge.model_dump_json(), ex=CACHE_TTL_SECONDS)
        logger.info("cache_stored", key=key, title=challenge.title)

    except Exception as e:
        logger.warning("cache_write_error", error=str(e))


async def invalidate_cache(params: ChallengeParams) -> None:
    """Invalide le cache pour des paramètres donnés."""
    try:
        redis = await get_redis()
        key = _build_cache_key(params)
        await redis.delete(key)
        logger.info("cache_invalidated", key=key)

    except Exception as e:
        logger.warning("cache_invalidate_error", error=str(e))


async def get_cache_stats() -> dict:
    """Retourne des stats sur le cache (nombre d'entrées, mémoire)."""
    try:
        redis = await get_redis()
        keys = []
        async for key in redis.scan_iter(match=f"{CACHE_PREFIX}:*", count=100):
            keys.append(key)
        return {"cached_challenges": len(keys)}

    except Exception:
        return {"cached_challenges": -1}
