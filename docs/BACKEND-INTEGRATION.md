# Backend Integration Guide — Consommer skilluv-ai v2

> **Audience** : équipe backend Rust (`skilluv-backend`).
> **Objectif** : passer d'`AiClient` v1 (2 méthodes sur `challenge.proto`) à v2 (6 méthodes sur `skilluv_ai.proto`) sans casser la prod.
> **Source de vérité API** : [`docs/API-CONTRACT.md`](API-CONTRACT.md) — ce document explique le _pourquoi_ et le _comment_ côté backend.

Chaque section précise **ce qu'il faut faire**, **comment** (extraits de code), et **pourquoi** cette décision a été arrêtée côté IA.

---

## 1. Vue d'ensemble — ordre de rollout suggéré

| Étape | Effort | Bloque | Impact utilisateur |
|---|---|---|---|
| 1.1 Sync proto + build.rs | 30 min | Tout le reste | Aucun |
| 1.2 Étendre `AiClient` (6 méthodes) | 1 j | Routes appelantes | Aucun |
| 1.3 Basculer `llm_verifier` sur `CodeReviewService.ReviewCode` | 2 h | — | Reviews plus riches |
| 1.4 Basculer `plagiarism scan` sur `PlagiarismService.CheckPlagiarism` | 2 h | — | Idem |
| 1.5 Ajouter route `POST /api/admin/challenges/{id}/variant` → `GenerateVariant` | 4 h | — | Admin peut décliner |
| 1.6 Ajouter route `GET /api/users/me/performance` → `AnalyzePerformance` | 4 h | — | Coach IA profil |
| 1.7 Ajouter route `POST /api/users/me/orientations/suggest` → `SuggestCareerPath` | 3 h | — | Onboarding smarter |
| 1.8 Retirer les appels legacy `challenge.proto` | 2 h | — | Aucun (deprecate) |

**Total estimé : 2 à 3 jours** de dev backend cumulé.

**Ne rien casser** : `challenge.proto` v1 reste enregistré sur le serveur IA. Le backend peut migrer route par route ; les 2 méthodes v1 continueront de répondre jusqu'à l'étape 1.8.

---

## 2. Sync du fichier proto (étape 1.1)

**Ce qu'il faut faire** : copier `skilluv-ia/proto/skilluv_ai.proto` dans `skilluv-backend/proto/skilluv_ai.proto` à l'identique, puis brancher tonic-build.

**Comment** :

```bash
# depuis skilluv-backend
cp ../skilluv-ia/proto/skilluv_ai.proto proto/skilluv_ai.proto
```

Dans `build.rs` :

```rust
fn main() -> Result<(), Box<dyn std::error::Error>> {
    tonic_build::configure()
        .build_server(false) // on est client uniquement
        .compile_protos(
            &["proto/challenge.proto", "proto/skilluv_ai.proto"],
            &["proto"],
        )?;
    Ok(())
}
```

Les deux protos coexistent. `cargo build` régénère les stubs Rust dans `OUT_DIR`.

**Pourquoi cette copie plutôt qu'une git submodule ?**
- Trop peu de contenu partagé pour justifier une submodule (un seul fichier).
- Les 2 repos ont des cycles de release indépendants.
- Le proto est un **contrat versionné** : le backend décide quand upgrader.
- Règle non négociable : quand le backend sync, le fichier doit être **byte-identique** au proto de l'IA. Divergence = régression garantie.

Un script `skilluv-backend/scripts/sync_ai_proto.sh` qui fait le `cp` + `git diff --exit-code` peut être ajouté en pre-commit ou CI.

---

## 3. Extension `AiClient` (étape 1.2)

**Ce qu'il faut faire** : passer de 5 à 6 méthodes dans `src/grpc/client.rs`. Ajouter `generate_variant`.

**Comment (squelette)** :

