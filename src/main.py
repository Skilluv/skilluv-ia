import asyncio

import uvicorn

from src.api.router import create_app
from src.config import settings
from src.storage.minio_client import ensure_bucket
from src.utils.logging import get_logger, setup_logging
from src.utils.redis_client import close_redis

logger = get_logger("main")


async def start_fastapi() -> None:
    """Démarre le serveur FastAPI."""
    app = create_app()
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    await server.serve()


async def start_grpc() -> None:
    """Démarre le serveur gRPC."""
    from src.grpc_server.server import serve

    await serve()


async def start_worker() -> None:
    """Démarre le worker ARQ."""
    from arq import run_worker

    from src.workers.settings import get_redis_settings

    # Import dynamique pour enregistrer les fonctions worker
    from src.workers import plagiarism, talent_matcher, media_processor  # noqa: F401

    run_worker(
        {
            "functions": [
                plagiarism.process_plagiarism_job,
                talent_matcher.process_talent_match_job,
                media_processor.process_media_job,
            ],
            "redis_settings": get_redis_settings(),
            "max_jobs": settings.arq_max_jobs,
            "job_timeout": settings.arq_job_timeout,
        }
    )


async def main() -> None:
    """Point d'entrée : lance FastAPI + gRPC + ARQ worker dans le même event loop."""
    setup_logging()
    logger.info(
        "starting_skilluv_ai",
        environment=settings.environment,
        api_port=settings.api_port,
        grpc_port=settings.grpc_port,
    )

    # Initialisation MinIO bucket
    ensure_bucket()

    try:
        # Lance les 3 process en parallèle dans le même event loop
        await asyncio.gather(
            start_fastapi(),
            start_grpc(),
            start_worker(),
        )
    finally:
        await close_redis()
        logger.info("skilluv_ai_stopped")


if __name__ == "__main__":
    asyncio.run(main())
