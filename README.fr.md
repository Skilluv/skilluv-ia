> 🇬🇧 [English version](README.md) · 🇫🇷 Version française (cette page)

---

# skilluv-ai

Service IA de la plateforme Skilluv. Gere la generation de challenges, la detection de plagiat, le matching talent-entreprise et le traitement media (replays, clips).

Ce service communique avec le backend Rust via gRPC (synchrone) et Redis Queue (asynchrone). Il n'expose aucune route publique.

---

## Architecture

```
                          gRPC :50051
Rust Backend ──────────────────────────► Challenge Generator (Claude API)

                     Redis Queue
Rust Backend ──push──► skilluv:queue:plagiarism ──► Plagiarism Detector (tree-sitter + embeddings)
             ──push──► skilluv:queue:matching   ──► Talent Matcher (filtrage + scoring)
             ──push──► skilluv:queue:media      ──► Media Processor (ffmpeg + MinIO)
                                                         │
                                                    skilluv:result:{job_id}
                                                         │
                                                    skilluv:notifications ──pub/sub──► Rust Backend
```

### Services

| Service | Role | Communication | Dependances externes |
|---------|------|---------------|---------------------|
| Challenge Generator | Genere des challenges parametrables via LLM | gRPC sync | Claude API (Anthropic) |
| Plagiarism Detector | Detecte la similarite entre soumissions de code | Redis Queue async | Aucune |
| Talent Matcher | Match les talents avec les criteres entreprise | Redis Queue async | Aucune |
| Media Processor | Genere des replays timelapse et clips 30s | Redis Queue async | MinIO, ffmpeg |

### Stack technique

| Composant | Technologie |
|-----------|-------------|
| Runtime | Python 3.12+ |
| API | FastAPI (health check, metrics Prometheus) |
| gRPC | grpcio + grpcio-tools |
| Workers async | ARQ (asyncio natif, Redis natif) |
| LLM | Anthropic SDK (Claude API) |
| Plagiat AST | tree-sitter + grammaires (Python, JS, TS, Java, C, C++, Rust, Go) |
| Plagiat embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Video | ffmpeg-python |
| Stockage objets | MinIO SDK |
| Config | pydantic-settings |
| Package manager | uv |
| Logging | structlog (JSON structure) |
| Monitoring | prometheus-client |
| Tests | pytest + pytest-asyncio |

---

## Structure du projet

```
skilluv-ai/
├── proto/                          Definitions gRPC partagees avec le backend Rust
│   └── challenge.proto
├── src/
│   ├── main.py                     Point d'entree (FastAPI + gRPC + ARQ)
│   ├── config.py                   Configuration via .env (pydantic-settings)
│   ├── exceptions.py               Hierarchie d'erreurs
│   ├── api/
│   │   ├── health.py               GET /health, GET /metrics
│   │   └── router.py               Application FastAPI
│   ├── grpc_server/
│   │   ├── server.py               Demarrage serveur gRPC
│   │   ├── challenge_servicer.py   Implementation ChallengeService
│   │   └── generated/              Code genere depuis proto/ (gitignore)
│   ├── workers/
│   │   ├── settings.py             Configuration ARQ
│   │   ├── plagiarism.py           Worker detection plagiat
│   │   ├── talent_matcher.py       Worker matching talent
│   │   └── media_processor.py      Worker replays + clips
│   ├── services/
│   │   ├── challenge_generator.py  Logique generation (Claude API)
│   │   ├── plagiarism_detector.py  Orchestrateur plagiat (AST + embeddings)
│   │   ├── _plagiarism_ast.py      Moteur AST (tree-sitter)
│   │   ├── _plagiarism_embeddings.py  Moteur embeddings (sentence-transformers)
│   │   ├── talent_matcher.py       Logique matching + scoring
│   │   └── media_processor.py      Pipeline ffmpeg (replays, clips)
│   ├── models/
│   │   ├── queue_messages.py       Schemas d'entree (payloads Queue)
│   │   ├── job_results.py          Schemas de sortie (resultats Redis)
│   │   ├── challenge.py            Modeles challenge (params, generated)
│   │   └── talent.py               Modeles talent (profil, criteres)
│   ├── storage/
│   │   └── minio_client.py         Client MinIO (upload/download)
│   └── utils/
│       ├── redis_client.py         Client Redis (resultats, idempotence, pub/sub)
│       ├── logging.py              Configuration structlog JSON
│       └── metrics.py              Compteurs Prometheus
├── tests/
│   ├── conftest.py                 Fixtures de test
│   ├── test_challenge_generator.py
│   ├── test_plagiarism_detector.py
│   ├── test_talent_matcher.py
│   ├── test_media_processor.py
│   └── test_models.py
├── scripts/
│   └── generate_proto.sh           Compile .proto en Python
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
└── .dockerignore
```

