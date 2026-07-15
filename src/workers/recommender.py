"""Worker recommandations — consomme skilluv:queue:recommendations — Phase 5.5."""

import time
from datetime import UTC, datetime

from src.exceptions import SkilluvAIError
from src.models.job_results import JobResult
from src.models.queue_messages import QueueMessage
from src.models.recommendations import RecommendationPayload
from src.utils.logging import get_logger
from src.utils.metrics import jobs_duration_seconds, jobs_in_progress, jobs_total
from src.utils.redis_client import job_already_processed, publish_notification, write_result

logger = get_logger("worker.recommender")


async def process_recommendation_job(ctx: dict, raw_message: dict) -> None:
    message = QueueMessage.model_validate(raw_message)
    job_id = message.job_id
    job_type = "recommendation"

    if await job_already_processed(job_id):
        return

    jobs_in_progress.labels(job_type=job_type).inc()
    start = time.monotonic()
    try:
        payload = RecommendationPayload.model_validate(message.payload)
        from src.services.recommender import recommend_challenges

        result_data = await recommend_challenges(payload)
        duration_ms = int((time.monotonic() - start) * 1000)

        await write_result(
            job_id,
            JobResult(
                job_id=job_id,
                status="completed",
                result=result_data.model_dump(),
                duration_ms=duration_ms,
                completed_at=datetime.now(UTC),
            ),
        )
        await publish_notification(
            job_id,
            job_type,
            "completed",
            {"user_id": payload.user.user_id, "count": len(result_data.recommendations)},
        )
        jobs_total.labels(job_type=job_type, status="completed").inc()
        jobs_duration_seconds.labels(job_type=job_type).observe(duration_ms / 1000)
    except SkilluvAIError as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        await write_result(
            job_id,
            JobResult(
                job_id=job_id,
                status="failed",
                error=f"{type(e).__name__}: {e.message}",
                duration_ms=duration_ms,
                completed_at=datetime.now(UTC),
            ),
        )
        await publish_notification(job_id, job_type, "failed", {"error": e.message})
        jobs_total.labels(job_type=job_type, status="failed").inc()
        logger.error("job_failed", job_id=job_id, error=e.message)
    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        await write_result(
            job_id,
            JobResult(
                job_id=job_id,
                status="failed",
                error=f"Unexpected: {e!s}",
                duration_ms=duration_ms,
                completed_at=datetime.now(UTC),
            ),
        )
        await publish_notification(job_id, job_type, "failed", {"error": str(e)})
        jobs_total.labels(job_type=job_type, status="failed").inc()
        logger.error("job_unexpected_error", job_id=job_id, error=str(e))
    finally:
        jobs_in_progress.labels(job_type=job_type).dec()