```rust
use tonic::transport::Channel;

// tonic génère ces modules à partir des .proto
pub mod skilluv_ai_v2 {
    tonic::include_proto!("skilluv.ai.v2");
}
use skilluv_ai_v2::{
    code_review_service_client::CodeReviewServiceClient,
    challenge_generation_service_client::ChallengeGenerationServiceClient,
    talent_detection_service_client::TalentDetectionServiceClient,
    plagiarism_service_client::PlagiarismServiceClient,
    CodeReviewRequest, GenerateChallengeRequest, GenerateVariantRequest,
    AnalyzePerformanceRequest, CareerPathRequest, CheckPlagiarismRequest,
};

pub struct AiClient {
    channel: Channel,
}

impl AiClient {
    pub async fn connect(addr: String) -> Result<Self, tonic::transport::Error> {
        // Deadline gRPC côté client = 60s (voir MVP.md §0.3).
        let channel = Channel::from_shared(addr)?
            .timeout(std::time::Duration::from_secs(60))
            .connect()
            .await?;
        Ok(Self { channel })
    }

    pub async fn review_code(&self, req: CodeReviewRequest) -> anyhow::Result<CodeReviewResponse> {
        let mut client = CodeReviewServiceClient::new(self.channel.clone());
        Ok(client.review_code(req).await?.into_inner())
    }

    pub async fn generate_challenge(&self, req: GenerateChallengeRequest) -> anyhow::Result<GenerateChallengeResponse> {
        let mut client = ChallengeGenerationServiceClient::new(self.channel.clone());
        Ok(client.generate_challenge(req).await?.into_inner())
    }

    pub async fn generate_variant(&self, req: GenerateVariantRequest) -> anyhow::Result<GenerateChallengeResponse> {
        let mut client = ChallengeGenerationServiceClient::new(self.channel.clone());
        Ok(client.generate_variant(req).await?.into_inner())
    }

    pub async fn analyze_performance(&self, req: AnalyzePerformanceRequest) -> anyhow::Result<AnalyzePerformanceResponse> {
        let mut client = TalentDetectionServiceClient::new(self.channel.clone());
        Ok(client.analyze_performance(req).await?.into_inner())
    }

    pub async fn suggest_career_path(&self, req: CareerPathRequest) -> anyhow::Result<CareerPathResponse> {
        let mut client = TalentDetectionServiceClient::new(self.channel.clone());
        Ok(client.suggest_career_path(req).await?.into_inner())
    }

    pub async fn check_plagiarism(&self, req: CheckPlagiarismRequest) -> anyhow::Result<CheckPlagiarismResponse> {
        let mut client = PlagiarismServiceClient::new(self.channel.clone());
        Ok(client.check_plagiarism(req).await?.into_inner())
    }
}
```

**Pourquoi ces choix** :

- **Un `Channel` partagé, `Client` créé à chaque appel** — tonic recommande cette approche. Le channel gère le pool de connexions HTTP/2, les clients sont légers.
- **Timeout par client = 60 s**. Cohérent avec `MVP.md §0.3`. Opus 4.7 sur `ReviewCode` peut dépasser 30 s ; 60 s est le worst-case observé côté IA. Timeout inférieur = risque de `DEADLINE_EXCEEDED` alors que la réponse est en route.
- **Erreurs `tonic::Status` propagées via `anyhow`** — le backend traite `UNAVAILABLE` comme "Claude down, réessayer" et `INTERNAL` comme "reformater la sortie" (voir §7 gestion erreurs).
- **Pas de retry automatique** dans `AiClient`. Le code appelant décide (route synchrone = pas de retry, worker = retry avec backoff).

---

## 4. Migrer `llm_verifier` sur v2 (étape 1.3)

**Ce qu'il faut faire** : `services/llm_verifier.rs` appelle aujourd'hui l'IA via un chemin queue (Redis) ou v1 legacy. Passer sur `AiClient::review_code`.

**Champs à alimenter** dans `CodeReviewRequest` :

