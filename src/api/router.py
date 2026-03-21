from fastapi import FastAPI

from src.api.health import router as health_router


def create_app() -> FastAPI:
    """Crée et configure l'application FastAPI."""
    app = FastAPI(
        title="skilluv-ai",
        description="Service IA Skilluv — challenges, plagiat, matching, média",
        version="0.1.0",
        docs_url=None,  # Pas de Swagger en production (service interne)
        redoc_url=None,
    )
    app.include_router(health_router)
    return app
