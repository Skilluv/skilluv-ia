from pydantic import Field
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

    # === Mode mock LLM (bench, CI, tests intégration sans coût) ===
    # SKILLUV_AI_MOCK_CLAUDE=1 → factory renvoie un `MockProvider` déterministe
    # qui satisfait le JSON schema demandé sans appel réseau. Utile pour :
    #  - load tests `ghz` (mesurer overhead gRPC pur sans facture Claude)
    #  - CI (pas de fuite d'API key requise)
    #  - tests intégration end-to-end
    # PRIORITAIRE sur `llm_provider` — si mock=1, ni Claude ni Ollama ne sont
    # appelés. Voir src/llm/mock_provider.py.
    mock_llm: bool = Field(default=False, alias="SKILLUV_AI_MOCK_CLAUDE")

    # Endpoint Ollama (docker-compose.dev.yml expose sur ollama:11434, local
    # dev via installateur natif = http://localhost:11434).
    ollama_endpoint: str = "http://localhost:11434"

    # Mapping tier -> modèle Ollama. Défauts adaptés à ~16 GB RAM CPU-only.
    # Voir docs/LOCAL-LLM.md pour d'autres profils (32 GB, GPU dédié, etc.).
    #
    # NB : les 3 tiers pointent volontairement sur le même modèle 7B. Le 3B a
    # été testé et échoue de façon reproductible sur les schémas nested
    # (typiquement `suggest_career_path` — voir tests/integration/
    # test_services_llm_live.py). Un seul modèle à pull en prod, latence
    # uniforme, pas de surprise. Pour ré-introduire un modèle plus petit sur
    # le tier FAST, valider d'abord contre les vrais schémas des 3 services.
    ollama_model_premium: str = "qwen2.5-coder:7b-instruct-q4_K_M"
    ollama_model_standard: str = "qwen2.5-coder:7b-instruct-q4_K_M"
    ollama_model_fast: str = "qwen2.5-coder:7b-instruct-q4_K_M"

    # Nombre max de retries si Ollama produit un JSON invalide / non conforme
    # au schema. Ollama < Claude sur le structured output — un budget de 2
    # retries (soit 3 tentatives) est le sweet spot mesuré avec Qwen 7B sur
    # les schémas de challenge_generation (~10 champs).
    ollama_max_retries: int = 2

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
    }


settings = Settings()
