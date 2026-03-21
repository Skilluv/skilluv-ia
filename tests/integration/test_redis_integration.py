"""Tests d'intégration Redis — résultats, idempotence, pub/sub."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from redis.asyncio import Redis

from src.models.job_results import JobResult


@pytest.mark.asyncio
async def test_write_and_read_result(redis_client: Redis) -> None:
    """Écrire un résultat et le relire."""
    job_id = "skilluv:test:job-001"
    result = JobResult(
        job_id=job_id,
        status="completed",
        result={"flagged": False, "score": 0.42},
        duration_ms=150,
        completed_at=datetime.now(UTC),
    )

    # Écrire
    await redis_client.set(
        f"skilluv:test:result:{job_id}",
        result.model_dump_json(),
        ex=60,
    )

    # Relire
    data = await redis_client.get(f"skilluv:test:result:{job_id}")
    assert data is not None
    loaded = JobResult.model_validate_json(data)
    assert loaded.job_id == job_id
    assert loaded.status == "completed"
    assert loaded.result["flagged"] is False


@pytest.mark.asyncio
async def test_idempotence_check(redis_client: Redis) -> None:
    """Vérifier qu'un job déjà traité est détecté."""
    job_id = "skilluv:test:job-002"
    key = f"skilluv:test:result:{job_id}"

    # Pas encore traité
    exists = await redis_client.exists(key)
    assert exists == 0

    # Traiter
    await redis_client.set(key, '{"status": "completed"}', ex=60)

    # Déjà traité
    exists = await redis_client.exists(key)
    assert exists == 1


@pytest.mark.asyncio
async def test_pubsub_notification(redis_client: Redis) -> None:
    """Publier et recevoir une notification via Pub/Sub."""
    channel = "skilluv:test:notifications"

    # Souscrire
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)

    # Attendre le message de souscription
    msg = await pubsub.get_message(timeout=1)

    # Publier
    notification = json.dumps({
        "job_id": "test-003",
        "job_type": "plagiarism_check",
        "status": "completed",
    })
    await redis_client.publish(channel, notification)

    # Recevoir
    msg = await pubsub.get_message(timeout=2)
    assert msg is not None
    assert msg["type"] == "message"
    data = json.loads(msg["data"])
    assert data["job_id"] == "test-003"
    assert data["status"] == "completed"

    await pubsub.unsubscribe(channel)
    await pubsub.aclose()


@pytest.mark.asyncio
async def test_result_ttl(redis_client: Redis) -> None:
    """Vérifier que le TTL est bien appliqué."""
    key = "skilluv:test:result:ttl-test"
    await redis_client.set(key, "data", ex=2)

    ttl = await redis_client.ttl(key)
    assert 0 < ttl <= 2

    # Attendre l'expiration
    await asyncio.sleep(3)
    exists = await redis_client.exists(key)
    assert exists == 0