| Champ | D'où vient-il | Notes |
|---|---|---|
| `submission_id` | table `deliverables.id` | UUID string |
| `code` | `deliverables.source_code` ou blob MinIO | Limité à 15 000 chars côté IA (troncature auto) |
| `language` | `deliverables.language` | ex: `python`, `rust`, `js` |
| `challenge_title` | `challenges.title` | Aide le tone du review |
| `challenge_instructions` | `challenges.description` | Idem |
| `difficulty` | `challenges.difficulty` | 1-5, permet au prompt d'ajuster la sévérité |

**Champs consommés dans la réponse** (déjà en place côté `llm_verifier`) :

| Champ | Usage backend |
|---|---|
| `quality_score` | 0-100, normaliser en `f64 / 100.0` avant stockage |
| `summary` | Résumé 1-2 phrases affiché au user |
| `strengths[]` | Cap à 3 côté Rust (déjà fait) |
| `improvements[]` | Cap à 3 côté Rust (déjà fait) |
| `issues[]` | Persister en table `deliverable_issues` |
| `model_version` | À logger + persister pour traçabilité audit |

**Pourquoi ne pas passer par une queue Redis ?**
- `llm_verifier` est appelé sur un chemin utilisateur (submission acceptée → verdict), la latence importe.
- Cache Redis côté IA masque déjà les appels répétés (§`_challenge_cache.py`).
- La queue reste pertinente pour les scans batch admin (worker ARQ inchangé).

---

## 5. Migrer plagiarism scan sur v2 (étape 1.4)

**Ce qu'il faut faire** : la route `POST /api/admin/fraud/scan-deliverable/{id}` (et potentiellement les hooks P14.3) doit appeler `AiClient::check_plagiarism`.

**Comment construire `CheckPlagiarismRequest`** :

```rust
let comparison_pool: Vec<PreviousSubmission> = sqlx::query_as!(
    PreviousSubmission,
    r#"
    SELECT
        d.id AS submission_id,
        d.source_code AS code,
        d.language AS language,
        d.created_at AS submitted_at
    FROM deliverables d
    WHERE d.challenge_id = $1
      AND d.id != $2
      AND d.status = 'verified'
    ORDER BY d.created_at DESC
    LIMIT 200
    "#,
    challenge_id,
    target_submission_id,
)
.fetch_all(&pool)
.await?;

let request = CheckPlagiarismRequest {
    submission_id: target_submission_id.to_string(),
    code: target.source_code.clone(),
    language: target.language.clone(),
    comparison_pool,
    threshold: 0.0, // 0 = utiliser le seuil global du service (0.80)
};
```

**Pourquoi limiter à 200 candidats ?**
- Coût CPU côté IA est linéaire dans la taille du pool (200 comparaisons AST + 200 embeddings).
- Sur du gros volume, préférer un pré-filtrage LSH côté backend (post-MVP).
- Alerting Grafana : la latence p95 de `CheckPlagiarism` doit rester < 10 s ; au-delà, réduire ce cap.

**`threshold` override** :
- `0.0` → utilise `settings.plagiarism_threshold` côté IA (0.80).
- `> 0.0` → override par requête (utile pour scans admin stricts à 0.95).

**Ce que le proto ne transporte PAS** (à savoir) :
- Pas de `user_id` par candidat. Si le backend a besoin de savoir qui a le clone, il joint sur `submission_id` retourné dans `similar_submission_id`.
- Pas de `submitted_at` utilisé côté IA. Champ présent pour futur pondération temporelle éventuelle.

---

## 6. Nouvelles routes (étapes 1.5, 1.6, 1.7)

### 6.1 `POST /api/admin/challenges/{id}/variant` → `GenerateVariant`

**Ce qu'il faut faire** :

1. Récupérer le challenge original en Postgres.
2. Convertir la row DB en `GeneratedChallenge` proto (contexte inline).
3. Appeler `AiClient::generate_variant`.
4. Persister le résultat comme un **nouveau** challenge (pas un update).

