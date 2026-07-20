# Skilluv AI Service

> **Internal AI microservice powering Skilluv's challenge generation, plagiarism detection, talent matching, and media processing.**

> 🇬🇧 English (this page) · 🇫🇷 [Version française](README.fr.md)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![gRPC](https://img.shields.io/badge/gRPC-server-4285f4.svg)](https://grpc.io/)

---

## What is Skilluv?

Skilluv is a community platform training the African OSS generation through real contributions to real open source projects. Every completed challenge produces a verifiable artifact exportable to recruiters. **Talents never pay for access — companies do.**

Full product vision in the [backend repository](https://github.com/skilluv/skilluv-backend).

## What this repo contains

The **AI microservice** of Skilluv. Written in **Python 3.12**, packaged with **uv**. It communicates with the Rust backend via **gRPC** (synchronous calls) and **Redis Queue** (asynchronous jobs). **This service exposes no public HTTP routes.**

Responsibilities:

- **Challenge generation** — parameterized challenge synthesis via LLM (Claude API)
- **Plagiarism detection** — code similarity detection using `tree-sitter` and embeddings
- **Talent matching** — filtering and scoring for recruiter queries
- **Media processing** — replay ingestion, clip generation via `ffmpeg` and MinIO

## MVP status (v2 gRPC contract)

The v2 gRPC contract (`skilluv.ai.v2` — see [`proto/skilluv_ai.proto`](proto/skilluv_ai.proto)) is **MVP-ready**. Phases M1 → M5 done, M6 (deployment) is the last step.

| Phase | Scope | Status |
|---|---|---|
| M1 | Proto unification (4 services, versioning rules) | ✅ done |
| M2 | gRPC wrappers CodeReview + Plagiarism | ✅ done |
| M3 | TalentDetection (AnalyzePerformance + SuggestCareerPath) | ✅ done |
| M4 | GenerateChallenge + GenerateVariant v2 | ✅ done |
| M5 | Metrics, Grafana, alerts, e2e tests, docs | ✅ done |
| M6 | Docker image + Hetzner deploy + secrets | ✅ done |

Key entry points :
- **Plan & decisions** : [`docs/MVP.md`](docs/MVP.md) (§0 = decisions arrêtées)
- **API contract** : [`docs/API-CONTRACT.md`](docs/API-CONTRACT.md) (grpcurl examples for the 4 services)
- **Deployment** : [`docs/DEPLOYMENT-HETZNER.md`](docs/DEPLOYMENT-HETZNER.md) + [`docker-compose.prod.yml`](docker-compose.prod.yml)
- **Dashboards** : [`infra/grafana/skilluv-ai-grpc-dashboard.json`](infra/grafana/skilluv-ai-grpc-dashboard.json)
- **Alerts** : [`infra/prometheus/alerts.yml`](infra/prometheus/alerts.yml)

**Test suite** : ~230 tests, gRPC round-trips against a local `aio.server`, Claude mocked (no network cost).

## Companion repositories

- [`skilluv-backend`](https://github.com/skilluv/skilluv-backend) — Rust + Axum API (the caller for gRPC and Redis Queue)
- [`skilluv-frontend`](https://github.com/skilluv/skilluv-frontend) — SvelteKit web app for talents
- [`skilluv-admin`](https://github.com/skilluv/skilluv-admin) — SvelteKit admin panel

## Architecture

```
                          gRPC :50051
Rust Backend ────────────────────────────►  Challenge Generator (Claude API)

                     Redis Queue
Rust Backend ──push──►  skilluv:queue:plagiarism  ──►  Plagiarism Detector (tree-sitter + embeddings)
             ──push──►  skilluv:queue:matching    ──►  Talent Matcher (filtering + scoring)
             ──push──►  skilluv:queue:media       ──►  Media Processor (ffmpeg + MinIO)
                                                            │
                                                       skilluv:result:{job_id}
                                                            │
                                                       skilluv:notifications ──pub/sub──► Rust Backend
```

### Services

| Service                | Role                                                     | Communication      | External dependencies      |
|------------------------|----------------------------------------------------------|--------------------|----------------------------|
| Challenge Generator    | Generates parameterized challenges via LLM               | gRPC sync          | Claude API (Anthropic)     |
| Plagiarism Detector    | Detects similarity between code submissions              | Redis Queue async  | None                       |
| Talent Matcher         | Filters and scores talents for recruiter queries         | Redis Queue async  | None                       |
| Media Processor        | Ingests replays, generates clips                         | Redis Queue async  | ffmpeg, MinIO              |

## Quick start

**Prerequisites**: Python 3.12+, `uv`, Docker (for Redis, MinIO, and the Rust backend).

```bash
git clone https://github.com/skilluv/skilluv-ia.git
cd skilluv-ia
cp .env.example .env
# edit .env — CLAUDE_API_KEY, REDIS_URL, MINIO_ENDPOINT, etc.

uv sync
uv run python -m skilluv_ai
```

The gRPC server listens on port `50051`.

For the full deployment guide (Docker, Hetzner, monitoring via Grafana Loki + Prometheus), see [`README.fr.md`](README.fr.md).

## Contributing

Contributors welcome — Python engineers, ML/LLM practitioners, prompt engineers, security researchers interested in LLM prompt injection defense. See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

**AI-assisted contributions are welcome and encouraged** (and this service literally is one — full loop transparency).

## Security

For security disclosures, see [SECURITY.md](SECURITY.md). Because this service handles LLM prompts and executes with API keys, prompt injection and secret exfiltration reports are especially welcome.

## Monitoring

- Prometheus-compatible `/metrics` endpoint
- Metrics: `skilluv_ai_jobs_total`, `skilluv_ai_jobs_duration_seconds`, `skilluv_ai_jobs_in_progress`, `skilluv_ai_external_errors_total`
- Structured JSON logs to stdout, collected via Grafana Loki

## License

Distributed under the [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0). The AGPL was chosen to prevent closed forks of the AI pipeline while remaining compatible with the rest of the Skilluv stack.

## Origin

Skilluv is built solo by [Jeremie Zitti](https://github.com/skilluv), a Beninese engineer. Public launch: **January 2027**.
