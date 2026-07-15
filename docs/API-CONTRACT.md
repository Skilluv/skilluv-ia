# skilluv-ai — Contrat gRPC v2

> **Statut** : MVP — 4 services exposés (M1–M4 done).
> **Source de vérité** : [`proto/skilluv_ai.proto`](../proto/skilluv_ai.proto).
> Le legacy `challenge.proto` (v1, `skilluv.ai.ChallengeService`) reste actif jusqu'à IA-M6.

Package proto v2 : `skilluv.ai.v2`. Deadline gRPC client recommandée : **60 s** (voir `MVP.md` §0.3).

Tous les exemples utilisent [`grpcurl`](https://github.com/fullstorydev/grpcurl) contre un serveur local (`localhost:50051`). Reflection n'est pas activée en prod → passer explicitement le proto avec `-import-path proto -proto skilluv_ai.proto`.

---

## 1. `CodeReviewService.ReviewCode`

**Modèle Claude** : Opus 4.7. **Cache Redis** : oui (clé = hash code + params).

### Requête

```bash
grpcurl -plaintext \
  -import-path proto -proto skilluv_ai.proto \
  -d '{
    "submission_id": "sub-42",
    "code": "def add(a, b):\n    return a + b",
    "language": "python",
    "challenge_title": "Sum two numbers",
    "challenge_instructions": "Return a + b.",
    "difficulty": 1
  }' \
  localhost:50051 skilluv.ai.v2.CodeReviewService/ReviewCode
```

### Réponse (extrait)

```json
{
  "qualityScore": 87,
  "summary": "Implémentation minimale et correcte.",
  "strengths": ["nommage clair"],
  "improvements": ["ajouter type hints"],
  "issues": [
    {"severity": "minor", "category": "style", "message": "Type hints absents.", "lineNumber": 1}
  ],
  "resources": [{"title": "PEP 484 type hints", "url": "", "kind": "doc"}],
  "modelVersion": "claude-opus-4-7"
}
```

**Codes d'erreur** :
- `UNAVAILABLE` — Claude upstream down (`ExternalServiceError`)
- `INTERNAL` — JSON invalide malgré structured outputs (rare, `ValidationError`)

---

## 2. `ChallengeGenerationService.GenerateChallenge`

**Modèle Claude** : Sonnet 4.6. **Cache Redis** : oui (sauf `tone=absurd`).

```bash
grpcurl -plaintext \
  -import-path proto -proto skilluv_ai.proto \
  -d '{
    "skill_domain": "code",
    "difficulty": 3,
    "duration_minutes": 45,
    "mode": "solo",
    "tone": "serious",
    "ai_allowed": false,
    "language": "fr",
    "programming_language": "python",
    "orientation_slug": "dev-backend",
    "is_training": true
  }' \
  localhost:50051 skilluv.ai.v2.ChallengeGenerationService/GenerateChallenge
```

Réponse : `GenerateChallengeResponse{success, challenge: GeneratedChallenge, error_message, model_version}`.

## 3. `ChallengeGenerationService.GenerateVariant`

**IA stateless** : le backend fournit le challenge original inline dans `original` (source : Postgres). Pas de dépendance à un cache inter-appels.

```bash
grpcurl -plaintext \
  -import-path proto -proto skilluv_ai.proto \
  -d '{
    "original_challenge_id": "ch-abc",
    "variant_type": "harder",
    "target_param": "4",
    "original": {
      "title": "FizzBuzz",
      "description": "...",
      "instructions": "...",
      "difficulty": 2,
      "duration_minutes": 30,
      "skill_domain": "code",
      "tone": "serious",
      "tags": ["python"],
      "starter_code": "def fizzbuzz(n): pass",
      "test_cases": [
        {"input": "3", "expected_output": "Fizz", "description": "mult 3", "is_hidden": false}
      ],
      "evaluation_criteria": "Boucle correcte.",
      "fragment_reward": 10,
      "ai_allowed": false,
      "language": "fr"
    }
  }' \
  localhost:50051 skilluv.ai.v2.ChallengeGenerationService/GenerateVariant
```

**variant_type** : `harder` | `easier` | `different_lang` | `shorter` | `longer`.
**target_param** :
- `harder`/`easier` : difficulté cible (int, sinon ±1 borné à [1..5])
- `different_lang` : nom du langage (`python`, `rust`, …)
- `shorter`/`longer` : minutes (int, sinon /2 ou ×2 borné à [5..180])

---

## 4. `TalentDetectionService.AnalyzePerformance`

**Modèle** : Sonnet 4.6. **L'IA ne recalcule rien** — utilise les snapshots fournis par le backend (voir `MVP.md` §4).

```bash
grpcurl -plaintext \
  -import-path proto -proto skilluv_ai.proto \
  -d '{
    "user_id": "user-42",
    "current_rank": "bronze",
    "skills": [
      {"skill_slug": "python", "wpc_total": 120, "evidence_count": 8}
    ],
    "deliverables": [
      {
        "deliverable_id": "d-1", "skill_slug": "python", "wpc": 40,
        "verified_at": "2026-06-01T10:00:00Z",
        "verifiable_by": "test_suite", "difficulty": 3
      }
    ],
    "orientations": [{"orientation_slug": "dev-backend", "completion_ratio": 0.55}]
  }' \
  localhost:50051 skilluv.ai.v2.TalentDetectionService/AnalyzePerformance
```

Réponse (extrait) :

```json
{
  "overallScore": 0.72,
  "strengths": [{"skillSlug": "python", "evidenceCount": 8, "wpcTotal": 120}],
  "gaps": [{"skillSlug": "sql", "importance": "critical", "reason": "Manque pour backend."}],
  "nextActions": [{"actionType": "attempt_challenge", "targetSlug": "sql-basics", "priority": 1}],
  "rankReadiness": {
    "currentRank": "bronze", "nextRank": "silver",
    "missingCriteria": [{"criterion": "wpc_total", "currentValue": 120, "threshold": 200}],
    "estimatedDaysToPromotion": 30
  },
  "modelVersion": "claude-sonnet-4-6"
}
```

**Cas dégénéré** : profil vide (aucun skill ni deliverable) → réponse safe **sans appel LLM** (économie de coût sur l'onboarding).

## 5. `TalentDetectionService.SuggestCareerPath`

**Modèle** : Haiku 4.5. Filtre défensif : slugs hors catalogue rejetés.

```bash
grpcurl -plaintext \
  -import-path proto -proto skilluv_ai.proto \
  -d '{
    "user_id": "user-42",
    "skills": [{"skill_slug": "python", "wpc_total": 200, "evidence_count": 15}],
    "working_languages": ["fr", "en"],
    "target_market": "africa",
    "max_suggestions": 3
  }' \
  localhost:50051 skilluv.ai.v2.TalentDetectionService/SuggestCareerPath
```

Catalogue orientations : [`src/data/orientations_catalog.json`](../src/data/orientations_catalog.json). À sync avec les 31 orientations backend (voir `_meta.todo`).

---

## 6. `PlagiarismService.CheckPlagiarism`

**Déterministe** : AST (tree-sitter) + embeddings (sentence-transformers). **Pas d'appel Claude**, coût $0. Seuil défaut = `settings.plagiarism_threshold` (0.80).

```bash
grpcurl -plaintext \
  -import-path proto -proto skilluv_ai.proto \
  -d '{
    "submission_id": "sub-42",
    "code": "def hello():\n    return \"world\"",
    "language": "python",
    "comparison_pool": [
      {
        "submission_id": "sub-clone",
        "code": "def hello():\n    return \"world\"",
        "language": "python",
        "submitted_at": "2026-07-01T10:00:00Z"
      }
    ],
    "threshold": 0.85
  }' \
  localhost:50051 skilluv.ai.v2.PlagiarismService/CheckPlagiarism
```

Réponse :

```json
{
  "similarityScore": 1.0,
  "similarSubmissionId": "sub-clone",
  "astSimilarity": 1.0,
  "embeddingSimilarity": 1.0,
  "isPlagiarism": true,
  "modelVersion": "ast+embedding-v1"
}
```

`threshold=0` (défaut proto) → utilise le seuil global du service. `threshold>0` → override par requête.

---

## Métriques Prometheus exposées

Endpoint : `http://<host>:8000/metrics`. Deux séries clés côté MVP :

| Métrique | Type | Labels | Buckets / Notes |
|---|---|---|---|
| `skilluv_ai_grpc_request_duration_seconds` | Histogram | `method` | 0.05–60 s |
| `skilluv_ai_grpc_requests_total` | Counter | `method`, `status` (`ok`\|`error`) | — |
| `skilluv_ai_external_errors_total` | Counter | `service` (`claude_api`\|…) | Alerte si > 0.1/s |

Dashboard prêt : [`infra/grafana/skilluv-ai-grpc-dashboard.json`](../infra/grafana/skilluv-ai-grpc-dashboard.json).
Règles d'alertes : [`infra/prometheus/alerts.yml`](../infra/prometheus/alerts.yml).

---

## Règles de versioning proto (MVP.md §0.5)

- Nouveau champ → **optional** (proto3) ou default sûr.
- **Jamais** de renumbering.
- Suppression → `reserved N` + garder la doc du champ.
- Chaque réponse contient `model_version: string` (traçabilité audit).
