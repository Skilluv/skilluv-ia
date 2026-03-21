FROM python:3.12-slim AS base

# ffmpeg pour le traitement média
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# uv pour la gestion des dépendances
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dépendances d'abord (cache Docker)
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml

# Code source
COPY proto/ proto/
COPY src/ src/

EXPOSE 8000 50051

CMD ["python", "-m", "src.main"]