```rust
#[derive(serde::Deserialize)]
pub struct VariantParams {
    pub variant_type: String, // 'harder' | 'easier' | 'different_lang' | 'shorter' | 'longer'
    pub target_param: String,
}

pub async fn create_variant(
    State(state): State<AppState>,
    Path(challenge_id): Path<Uuid>,
    Json(params): Json<VariantParams>,
) -> Result<Json<CreatedChallenge>, ApiError> {
    let original_row = fetch_challenge(&state.pool, challenge_id).await?;
    let original_proto = challenge_row_to_proto(&original_row);

    let request = GenerateVariantRequest {
        original_challenge_id: challenge_id.to_string(),
        variant_type: params.variant_type,
        target_param: params.target_param,
        original: Some(original_proto),
    };
    let response = state.ai.generate_variant(request).await?;
    if !response.success {
        return Err(ApiError::UpstreamError(response.error_message));
    }

    let new_challenge = persist_challenge(
        &state.pool,
        response.challenge.expect("success => challenge présent"),
    ).await?;
    Ok(Json(new_challenge))
}
```

**Pourquoi `original` inline plutôt qu'un lookup Redis côté IA ?**
- Décision M4 : **l'IA est stateless**. Elle ne dépend d'aucun cache partagé inter-appels.
- Le backend est déjà la source de vérité (Postgres). Éviter la duplication.
- Simplifie le rollback, les tests, et la reprise après incident Redis.

### 6.2 `GET /api/users/me/performance` → `AnalyzePerformance`

**Ce qu'il faut faire** : agréger le snapshot user côté backend, appeler l'IA, retourner un JSON coach-friendly au frontend.

**Le point critique** : c'est le backend qui pré-calcule tout ce qui est déterministe. L'IA n'a QUE de la sémantique à ajouter.

```rust
async fn build_analyze_payload(pool: &PgPool, user_id: Uuid) -> AnalyzePerformanceRequest {
    let deliverables = fetch_recent_verified_deliverables(pool, user_id, 100).await;
    let skills = fetch_user_skills_snapshot(pool, user_id).await;
    let orientations = fetch_user_orientations(pool, user_id).await;
    let current_rank = fetch_user_rank(pool, user_id).await;

    AnalyzePerformanceRequest {
        user_id: user_id.to_string(),
        deliverables: deliverables.into_iter().map(Into::into).collect(),
        skills: skills.into_iter().map(Into::into).collect(),
        orientations: orientations.into_iter().map(Into::into).collect(),
        current_rank,
    }
}
```

**Ce qui doit être présent dans les snapshots** :

| Snapshot | Champs source Postgres | Pourquoi |
|---|---|---|
| `DeliverableSnapshot` | `deliverables.id`, `deliverables.skill_slug`, `deliverables.wpc`, `deliverables.verified_at`, `deliverables.verifiable_by`, `challenges.difficulty` | Permet à l'IA de raisonner sur la diversité + fraîcheur |
| `SkillSnapshot` | `user_skills.slug`, agrégats `wpc_total`, `evidence_count`, `first_evidence_at`, `last_evidence_at` | Priorise les strengths, détecte l'inactivité |
| `OrientationSnapshot` | `user_orientations.slug`, `completion_ratio` (déjà calculé par backend) | Contexte : quelles orientations le user a activées |
| `current_rank` | `users.rank` | Permet de projeter `rank_readiness.next_rank` |

