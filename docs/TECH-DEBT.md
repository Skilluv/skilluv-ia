# Tech Debt Tracker — skilluv-ai

> **Objectif** : garder trace de tout ce qui a été fait, ce qui reste, et pourquoi. À jour au **2026-07-16**.
>
> Convention :
> - ✅ **Done** — livré, dans un commit référencé
> - 🚧 **In progress** — commencé, pas fini
> - ⏳ **Blocked** — nécessite une action externe (backend, ops, produit)
> - 📋 **Backlog** — identifié, planifié, pas commencé

---

## 1. Dette bloquante prod

### Côté IA

| # | Item | Statut | Commit / PR | Notes |
|---|---|---|---|---|
| 1 | Publier image `ghcr.io/skilluv/skilluv-ia:mvp-1` | ⏳ | `.github/workflows/release.yml` prêt | Attend `git tag mvp-1` + push |
| 2 | Rate-limiting per-caller | ✅ | `7d18830`+ | `_rate_limit.py`, 11 tests |
| 3 | gRPC health check | ✅ | `2b1dda9` | `grpc.health.v1` conforme |

### Côté backend

| # | Item | Statut | Owner | Notes |
|---|---|---|---|---|
| 4 | Sync `proto/skilluv_ai.proto` + `build.rs` | ⏳ | backend | Voir `BACKEND-INTEGRATION.md` §2 |
| 5 | Étendre `AiClient` avec `generate_variant` | ⏳ | backend | §3 |
| 6 | Basculer `llm_verifier` sur `CodeReviewService.ReviewCode` | ⏳ | backend | §4 |
| 7 | Basculer plagiarism scan sur `PlagiarismService` v2 | ⏳ | backend | §5 |

---

## 2. Dette recommandée avant bêta

### Côté IA

| # | Item | Statut | Commit / PR | Notes |
|---|---|---|---|---|
| 8 | Catalogue orientations 8 → 22 | ✅ | this commit | Draft v0.2. À réconcilier avec migration 0088 backend (voir _meta.todo) |
| 9 | Enrichir prompt `generate_challenge` avec `orientation_slug` / `is_training` / `project_id` | ✅ | `7d18830` | 20 tests |
| 10 | Cache Redis pour `AnalyzePerformance` | ✅ | `7d18830` | ~$0.02/hit économisé |
| 11 | Alertmanager config template + wiring compose | ✅ | this commit | `infra/alertmanager/`, profile `alerting` |
| 12 | Load test harness `ghz` + doc | ✅ | this commit | `bench/`, 3 fixtures + README |
| 13 | Fix test flaky `test_similar_code` | ✅ | this commit | `pytest.skip` si HF Hub inaccessible |
| 14 | CI strict (retirer `continue-on-error` sur pytest) | ✅ | this commit | Lint reste tolérant en attendant nettoyage |

### Côté backend

| # | Item | Statut | Owner | Notes |
|---|---|---|---|---|
| 15 | Route `POST /api/admin/challenges/{id}/variant` | ⏳ | backend | Voir `BACKEND-INTEGRATION.md` §6.1 |
| 16 | Route `GET /api/users/me/performance` | ⏳ | backend | §6.2 |
| 17 | Route `POST /api/users/me/orientations/suggest` | ⏳ | backend | §6.3 |
| 18 | Fournir la migration 0088 SQL pour sync orientations exhaustif | ⏳ | backend | Actuellement 22 orientations côté IA (draft) vs 31 backend |

---

## 3. Dette de fond (post-bêta)

### Côté IA

| # | Item | Statut | Effort | Notes |
|---|---|---|---|---|
| 19 | Deprecate `proto/challenge.proto` v1 | 📋 | 2 h | Attend confirmation qu'aucun caller ne l'utilise (log warn dans le servicer legacy pour repérer) |
| 20 | Retirer `src/grpc_server/_manual_handler.py` | 📋 | 15 min | Utilisé uniquement quand stubs v1 pas générés — obsolète depuis `generate_proto.sh` systématique |
| 21 | Ruff clean pass (retirer `continue-on-error` sur lint) | 📋 | 2-3 h | ~20 warnings existants |
| 22 | Mode mock Claude (`SKILLUV_AI_MOCK_CLAUDE=1`) pour bench + tests intégration sans coût | 📋 | 3 h | Utile pour load tests réalistes |
| 23 | Table `ai_call_log` côté backend | ⏳ | 4 h | Voir `BACKEND-INTEGRATION.md` §9 — évite dépendance rétention Grafana |
| 24 | Pré-filtrage LSH côté backend pour plagiarism (cap 200 candidats) | ⏳ | 1 j | Voir §5 backend integration |
| 25 | Prompts LLM itérés sur 50-100 vrais cas | 📋 | 8-12 j | Le vrai travail post-lancement — c'est ce qui différencie une IA "acceptable" d'une IA "utile" |
| 26 | Ajouter tests intégration Redis avec vrai Docker Redis (pas juste mock) | 📋 | 2 h | Aujourd'hui `tests/integration/test_redis_integration.py` existe mais couverture partielle |

### Côté ops / infra

| # | Item | Statut | Notes |
|---|---|---|---|
| 27 | Provisionner serveur Hetzner + DNS + Caddy | ⏳ | Voir `DEPLOYMENT-HETZNER.md` §1-3 |
| 28 | Backup S3 secondaire (rclone → B2 ou S3-compat) | 📋 | Cron local suffit pour MVP, off-site avant scale |
| 29 | Rotation age keys | 📋 | Post-MVP, quand > 2 opérateurs |

---

## 4. Dette découverte pendant la mission

| # | Item | Statut | Notes |
|---|---|---|---|
| 30 | `grpc.aio.unary_unary_rpc_method_handler` n'existe pas | ✅ | Fix dans `2b1dda9`. Repéré via le test consolidé, aurait dormi jusqu'en prod |
| 31 | Cache key `challenge_generator` ne prenait pas les champs v2 | ✅ | `7d18830` — sinon collision entre challenges même params mais orientation différente |
| 32 | Champs v2 (`orientation_slug`, etc.) acceptés mais ignorés | ✅ | Consommés depuis `7d18830` |
| 33 | Pas de `uv.lock` committé | ✅ | `10723bf` — builds Docker reproductibles |
| 34 | Warning pytest sur `TestCase(BaseModel)` | ✅ | `10723bf` — `__test__ = False` |

---

## 5. Comment ce doc doit vivre

- **Ajouter** une ligne dès qu'une dette est identifiée en revue de code ou en post-mortem.
- **Modifier** le statut au moment du commit qui la résout, avec le hash.
- **Retirer** rien : garder l'historique, ça sert de post-mortem collectif.
- **Prioriser** les items via les colonnes §1 (bloquant prod) → §2 (bêta) → §3 (post-bêta).

Convention commit : `chore(debt): #N — <description courte>` pour repérer facilement.

---

## 6. Vue synthétique

**Résolu dans cette session** : items 2, 3, 8-14, 30-34 (14 items).

**Reste bloquant prod** : 1 (image push), 4-7 (backend).

**Reste avant bêta** : 15-18 (backend).

**Post-bêta** : 19-29 (11 items, ~3-5 semaines de work cumulé).

Si tu ajoutes du contexte utile en revue, commit le doc à jour ; ne le laisse pas dériver silencieusement.