---

## Installation

### Prerequis

- Python 3.12+
- uv (https://docs.astral.sh/uv/)
- Docker et Docker Compose (pour Redis et MinIO en local)
- ffmpeg (installe dans le conteneur Docker, ou localement pour le dev)

### Setup

```bash
# Cloner le repo
git clone <repo-url> skilluv-ai
cd skilluv-ai

# Copier et configurer l'environnement
cp .env.example .env
# Editer .env : renseigner ANTHROPIC_API_KEY au minimum

# Installer les dependances
uv sync

# Installer les dependances de developpement
uv sync --extra dev

# Compiler les stubs gRPC
bash scripts/generate_proto.sh
```

---

## Utilisation

### Demarrage en developpement

```bash
# Lancer l'infrastructure locale (Redis + MinIO)
docker compose up -d redis minio

# Lancer le service
uv run python -m src.main
```

Le service demarre 3 process dans le meme event loop :
- FastAPI sur le port 8000 (health check + metrics)
- Serveur gRPC sur le port 50051
- Worker ARQ consommant les 3 queues Redis

### Demarrage via Docker

```bash
# Tout lancer (service + infra)
docker compose up --build

# Ou seulement le build
docker build -t skilluv-ai .
```

### Verification

```bash
# Health check
curl http://localhost:8000/health

# Metrics Prometheus
curl http://localhost:8000/metrics
```

---

## Tests

```bash
# Lancer tous les tests
uv run pytest

# Avec couverture
uv run pytest --cov=src --cov-report=term-missing

# Un fichier specifique
uv run pytest tests/test_challenge_generator.py -v
```

### Lint et typage

```bash
# Linter
uv run ruff check src/ tests/

# Type checking
uv run mypy src/ --ignore-missing-imports
```

---

## Configuration

Toute la configuration se fait via variables d'environnement ou fichier `.env`. Voir `.env.example` pour la liste complete.

| Variable | Description | Defaut |
|----------|-------------|--------|
| `REDIS_URL` | URL de connexion Redis | `redis://localhost:6379/0` |
| `MINIO_ENDPOINT` | Endpoint MinIO | `localhost:9000` |
| `MINIO_ACCESS_KEY` | Cle d'acces MinIO | `minioadmin` |
| `MINIO_SECRET_KEY` | Cle secrete MinIO | `minioadmin` |
| `MINIO_BUCKET` | Nom du bucket | `skilluv-media` |
| `ANTHROPIC_API_KEY` | Cle API Claude (Anthropic) | - |
| `GRPC_PORT` | Port du serveur gRPC | `50051` |
| `API_PORT` | Port FastAPI | `8000` |
| `LOG_LEVEL` | Niveau de log | `INFO` |
| `ENVIRONMENT` | Environnement (development/production) | `development` |
| `PLAGIARISM_THRESHOLD` | Seuil de detection plagiat | `0.80` |

---

## Communication avec le backend Rust

### gRPC (synchrone)

Le backend Rust appelle `ChallengeService.GenerateChallenge` pour generer un challenge. La definition du service est dans `proto/challenge.proto`.

```protobuf
service ChallengeService {
  rpc GenerateChallenge (GenerateChallengeRequest) returns (GenerateChallengeResponse);
  rpc ValidateChallenge (ValidateChallengeRequest) returns (ValidateChallengeResponse);
}
```

### Redis Queue (asynchrone)

Le backend Rust pousse des messages JSON dans les queues Redis. Le format est uniforme :

```json
{
  "job_id": "uuid-v4",
  "job_type": "plagiarism_check",
  "payload": { ... },
  "created_at": "2026-03-21T14:30:00Z",
  "retry_count": 0
}
```

Queues :
- `skilluv:queue:plagiarism` -- detection de plagiat
- `skilluv:queue:matching` -- matching talent
- `skilluv:queue:media` -- replays et clips

### Resultats

Chaque job ecrit son resultat dans Redis :
- Cle : `skilluv:result:{job_id}` (TTL 24h)
- Notification : publication sur le channel `skilluv:notifications`

```json
{
  "job_id": "uuid",
  "job_type": "plagiarism_check",
  "status": "completed",
  "summary": { ... }
}
```

---

## Services en detail

### Challenge Generator

Genere des challenges parametrables via l'API Claude. Le prompt est dynamique et s'adapte au domaine (code, design, game, security), a la difficulte (1-5), au ton (serious, fun, absurd) et a la langue (fr, en).

La recompense en fragments est calculee automatiquement : `difficulte x facteur_duree x complexite`.

### Plagiarism Detector

Approche hybride combinant deux moteurs :

1. **Moteur AST** (tree-sitter) : parse le code en arbre syntaxique, normalise (supprime identifiants, commentaires, litteraux), compare les structures via bigrammes Jaccard. Supporte 8 langages, fallback textuel pour les autres.

2. **Moteur Embeddings** (sentence-transformers, all-MiniLM-L6-v2) : encode le code en vecteurs 384 dimensions, compare par similarite cosinus. Modele local, ~100MB, tourne sur CPU.

Score combine : `0.6 x AST + 0.4 x embeddings`. Flag si >= 0.80 (configurable).

### Talent Matcher

Pipeline en 3 phases :

1. **Filtrage strict** : domaine de competence, fragments minimum, titre minimum, pays
2. **Scoring pondere** (sur 100) : domaines (25 pts), fragments (25 pts), titre (20 pts), langages (15 pts), trust score (15 pts)
3. **Tri decroissant** par score de pertinence

### Media Processor

Deux pipelines ffmpeg :

- **Replay** : reconstitue les frames d'edition a partir des events horodates, encode en video timelapse (10x), ajoute un overlay stats, upload vers MinIO (`skilluv-media/replays/`)
- **Clip** : telecharge un replay depuis MinIO, extrait un segment de 30 secondes, upload vers MinIO (`skilluv-media/clips/`)

---

## Deploiement

### Production (Hetzner)

Le service tourne dans un conteneur Docker unique sur le serveur Hetzner principal, aux cotes du backend Rust, PostgreSQL, Redis, MinIO et Judge0.

Pipeline CI/CD : GitHub Actions -> build Docker -> push GHCR -> SSH deploy.

### Monitoring

- Endpoint `/metrics` compatible Prometheus
- Metriques : `skilluv_ai_jobs_total`, `skilluv_ai_jobs_duration_seconds`, `skilluv_ai_jobs_in_progress`, `skilluv_ai_external_errors_total`
- Logs JSON structures vers stdout, collectes par Grafana Loki

---

## Licence

Ce projet est distribue sous licence [GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0).

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md) pour les modalites de contribution.
Voir [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) pour les regles de la communaute.

## Securite

Pour signaler une vulnerabilite, voir [SECURITY.md](SECURITY.md).
