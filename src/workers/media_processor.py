"""Worker de traitement média — consomme skilluv:queue:media."""

from datetime import UTC, datetime
import time

from src.exceptions import SkilluvAIError
from src.models.job_results import JobResult
from src.models.queue_messages import ClipPayload, QueueMessage, ReplayPayload
from src.utils.logging import get_logger
from src.utils.metrics import jobs_duration_seconds, jobs_in_progress, jobs_total
from src.utils.redis_client import job_already_processed, publish_notification, write_result

logger = get_logger("worker.media_processor")


async def process_media_job(ctx: dict, raw_message: dict) -> None:
    """Traite un job de traitement média (replay ou clip)."""
    message = QueueMessage.model_validate(raw_message)
    job_id = message.job_id
    job_type = message.job_type  # "replay_generate" ou "clip_generate"

    if await job_already_processed(job_id):
        logger.info("job_skipped_already_processed", job_id=job_id)
        return

    jobs_in_progress.labels(job_type=job_type).inc()
    start = time.monotonic()

    try:
        logger.info("job_started", job_id=job_id, job_type=job_type)

        from src.services.media_processor import generate_clip, generate_replay

        if job_type == "replay_generate":
            payload = ReplayPayload.model_validate(message.payload)
            result_data = await generate_replay(payload)
        elif job_type == "clip_generate":
            payload = ClipPayload.model_validate(message.payload)
            result_data = await generate_clip(payload)
        else:
            raise ValueError(f"Unknown media job_type: {job_type}")

        duration_ms = int((time.monotonic() - start) * 1000)

        result = JobResult(
            job_id=job_id,
            status="completed",
            result=result_data.model_dump(),
            duration_ms=duration_ms,
            completed_at=datetime.now(UTC),
        )
        await write_result(job_id, result)
        await publish_notification(job_id, job_type, "completed", {
            "submission_id": result_data.submission_id,
            "minio_key": result_data.minio_key,
        })

        jobs_total.labels(job_type=job_type, status="completed").inc()
        jobs_duration_seconds.labels(job_type=job_type).observe(duration_ms / 1000)
        logger.info("job_completed", job_id=job_id, duration_ms=duration_ms)

    except SkilluvAIError as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        result = JobResult(
            job_id=job_id,
            status="failed",
            error=f"{type(e).__name__}: {e.message}",
            duration_ms=duration_ms,
            completed_at=datetime.now(UTC),
        )
        await write_result(job_id, result)
        await publish_notification(job_id, job_type, "failed", {"error": e.message})
        jobs_total.labels(job_type=job_type, status="failed").inc()
        logger.error("job_failed", job_id=job_id, error=e.message, duration_ms=duration_ms)

    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        result = JobResult(
            job_id=job_id,
            status="failed",
            error=f"Unexpected: {e!s}",
            duration_ms=duration_ms,
            completed_at=datetime.now(UTC),
        )
        await write_result(job_id, result)
        await publish_notification(job_id, job_type, "failed", {"error": str(e)})
        jobs_total.labels(job_type=job_type, status="failed").inc()
        logger.error("job_unexpected_error", job_id=job_id, error=str(e), duration_ms=duration_ms)

    finally:
        jobs_in_progress.labels(job_type=job_type).dec()
