# skilluv-ia — Plan MVP

**Dernière révision** : 2026-07-15 (basé sur audit skilluv-backend jusqu'à P25).

**Contexte** : le backend Rust a évolué de P6 à P25 (badges Proof Engine, orientations métier, capabilities, hooks événementiels, enterprise types, community moderators). Le service IA Python n'a pas été touché depuis P5. Ce document liste **ce qui est là, ce qui manque, ce qu'il faut modifier, et dans quel ordre**.

**Principe MVP** : le service IA doit exposer un **contrat gRPC stable** que le backend consomme via `AiClient` (`src/grpc/client.rs`). Tout ce qui n'est pas dans le contrat AiClient est **hors MVP**.

---

## 1. État actuel — synthèse audit

**LOC totales : ~4 015** (Python source, hors generated + tests).

**Services implémentés** (12 modules) :

| Service | Fichier | gRPC ? | Queue ? | Utilisé par backend ? |
|---|---|---|---|---|
| Challenge generator | `challenge_generator.py` | ✅ | — | ✅ `AiClient::generate_challenge` |
| Challenge cache Redis | `_challenge_cache.py` | — | — | interne |
| Code reviewer | `code_reviewer.py` | ❌ | ✅ | ✅ `AiClient::review_code` (**MISMATCH**) |
| Plagiarism detector (AST+embeddings) | `plagiarism_detector.py` | ❌ | ✅ | ✅ `AiClient::check_plagiarism` (**MISMATCH**) |
| Talent matcher | `talent_matcher.py` | ❌ | ✅ | ⚠ backend a `analyze_performance` + `suggest_career_path` **NON IMPLÉMENTÉS** |
| Recommender | `recommender.py` | ❌ | ✅ | ❌ backend ne l'appelle pas |
| Analytics IA (hidden gems + churn) | `analytics_ai.py` | ❌ | ✅ | ❌ backend ne l'appelle pas |
| Media processor (timelapse + clips) | `media_processor.py` | ❌ | ✅ | ❌ backend ne l'appelle pas |

**Proto actuel** : `proto/challenge.proto` définit UNE service (`ChallengeService`) avec **2 méthodes** (GenerateChallenge, ValidateChallenge).

**Contrat backend attendu** : 5 méthodes RPC sur `AiClient` (voir §2).

**Gap principal** : proto sous-dimensionné + 3 services critiques manquants ou async-only.

---

## 2. Contrat backend attendu (source de vérité)

Extrait de `skilluv-backend/src/grpc/client.rs` :

```rust
impl AiClient {
    pub async fn review_code(...)          -> CodeReviewResponse;
    pub async fn generate_challenge(...)   -> GenerateChallengeResponse;
    pub async fn analyze_performance(...)  -> AnalyzePerformanceResponse;
    pub async fn suggest_career_path(...)  -> CareerPathResponse;
    pub async fn check_plagiarism(...)     -> PlagiarismResponse;
}
```

**5 méthodes → 4 services gRPC** (`analyze_performance` + `suggest_career_path` partagent `TalentDetectionService`).

### 2.1 CodeReviewResponse (utilisé par backend P15.2 llm_verifier)

Champs consommés par `skilluv-backend/src/services/llm_verifier.rs` :

- `quality_score: int32` (0-100, normalisé à [0,1] côté Rust)
- `summary: string` (1-2 phrases)
- `strengths: repeated string` (3 max côté Rust)
- `improvements: repeated string` (3 max côté Rust)
- `issues: repeated Issue`

### 2.2 CheckPlagiarismResponse (utilisé par P14.3)

Backend attend `similarity_score ∈ [0,1]` + `similar_submission_id` + `matched_ranges[]`.

### 2.3 AnalyzePerformance / CareerPath (à écrire — n'existe pas)

Backend a des types Rust mais **aucun endpoint appelé** encore. On peut donc **définir le contrat maintenant** de façon à ce qu'il matche les nouveaux features backend :

- Orientations métier (P16) → `SuggestCareerPath` retourne des `orientation_slug[]` (dev-frontend, pentester-web, etc.).
- Capabilities (P18) → `AnalyzePerformance` peut signaler "près du seuil mentor".
- Rank system (P17.4) → `AnalyzePerformance` peut suggérer les artefacts qui débloqueront le prochain rang.

---

## 3. Ce qu'il faut FAIRE — MVP scope

### 3.1 Unifier le proto (Phase IA-M1)

Créer `proto/skilluv_ai.proto` (remplace ou complète `challenge.proto`) avec les 4 services :

- `CodeReviewService.ReviewCode`
- `ChallengeGenerationService.GenerateChallenge` + `GenerateVariant`
- `TalentDetectionService.AnalyzePerformance` + `SuggestCareerPath`
- `PlagiarismService.CheckPlagiarism`

**Contrats messages précis** : voir Annexe A.

### 3.2 gRPC wrappers autour des workers existants (Phase IA-M2)

3 services ont déjà la logique métier **mais uniquement en workers async ARQ**. Il faut exposer des méthodes gRPC synchrones qui appellent ces logiques directement (pas via queue) :

- `CodeReviewServicer.ReviewCode(request)` → appelle `code_reviewer.review(...)` en direct.
- `PlagiarismServicer.CheckPlagiarism(request)` → appelle `plagiarism_detector.detect(...)` en direct.

**Timeout gRPC** : 30s par défaut. Prévoir `deadline` côté client Rust.

**Cache Redis** : garder le pattern actuel (clé = hash du code + params). Évite re-invoke coûteux LLM.

### 3.3 TalentDetectionService — implémentation nouvelle (Phase IA-M3)

**AnalyzePerformance** : analyse d'un user (deliverables verified + attestations + user_skills + orientations) → verdict pédagogique :

```
Input :  user_id + snapshot des deliverables/skills/orientations
Output : {
  overall_score: float [0-1],
  strengths: [{skill_slug, evidence_count, wpc_total}],
  gaps: [{skill_slug, importance, reason}],
  next_actions: [{action_type: 'attempt_challenge'|'seek_mentor'|'take_attestation', target_slug, priority}],
  rank_readiness: {
    current_rank, next_rank,
    missing_criteria: [{criterion, current_value, threshold}],
    estimated_days_to_promotion
  }
}
```

**SuggestCareerPath** : recommande des orientations métier basé sur les skills prouvés :

```
Input :  user_id + snapshot user_skills + working_languages + target_market ('africa'|'international')
Output : {
  suggestions: [{orientation_slug, confidence, match_reason, transition_effort, timeline_months}],
  primary_recommendation: orientation_slug,
  secondary_recommendations: [orientation_slug]
}
```

**Note importante** : ces méthodes NE doivent PAS ré-implémenter ce que le backend fait déjà (`services/skills.rs`, `services/orientations_playlist.rs`). Elles doivent **enrichir** avec de la sémantique LLM (Haiku pour vitesse + coûts) sur des snapshots pré-agrégés par le backend.

**Modèle LLM recommandé** : Claude Haiku 4.5 (rapide + moins cher), sauf pour `AnalyzePerformance` où Sonnet 4.6 est mieux si le user a > 50 artefacts.

### 3.4 GenerateVariant — méthode complémentaire (Phase IA-M4)

Backend n'appelle pas encore `GenerateVariant`, mais c'est prévu par le proto backend. Utile pour :

- Version "harder" d'un challenge existant (upscale difficulté 2 → 3).
- Version "different_lang" (Rust → Python).
- Version "shorter" (2h → 30min).

```
GenerateVariantRequest {
  challenge_id: string,
  variant_type: 'harder' | 'easier' | 'different_lang' | 'shorter' | 'longer',
  target_param: string
}
```

Retourne un `GeneratedChallenge` (même type que `GenerateChallenge`).

### 3.5 Tests e2e (Phase IA-M5)

Actuellement : 17 fichiers de tests unitaires, aucun e2e gRPC.

À ajouter :

- `tests/integration/test_grpc_code_review.py`
- `tests/integration/test_grpc_plagiarism.py`
- `tests/integration/test_grpc_talent.py`
- `tests/integration/test_grpc_challenge.py`

Un test = un roundtrip complet (client → server → service → response). Mock Claude API pour ne pas dépendre d'un token en test.

### 3.6 Deployment prod (Phase IA-M6)

- Docker image publiée (Docker Hub ou GHCR).
- Env `.env.production` template.
- Variables secrètes gérées via Vault ou GitHub Secrets.
- Health check gRPC endpoint (`grpc.health.v1.Health`).
- Metrics Prometheus exposées sur `:8000/metrics` (déjà en place).
- Alerting Grafana : Claude API errors > 5% sur 5min, gRPC latency p95 > 30s.

---

## 4. Ce qu'il faut NE PAS FAIRE (anti-scope creep)

**Ne PAS ré-implémenter côté IA ce que le backend fait déjà** :

- ❌ Calculer les rangs (P17.4) — le backend a `services/ranks.rs`. L'IA reçoit un snapshot, ne calcule pas.
- ❌ Vérifier les capabilities (P18) — le backend a `middleware/capabilities.rs`.
- ❌ Recompute les badges (P17.3) — le backend a `services/badge_engine.rs`.
- ❌ Filtrer par orientation (P16) — le backend a `talent_search_v3.rs`.
- ❌ Écrire dans la DB Skilluv — l'IA n'a pas accès direct à Postgres. Tous les writes passent par le backend.

**Ne PAS créer de nouveaux services non demandés par backend** :

- ❌ Pas de `RecommenderService` gRPC — `recommender.py` reste utile en worker async pour les emails digest.
- ❌ Pas de `MediaProcessorService` gRPC — reste en Queue.
- ❌ Pas de `AnalyticsService` gRPC — hidden gems + churn = jobs batch nightly.

**Ne PAS ajouter de dépendances Python lourdes non-nécessaires** :

- ❌ Pas de PyTorch, TensorFlow (sentence-transformers suffit).
- ❌ Pas de LangChain/LlamaIndex.

---

## 5. Ce qu'il faut MODIFIER

### 5.1 Proto migration (breaking)

Renommer `proto/challenge.proto` → `proto/skilluv_ai.proto` (ou garder + ajouter).

Régénérer les stubs Python via `python -m grpc_tools.protoc`.

Le backend a déjà `skilluv-backend/build.rs` qui compile son propre proto. **Synchroniser les protos** entre les deux repos.

### 5.2 Code reviewer — wrap sync

`services/code_reviewer.py` a une signature async utilisable en direct. Créer `grpc_server/code_review_servicer.py` qui l'appelle. Aucun changement dans la logique.

### 5.3 Plagiarism detector — wrap sync

Idem : `services/plagiarism_detector.py` fonctionne déjà en async, exposer via gRPC. Le worker ARQ reste (utile pour bulk scan admin), mais on ajoute la voie gRPC pour les scans one-shot.

### 5.4 Talent matcher — refactor partiel

`services/talent_matcher.py` fait actuellement du "matching enterprise → talents". À NE PAS confondre avec `TalentDetectionService` (analyse d'UN talent + suggestions carrière).

**Option** : garder `talent_matcher.py` comme est (worker async pour talent search enterprise), et créer un NOUVEAU module `services/talent_analyzer.py` pour AnalyzePerformance + SuggestCareerPath.

### 5.5 Config — Claude models

Actuellement `challenge_generator` utilise Sonnet 4, `code_reviewer` utilise Opus 4.7. Standardiser :

- **Opus 4.7** : `ReviewCode` (analyse profonde), `SuggestCareerPath` si > 50 artefacts.
- **Sonnet 4.6** : `GenerateChallenge`, `GenerateVariant`, `AnalyzePerformance`.
- **Haiku 4.5** : reformulations rapides, cache miss réhydration.

Env var `SKILLUV_AI_MODEL_DEFAULT` + override par méthode.

---

## 6. Ce qu'il faut SUPPRIMER

**Rien à supprimer.** Toute la logique existante est réutilisable :

- Media processor + workers restent (utilisés async pour replays profil).
- Recommender reste (utilisé pour digest emails).
- Analytics IA reste (hidden gems + churn = jobs batch admin).

**Une seule remarque** : `proto/challenge.proto` v1 devrait rester **le temps de la transition** (ne pas casser tant que le nouveau proto n'est pas prêt).

---

## 7. Phases séquencées

**Estimation totale : 15-22 jours de dev cumulé** pour un MVP fonctionnel + testé + déployé.

### Phase IA-M1 — Unification du proto ⏱️ 1-2 jours

- [ ] Créer `proto/skilluv_ai.proto` avec les 4 services + tous les messages listés Annexe A.
- [ ] Copier ce proto à l'identique dans `skilluv-backend/proto/`.
- [ ] Régénérer les stubs Python (`scripts/generate_grpc.sh`).
- [ ] Régénérer les stubs Rust (tonic-build via cargo build).
- [ ] Tests : `challenge_pb2` génère bien les nouvelles classes, `challenge_pb2_grpc` a les 4 servicers.

**DoD** : les deux repos compilent avec le nouveau proto ; ChallengeService continue de fonctionner.

### Phase IA-M2 — gRPC wrappers Code Review + Plagiarism ⏱️ 2-3 jours

- [ ] `grpc_server/code_review_servicer.py` — implémente `ReviewCode(request)` → appelle `services.code_reviewer.review(...)`.
- [ ] `grpc_server/plagiarism_servicer.py` — implémente `CheckPlagiarism(request)` → appelle `services.plagiarism_detector.detect(...)`.
- [ ] Enregistrer les 2 nouveaux servicers dans `grpc_server/server.py`.
- [ ] Tests : `tests/integration/test_grpc_code_review.py` + `test_grpc_plagiarism.py`.
- [ ] Vérifier depuis le backend Rust que `llm_verifier` et `plagiarism scan` fonctionnent en gRPC réel.

**DoD** : backend Rust peut appeler `AiClient::review_code` et `AiClient::check_plagiarism` avec succès end-to-end.

### Phase IA-M3 — TalentDetectionService (nouveau) ⏱️ 5-7 jours

- [ ] `services/talent_analyzer.py` — nouveau module avec `analyze_performance()` et `suggest_career_path()`.
- [ ] Prompts Claude Sonnet 4.6 pour AnalyzePerformance (rank readiness, gaps, next actions).
- [ ] Prompts Claude Haiku 4.5 pour SuggestCareerPath (mapping skills → orientations métier).
- [ ] Loader de catalogue orientations : copier le seed backend `migrations/0088_orientations_and_orientation_skill_map.sql` en fichier JSON versionné dans `src/data/orientations_catalog.json`.
- [ ] `grpc_server/talent_detection_servicer.py` — expose les 2 méthodes.
- [ ] Tests unitaires + integration.
- [ ] Documentation prompts + coûts LLM estimés.

**DoD** : backend Rust peut appeler `AiClient::analyze_performance` et `AiClient::suggest_career_path` ; réponses cohérentes avec les 31 orientations backend.

### Phase IA-M4 — GenerateVariant ⏱️ 2 jours

- [ ] Étendre `services/challenge_generator.py` avec `generate_variant(challenge_id, variant_type, target_param)`.
- [ ] Prompt Sonnet 4.6 spécifique : "reformule ce challenge en X" (fetch challenge original via cache Redis ou re-génère prompt).
- [ ] Ajouter la méthode au `ChallengeGenerationServicer`.
- [ ] Tests des 5 variant_type.

**DoD** : backend Rust peut appeler `AiClient::generate_variant` (une fois exposé côté Rust — noter : le client Rust doit être étendu aussi).

### Phase IA-M5 — Tests e2e + monitoring ⏱️ 3-4 jours

- [ ] `tests/integration/test_grpc_full_chain.py` — chaîne complète : backend fake → IA → Claude mocké → réponse.
- [ ] Grafana dashboard : latence p50/p95/p99 par méthode, error rate, Claude cost par jour.
- [ ] Alerts Prometheus : `claude_api_errors > 5% sur 5min`, `grpc_latency_p95 > 30s`.
- [ ] `README.md` mis à jour avec status "MVP-ready".
- [ ] `docs/API-CONTRACT.md` — les 4 services documentés avec exemples curl grpcurl.

**DoD** : dashboard "skilluv-ai health" visible sur Grafana ; alerte email si dégradation ; docs à jour.

### Phase IA-M6 — Deployment prod ⏱️ 2-3 jours

- [ ] `.env.production` template avec toutes les vars requises.
- [ ] Docker image publiée sur GHCR (`ghcr.io/skilluv/skilluv-ia:mvp-1`).
- [ ] `docs/DEPLOYMENT-HETZNER.md` — checklist opérationnelle (créer serveur, DNS, TLS, backup MinIO).
- [ ] Health check gRPC `grpc.health.v1.Health` conforme.
- [ ] Rollback plan documenté.

**DoD** : IA déployée + accessible depuis backend prod avec `GRPC_AI_URL=https://...`.

---

## 8. Post-MVP (référencer POST-MVP-BACKLOG.md dans le backend)

Une fois MVP livré, alignement avec les enhancements backend :

- **Timeline enrichie** (Tier 1.4 backend) → potentiel `SummarizeTimeline` method côté IA (Haiku).
- **Peer coaching matcher** (Tier 2.2) → possible `MatchPeers` gRPC method.
- **AI companion disclosed** (Tier 3.1) → gros chantier, `AiCompanionService` avec `ask()`, `explain()`, `generate_exercises()`.
- **Moderation pre-scoring** (P25 + post-MVP) → `ModerateContent(text) → {is_spam, is_toxic, needs_human}` pour aider forum_moderator.

**Rien de cela n'est MVP.** Post-lancement bêta minimum.

---

## Annexe A — Contrats gRPC détaillés

### A.1 CodeReviewService

```proto
message CodeReviewRequest {
  string submission_id = 1;
  string code = 2;
  string language = 3;
  string challenge_title = 4;
  string challenge_instructions = 5;
  int32  difficulty = 6;
}

message CodeReviewResponse {
  int32   quality_score = 1;        // 0-100
  string  summary = 2;
  repeated string strengths = 3;
  repeated string improvements = 4;
  repeated Issue issues = 5;
  repeated LearningResource resources = 6;
  string  model_version = 7;
}

message Issue {
  string severity = 1;              // 'blocker' | 'critical' | 'major' | 'minor'
  string category = 2;              // 'bug' | 'security' | 'perf' | 'style'
  string message = 3;
  int32  line_number = 4;
}

message LearningResource {
  string title = 1;
  string url = 2;
  string kind = 3;                  // 'doc' | 'article' | 'video'
}
```

### A.2 ChallengeGenerationService

```proto
message GenerateChallengeRequest {
  string skill_domain = 1;
  int32  difficulty = 2;
  int32  duration_minutes = 3;
  string mode = 4;                  // 'solo' | 'team'
  string tone = 5;
  bool   ai_allowed = 6;
  string language = 7;
  repeated string tags = 8;
  string programming_language = 9;
  string orientation_slug = 10;     // NOUVEAU (P16)
  bool   is_training = 11;
  string project_id = 12;
}

message GenerateVariantRequest {
  string original_challenge_id = 1;
  string variant_type = 2;
  string target_param = 3;
}
```

### A.3 TalentDetectionService

```proto
message AnalyzePerformanceRequest {
  string user_id = 1;
  repeated DeliverableSnapshot deliverables = 2;
  repeated SkillSnapshot skills = 3;
  repeated OrientationSnapshot orientations = 4;
  string current_rank = 5;
}

message AnalyzePerformanceResponse {
  double overall_score = 1;
  repeated StrengthItem strengths = 2;
  repeated GapItem gaps = 3;
  repeated NextAction next_actions = 4;
  RankReadiness rank_readiness = 5;
  string  model_version = 6;
}

message CareerPathRequest {
  string user_id = 1;
  repeated SkillSnapshot skills = 2;
  repeated string working_languages = 3;
  string target_market = 4;
  int32  max_suggestions = 5;
}

message CareerPathResponse {
  repeated OrientationSuggestion suggestions = 1;
  string primary_recommendation = 2;
  repeated string secondary_recommendations = 3;
  string  model_version = 4;
}

message OrientationSuggestion {
  string orientation_slug = 1;
  double confidence = 2;
  string match_reason = 3;
  repeated string required_skills_missing = 4;
  string transition_effort = 5;
  int32  timeline_estimate_months = 6;
}
```

### A.4 PlagiarismService

```proto
message CheckPlagiarismRequest {
  string submission_id = 1;
  string code = 2;
  string language = 3;
  repeated PreviousSubmission comparison_pool = 4;
  double threshold = 5;
}

message CheckPlagiarismResponse {
  double similarity_score = 1;
  string similar_submission_id = 2;
  double ast_similarity = 3;
  double embedding_similarity = 4;
  repeated MatchedRange matched_ranges = 5;
  bool   is_plagiarism = 6;
  string model_version = 7;
}
```

---

## Annexe B — Coûts LLM estimés (Claude API pricing 2026)

| Méthode | Modèle | Input tokens | Output tokens | Coût |
|---|---|---|---|---|
| ReviewCode | Opus 4.7 | ~2 000 | ~800 | ~$0.05 |
| GenerateChallenge | Sonnet 4.6 | ~500 | ~1 500 | ~$0.02 |
| GenerateVariant | Sonnet 4.6 | ~1 000 | ~1 500 | ~$0.025 |
| AnalyzePerformance | Sonnet 4.6 | ~1 500 | ~800 | ~$0.02 |
| SuggestCareerPath | Haiku 4.5 | ~800 | ~500 | ~$0.005 |
| CheckPlagiarism | (déterministe) | 0 | 0 | $0 |

**Cache Redis** : hit rate visé 40-60 % sur ReviewCode. Cost divisé par 2 en moyenne.

**Budget prévisionnel** : ~$50-200/mois pour 1 000 users actifs (à raffiner).

---

## Annexe C — Mapping backend → IA calls

| Backend event / route | Appelle | Quand ? |
|---|---|---|
| `POST /api/admin/fraud/llm-evaluate/{id}` | `ReviewCode` | Admin manuel + hook auto sur deliverable verifiable_by='llm_evaluation' |
| `POST /api/admin/challenges/generate` (P4) | `GenerateChallenge` | Admin crée un challenge template AI-assisté |
| `POST /api/admin/challenges/{id}/variant` (P24+ candidat) | `GenerateVariant` | Admin duplique un challenge à difficulty différente |
| `POST /api/users/me/orientations/suggest` (nouveau, à créer) | `SuggestCareerPath` | Onboarding : user vient de s'inscrire, propose 3 orientations basées sur profil |
| `GET /api/users/me/performance` (nouveau, à créer) | `AnalyzePerformance` | Profil user, section "coach IA" avec next actions |
| `POST /api/admin/fraud/scan-deliverable/{id}` | `CheckPlagiarism` | Admin manuel scan single deliverable |
| `capabilities_engine::recompute` (P18.2) | `AnalyzePerformance` (optionnel) | Enrichir la décision de promotion mentor (post-MVP) |

**Note** : les 2 routes "nouveau à créer" côté backend nécessitent une petite phase P26 backend post-IA-MVP. Estimation : 2 jours de dev backend.
