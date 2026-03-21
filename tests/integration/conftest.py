"""Fixtures pour les tests d'intégration.

Ces tests nécessitent Redis et MinIO en local :
    docker compose up -d redis minio

Lancer uniquement les tests d'intégration :
    uv run pytest tests/integration/ -v
"""

import os

import pytest
import pytest_asyncio
from redis.asyncio import Redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")


def _redis_available() -> bool:
    """Vérifie si Redis est accessible."""
    import asyncio

    async def _check():
        try:
            r = Redis.from_url(REDIS_URL, decode_responses=True)
            await r.ping()
            await r.aclose()
            return True
        except Exception:
            return False

    return asyncio.get_event_loop().run_until_complete(_check()) if asyncio.get_event_loop().is_running() else False


def _minio_available() -> bool:
    """Vérifie si MinIO est accessible."""
    try:
        from minio import Minio

        client = Minio(
            endpoint=MINIO_ENDPOINT,
            access_key="minioadmin",
            secret_key="minioadmin",
            secure=False,
        )
        client.list_buckets()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="SKIP_INTEGRATION=1",
)

requires_minio = pytest.mark.skipif(
    os.environ.get("SKIP_INTEGRATION") == "1",
    reason="SKIP_INTEGRATION=1",
)


@pytest_asyncio.fixture
async def redis_client():
    """Client Redis pour les tests d'intégration."""
    client = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except Exception:
        pytest.skip("Redis not available")
    yield client
    # Nettoyer les clés de test
    keys = await client.keys("skilluv:test:*")
    if keys:
        await client.delete(*keys)
    await client.aclose()


@pytest.fixture
def minio_client():
    """Client MinIO pour les tests d'intégration."""
    try:
        from minio import Minio

        client = Minio(
            endpoint=MINIO_ENDPOINT,
            access_key="minioadmin",
            secret_key="minioadmin",
            secure=False,
        )
        client.list_buckets()
    except Exception:
        pytest.skip("MinIO not available")
    return client
