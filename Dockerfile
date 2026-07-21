# syntax=docker/dockerfile:1.7
# =========================================================================
# skilluv-ai — image de production
#
# Multi-stage :
#   1) builder — installe les dépendances Python via uv dans un venv figé
#   2) runtime — image slim, utilisateur non-root, healthcheck gRPC
#
# Labels OCI standards + build args pour tag/version reproductible.
# =========================================================================

ARG PYTHON_VERSION=3.12

# -------------------------------------------------------------------------
# 1) Builder
# -------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

# Dépendances de build (ffmpeg est nécessaire au runtime, pas ici)
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
    && rm -rf /var/lib/apt/lists/*

# uv (astral) — pin explicite pour reproductibilité
COPY --from=ghcr.io/astral-sh/uv:0.11.30 /uv /usr/local/bin/uv

WORKDIR /app

# Installation deps dans un venv figé (isolé du site-packages système).
# `uv sync --frozen` respecte uv.lock strictement -> build reproductible.
COPY pyproject.toml uv.lock ./
RUN uv venv /opt/venv && \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    uv sync --frozen --no-dev --no-install-project

# grpc_health_probe : binaire officiel pour Docker/K8s healthcheck
ARG GRPC_HEALTH_PROBE_VERSION=v0.4.28
RUN curl -sSL -o /usr/local/bin/grpc_health_probe \
      "https://github.com/grpc-ecosystem/grpc-health-probe/releases/download/${GRPC_HEALTH_PROBE_VERSION}/grpc_health_probe-linux-amd64" && \
    chmod +x /usr/local/bin/grpc_health_probe

# -------------------------------------------------------------------------
# 2) Runtime
# -------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=0.1.0-mvp

LABEL org.opencontainers.image.title="skilluv-ai" \
      org.opencontainers.image.description="Skilluv AI microservice (gRPC v2 + workers)" \
      org.opencontainers.image.source="https://github.com/skilluv/skilluv-ia" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}"

# ffmpeg pour media processor (workers)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --home-dir /home/skilluv --shell /bin/bash --uid 10001 skilluv

# Venv depuis le builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /usr/local/bin/grpc_health_probe /usr/local/bin/grpc_health_probe
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --chown=skilluv:skilluv proto/ proto/
COPY --chown=skilluv:skilluv src/ src/

USER skilluv

EXPOSE 8000 50051

# Healthcheck standard grpc.health.v1 — tolérant au cold start du modèle
# d'embeddings (~30s), donc start-period=60s.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD /usr/local/bin/grpc_health_probe -addr=127.0.0.1:50051 || exit 1

CMD ["python", "-m", "src.main"]
