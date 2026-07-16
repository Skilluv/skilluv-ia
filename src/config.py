from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration skilluv-ai chargée depuis .env et variables d'environnement."""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "skilluv-media"
    minio_secure: bool = False

    # Claude API
    anthropic_api_key: str = ""

    # gRPC
    grpc_port: int = 50051

    # FastAPI
    api_port: int = 8000

    # Logging
    log_level: str = "INFO"

    # Environment
    environment: str = "development"

    # ARQ Worker
    arq_max_jobs: int = 10
    arq_job_timeout: int = 300  # 5 minutes
    arq_max_retries: int = 3

    # Plagiarism
    plagiarism_threshold: float = 0.80
    plagiarism_ast_weight: float = 0.6
    plagiarism_embedding_weight: float = 0.4

    # Redis result TTL
    result_ttl_seconds: int = 86400  # 24h

    # === LLM provider (Claude API vs Ollama local vs autre) ===
    # Défaut : ollama pour dev en local (gratuit, souverain), à basculer sur
    # claude en prod tant qu'un GPU dédié n'est pas provisionné. Voir
    # docs/LOCAL-LLM.md pour le setup.
    llm_provider: str = "ollama"

    # Endpoint Ollama (docker-compose.dev.yml expose sur ollama:11434, local
    # dev via installateur natif = http://localhost:11434).
    ollama_endpoint: str = "http://localhost:11434"

    # Mapping tier -> modèle Ollama. Défauts adaptés à ~16 GB RAM CPU-only.
    # Voir docs/LOCAL-LLM.md pour d'autres profils (32 GB, GPU dédié, etc.).
    ollama_model_premium: str = "qwen2.5-coder:7b-instruct-q4_K_M"
    ollama_model_standard: str = "qwen2.5-coder:7b-instruct-q4_K_M"
    ollama_model_fast: str = "qwen2.5-coder:3b-instruct-q4_K_M"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