**Limitation snapshot** : envoyer au plus **~50 deliverables récents** (l'IA côté prompt tronque à 50). Au-delà : bruit inutile qui gonfle le coût input tokens.

**Cas dégénéré** : si le user n'a AUCUN skill ni deliverable, l'IA renvoie une réponse safe sans appeler Claude (économie ~$0.02/user à l'onboarding). Le backend n'a rien à changer.

### 6.3 `POST /api/users/me/orientations/suggest` → `SuggestCareerPath`

**Ce qu'il faut faire** : route appelée à l'onboarding ou lors d'un refresh explicite.

```rust
let request = CareerPathRequest {
    user_id: user_id.to_string(),
    skills: skills_snapshot,
    working_languages: user.spoken_languages.clone(), // Vec<String>
    target_market: user.target_market.unwrap_or("international".into()),
    max_suggestions: 3,
};
let response = state.ai.suggest_career_path(request).await?;

// response.primary_recommendation = orientation_slug (ex: "dev-backend")
// response.suggestions[] = détails avec match_reason, timeline_estimate_months, ...
```

**Validation côté backend** (défense en profondeur) :
- Les `orientation_slug` retournés doivent exister dans la table `orientations`.
- L'IA filtre déjà contre son catalogue local (`orientations_catalog.json`), mais elle n'a que **8 des 31 orientations** au MVP. Voir §11 dette technique.

**Cas particulier onboarding** : si le user vient de s'inscrire (0 skills), l'IA renvoie `primary_recommendation="dev-frontend"` par défaut, sans appel Claude. Le backend peut proposer une orientation "généraliste" au premier écran sans latence.

---

## 7. Gestion des erreurs

L'IA renvoie **2 codes gRPC** en cas de problème :

| Code | Cause | Réaction backend |
|---|---|---|
| `UNAVAILABLE` | Claude API down / quota | Réponse 503 au client + retry avec backoff exponentiel (worker) OU fallback dégradé (route synchrone) |
| `INTERNAL` | Claude a renvoyé un JSON invalide malgré structured outputs | Log + alerte ; réponse 500. Ne PAS retry (bug côté IA, retry ne change rien) |

Sur `GenerateChallenge` / `GenerateVariant`, l'IA préfère renvoyer `success=false` dans la réponse (pas un status d'erreur gRPC) — le backend doit checker `response.success` :

```rust
let response = client.generate_variant(request).await?;
if !response.success {
    return Err(ApiError::UpstreamError(response.error_message));
}
```

**Pourquoi ce split ?**
- Erreurs "attendues" (variant_type invalide, original manquant) → dans le message pour permettre un traitement en 200 côté frontend.
- Erreurs "infra" (Claude down) → status gRPC pour permettre le retry systématique.

---

## 8. Deadlines et timeouts

**Règle §MVP.md §0.3** : deadline gRPC client = **60 s**. Ne descend PAS en dessous.

Par méthode (observations attendues) :

| Méthode | p50 attendu | p95 attendu | Deadline recommandée |
|---|---|---|---|
| `ReviewCode` (Opus 4.7) | 8-15 s | 25-40 s | **60 s** |
| `GenerateChallenge` (Sonnet 4.6) | 4-8 s | 12-18 s | 30 s |
| `GenerateVariant` (Sonnet 4.6) | 4-8 s | 12-18 s | 30 s |
| `AnalyzePerformance` (Sonnet 4.6) | 3-6 s | 10-15 s | 20 s |
| `SuggestCareerPath` (Haiku 4.5) | 1-3 s | 4-7 s | 10 s |
| `CheckPlagiarism` (déterministe) | < 2 s | < 5 s | 15 s |

Ces deadlines peuvent être ajustées via un helper :

```rust
let mut req = tonic::Request::new(request);
req.set_timeout(std::time::Duration::from_secs(60)); // par appel
```

**Pourquoi ces valeurs ?**
- Alertes Prometheus configurées pour p95 > 30 s (voir `infra/prometheus/alerts.yml`). Si Opus fait passer p95 > 30 s, c'est visible côté IA.
- Deadline < latence typique = timeouts fréquents et gaspillage de tokens (Claude finit son streaming, backend a déjà abandonné).
- Deadline >> latence typique = queue backend qui gonfle si l'IA est bloquée.

---

## 9. Métadonnées à persister systématiquement

Chaque appel doit **loguer + persister** :

- `model_version` (retourné dans chaque réponse) — traçabilité audit + explication d'un changement de comportement lors d'un upgrade modèle.
- Timestamp gRPC (client-side) — pour corréler avec les métriques Prometheus côté IA.
- Statut de la réponse (`success` explicite, ou `Ok`/`Err` du tonic call).

Recommandation : table `ai_call_log` (append-only, TTL 90 j) :

```sql
CREATE TABLE ai_call_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    method TEXT NOT NULL,          -- ex: 'ReviewCode'
    submission_id UUID,
    user_id UUID,
    latency_ms INT NOT NULL,
    status TEXT NOT NULL,          -- 'ok' | 'unavailable' | 'internal' | 'business_failure'
    model_version TEXT,
    called_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ai_call_log_called_at_idx ON ai_call_log (called_at DESC);
```

**Pourquoi persister** :
- Reconstitution ex-post d'un incident sans dépendre des rétentions Grafana (30 j).
- Analyse coût LLM par utilisateur / fonctionnalité.
- Détection d'abus (un user qui consomme 200 `ReviewCode`/jour est probablement un bot).

---

## 10. Champs du proto v2 non encore consommés

Le proto v2 accepte 3 champs sur `GenerateChallengeRequest` que l'IA **ne consomme pas encore côté prompt** (mais accepte pour éviter un breaking change plus tard) :

| Champ | Statut IA | Quand consommer |
|---|---|---|
| `orientation_slug` | Reçu, ignoré | Post-MVP : enrichir le prompt pour biaiser vers une orientation |
| `is_training` | Reçu, ignoré | Post-MVP : baisser la difficulté effective de -1 |
| `project_id` | Reçu, ignoré | Post-MVP : contextualiser sur un projet OSS existant |

**Le backend peut commencer à les envoyer dès maintenant.** L'IA les acceptera silencieusement. Quand la logique côté IA sera activée (probablement M+2 ou M+3), aucun changement de contrat.

---

## 11. Dette qui vous concerne côté backend

**Bloquants prod** :
- Étapes 1.1 → 1.4 (sync proto, `AiClient` étendu, migrations `llm_verifier` + `plagiarism`).

**Recommandés avant bêta** :
- Étapes 1.5 → 1.7 (nouvelles routes) — sans elles, `SuggestCareerPath` et `AnalyzePerformance` sont dev côté IA mais **inutilisées** en prod (waste).
- Sync des 23 orientations manquantes dans le backend vers `skilluv-ia/src/data/orientations_catalog.json`. À faire par ping/PR côté IA quand la table `orientations` du backend bouge.

**Post-MVP** :
- Consommer les champs `orientation_slug` / `is_training` / `project_id` (§10).
- Table `ai_call_log` (§9) — utile mais pas critique tant que le volume est faible.
- Pré-filtrage LSH côté backend pour réduire `comparison_pool` à < 200 candidats (§5).

---

## 12. Développement local

**Contre un IA local (recommandé)** :

```bash
cd skilluv-ia
docker compose up -d
# Le service écoute sur localhost:50051
```

Dans le backend :
```
GRPC_AI_URL=http://localhost:50051
```

**Contre un mock** (tests unitaires backend) :

Utiliser `tonic-mock` ou un serveur `aio.grpc` factice qui renvoie des réponses fixtures — évite le coût Claude en CI.

Le service IA expose aussi `grpc.health.v1.Health` — le backend peut valider la connexion avant chaque déploiement :

```bash
grpc_health_probe -addr=$GRPC_AI_URL
# {status: SERVING}
```

---

## 13. Ce que ce document ne couvre PAS

- Les **prompts** utilisés côté IA — c'est un détail d'implémentation côté service, susceptibles de bouger. Le contrat est le seul lien stable.
- Les **modèles Claude** — le mapping méthode → modèle est cette semaine `Opus/Sonnet/Haiku` (voir `MVP.md §0.2`), mais peut évoluer sans changement de contrat.
- Le **format `.env.production`** côté IA — c'est un secret opérationnel.
- La **stratégie d'observabilité côté backend** — Grafana IA (`infra/grafana/skilluv-ai-grpc-dashboard.json`) documente le côté IA ; le backend a ses propres dashboards.

Toute question sur le contrat → PR sur `docs/API-CONTRACT.md` ou `proto/skilluv_ai.proto`. Toute question sur le comportement métier → issue sur ce repo avec le tag `ai-behavior`.
