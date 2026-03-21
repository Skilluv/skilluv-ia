from fastapi import APIRouter
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest
from redis.asyncio import Redis
from starlette.responses import Response

from src.config import settings

router = APIRouter()


@router.get("/health")
async def health_check() -> JSONResponse:
    """Health check — vérifie Redis et retourne le statut des services."""
    checks: dict[str, str] = {}

    # Redis
    try:
        redis = Redis.from_url(settings.redis_url, decode_responses=True)
        await redis.ping()
        await redis.aclose()
        checks["redis"] = "healthy"
    except Exception:
        checks["redis"] = "unhealthy"

    all_healthy = all(v == "healthy" for v in checks.values())

    return JSONResponse(
        status_code=200 if all_healthy else 503,
        content={
            "status": "healthy" if all_healthy else "degraded",
            "services": checks,
            "version": "0.1.0",
            "environment": settings.environment,
        },
    )


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    """Endpoint Prometheus /metrics."""
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
