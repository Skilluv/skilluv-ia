import json
from datetime import UTC, datetime

from redis.asyncio import Redis

from src.config import settings
from src.models.job_results import JobResult
from src.utils.logging import get_logger

logger = get_logger("redis_client")

_redis: Redis | None = None


async def get_redis() -> Redis:
    """Retourne la connexion Redis (singleton)."""
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Ferme la connexion Redis."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def write_result(job_id: str, result: JobResult) -> None:
    """Écrit un résultat de job dans Redis avec TTL."""
    redis = await get_redis()
    key = f"skilluv:result:{job_id}"
    await redis.set(key, result.model_dump_json(), ex=settings.result_ttl_seconds)
    logger.info("result_written", job_id=job_id, status=result.status)


async def read_result(job_id: str) -> JobResult | None:
    """Lit un résultat de job depuis Redis."""
    redis = await get_redis()
    key = f"skilluv:result:{job_id}"
    data = await redis.get(key)
    if data is None:
        return None
    return JobResult.model_validate_json(data)


async def job_already_processed(job_id: str) -> bool:
    """Vérifie si un job a déjà été traité (idempotence)."""
    redis = await get_redis()
    key = f"skilluv:result:{job_id}"
    return await redis.exists(key) > 0


async def publish_notification(job_id: str, job_type: str, status: str, summary: dict) -> None:
    """Publie une notification sur le channel Pub/Sub pour le backend Rust."""
    redis = await get_redis()
    notification = json.dumps({
        "job_id": job_id,
        "job_type": job_type,
        "status": status,
        "summary": summary,
        "completed_at": datetime.now(UTC).isoformat(),
    })
    await redis.publish("skilluv:notifications", notification)
    logger.info("notification_published", job_id=job_id, job_type=job_type, status=status)
