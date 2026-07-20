# Changelog

All notable changes to the Skilluv AI microservice are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project will adopt semantic versioning once 1.0 is reached.

## [Unreleased]

### Added

- **Provider abstraction (Ollama / Claude)** — `src/llm/` layer with
  `LLMProvider` protocol, `ModelTier` enum (PREMIUM/STANDARD/FAST),
  `ClaudeProvider` and `OllamaProvider` implementations, and a singleton
  factory selected via `SKILLUV_AI_LLM_PROVIDER`. Ollama is the default
  for local development (no API key, no cost); Claude is the production
  path. All services (`talent_analyzer`, `code_reviewer`,
  `challenge_generator`) target a tier, not a specific model — swap
  provider without touching business code. `challenge_generator` now
  emits a JSON schema, eliminating fragile text-based JSON extraction.
- **Mock LLM provider** — `SKILLUV_AI_MOCK_CLAUDE=1` env flag activates
  `MockProvider`, which synthesizes a deterministic JSON matching the
  requested schema. Priority over `llm_provider`. Zero network calls,
  zero API cost — safe for load tests (`ghz`), CI, and integration
  suites.
- **Redis integration tests suite** — `tests/integration/test_redis_services_integration.py`
  (10 tests) exercises `_challenge_cache`, `_talent_cache` and the
  `get_redis` singleton against a real Docker Redis, covering the
  v2-fields hash key regression, absurd-tone skip, invalidate,
  cache-stats scoping, TTL, and pub/sub round-trip.

### Changed

- **Orientations catalog synced to 31 slugs** — `src/data/orientations_catalog.json`
  now mirrors the 31 curated orientations from
  `skilluv-backend/migrations/0088`. `_meta.version` bumped to `1.0.0`,
  `_meta.todo` removed. All slugs are byte-aligned with the backend so
  `SuggestCareerPath` responses map 1:1.
- **Ruff clean pass** — zero warnings, zero errors. Introduces
  `per-file-ignores` for legitimate cases: `N802` on `*_servicer.py`
  (gRPC methods must stay PascalCase to match the .proto),
  `E501` on prompt files and Pydantic models with long `Field(description=...)`.
- **Dev tooling comments** — `.gitignore` and `.dockerignore` refer to
  "AI coding assistant caches" instead of naming a specific vendor.

### Removed

- **`proto/challenge.proto` v1 (legacy)** — deleted along with
  `src/grpc_server/challenge_servicer.py`, generated stubs
  (`challenge_pb2*.py`), the manual-handler fallback in `server.py`,
  and the compilation step in `scripts/generate_proto.sh`. The
  backend migrated to `skilluv.ai.v2` since IA-A, zero call warnings
  detected in prod, so the v1 codepath is retired.
- **`src/grpc_server/_manual_handler.py`** — obsolete since
  `generate_proto.sh` runs systematically; if stubs are missing the
  server now fails fast with a clear "run generate_proto.sh" hint.

### Fixed

- **Cache key regression #31** — `_challenge_cache._build_cache_key`
  now includes `orientation_slug`, `is_training`, and `project_id`
  in the SHA-256 signature, preventing collisions between challenges
  that share domain/difficulty/duration but differ on v2 fields.

## [0.2.0] — 2026-07 (bench + polish)

### Added

- **Rate-limiting per caller** — `src/grpc_server/_rate_limit.py` (11 tests).
- **gRPC health check** — `grpc.health.v1` conformant, usable by Docker
  HEALTHCHECK and Kubernetes liveness probes.
- **Alertmanager wiring** — `infra/alertmanager/`, activated via the
  `alerting` docker-compose profile.
- **Load test harness** — `bench/` with 3 `ghz` fixtures + README.
- **CI strict** — `continue-on-error` removed on pytest.
- **Orientations catalog draft** — 22 orientations (later expanded
  to 31 in the current release).
- **v2 prompt enrichment** — `orientation_slug`, `is_training`,
  `project_id` are now consumed by the challenge generation prompts.
- **`AnalyzePerformance` Redis cache** — snapshot-hash keyed, ~$0.02
  saved per hit.

## [0.1.0] — 2026-07 (MVP delivery)

### Added

- **gRPC v2 contract** — 4 services (`CodeReview`,
  `ChallengeGeneration`, `TalentDetection`, `Plagiarism`) exposed on
  `skilluv.ai.v2` with 6 RPC methods (`ReviewCode`,
  `GenerateChallenge`, `GenerateVariant`, `AnalyzePerformance`,
  `SuggestCareerPath`, `CheckPlagiarism`).
- **Prod deployment scaffolding** — Dockerfile, compose profiles
  (default/monitoring/scaled), Prometheus scrape config, Grafana
  dashboard, Hetzner deployment doc.
- **AI capabilities** — challenge generation with dynamic difficulty,
  plagiarism detection (tree-sitter AST + SentenceTransformers
  embeddings), talent matching with semantic similarity + hard
  filters, visual replay frames renderer, media processor
  (ffmpeg-python + MinIO).
- **Data plane** — Redis for job queues + result cache + pub/sub, MinIO
  for artifact storage, structured logging with `structlog`.

### OSS baseline

- AGPL-3.0 LICENSE, SECURITY, CONTRIBUTING, CODE_OF_CONDUCT.
- Bilingual README (EN primary, FR at `README.fr.md`).
- GitHub issue / PR templates, CI workflow.
