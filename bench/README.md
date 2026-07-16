# Load testing skilluv-ai

Scripts `ghz` pour mesurer la latence + throughput des méthodes gRPC v2 sous
charge. Utile avant chaque bump de tag prod.

## Prérequis

- [`ghz`](https://ghz.sh/) installé (`brew install ghz` ou binaire GitHub Releases).
- Un serveur skilluv-ai qui tourne (local via docker compose ou target distant).
- Le fichier `proto/skilluv_ai.proto` accessible (le script y pointe automatiquement).

## Lancer

```bash
# Contre localhost, toutes les méthodes, 30s chacune
./bench/run.sh

# Contre staging, seulement ReviewCode
./bench/run.sh ai.staging.skilluv.example.com:443 review

# Concurrency + durée custom
GHZ_CONCURRENCY=50 GHZ_DURATION=60s ./bench/run.sh
```

## Interpréter les résultats

`ghz` affiche pour chaque méthode :

- **Latency (avg / p50 / p95 / p99)** — la valeur qui compte, pas la moyenne.
- **RPS** — throughput soutenu.
- **Status code distribution** — un `RESOURCE_EXHAUSTED` = rate-limit atteint, un `UNAVAILABLE` = Claude down.

### Seuils recommandés (voir `docs/API-CONTRACT.md`)

| Méthode | p50 cible | p95 cible | Alerte si p95 > |
|---|---|---|---|
| ReviewCode (Opus) | < 15 s | < 40 s | 60 s |
| GenerateChallenge (Sonnet) | < 8 s | < 18 s | 30 s |
| AnalyzePerformance (Sonnet) | < 6 s | < 15 s | 20 s |
| SuggestCareerPath (Haiku) | < 3 s | < 7 s | 10 s |
| CheckPlagiarism (déterministe) | < 2 s | < 5 s | 10 s |

Si la charge locale dépasse ces valeurs, ne pas déployer — profiler d'abord.

## Points d'attention

1. **Cache Redis fausse les résultats en local**. Le `submission_id` est le même à chaque appel dans les fixtures — la 2e requête sera un cache hit à ~1ms. Pour stress-tester le vrai chemin LLM, désactiver le cache côté service ou varier `submission_id` via `{{.RequestNumber}}` (déjà fait dans les fixtures).

2. **Rate-limiter est ACTIF** (voir `src/grpc_server/_rate_limit.py`). Un run à `--concurrency 100 --duration 60s` va rapidement saturer le budget par-peer (ex: 30 ReviewCode/min). Attendu — c'est ce qu'on veut valider en prod. Contre localhost, augmenter temporairement le budget si besoin de mesurer le débit maximal LLM.

3. **Coût Claude réel**. Un run de 30s à concurrency 10 sur ReviewCode = ~300 appels Opus @ $0.05 = **$15 par run**. Utiliser `SKILLUV_AI_MOCK_CLAUDE=1` en dev pour éviter la facture (nécessite l'implémentation d'un mode mock côté service — TODO post-MVP).

4. **HF Hub cold start**. Le 1er `CheckPlagiarism` télécharge le modèle sentence-transformers (~2min à froid). Warm-up recommandé avant le bench :
   ```bash
   grpcurl -plaintext -import-path proto -proto skilluv_ai.proto \
     -d "$(cat bench/ghz/check_plagiarism.json)" \
     localhost:50051 skilluv.ai.v2.PlagiarismService/CheckPlagiarism
   ```

## Fixtures

Dans `bench/ghz/` :

- `review_code.json` — fibonacci récursif basique, python
- `check_plagiarism.json` — 1 candidat identique + 1 différent
- `analyze_performance.json` — user bronze avec 2 skills et 2 deliverables

Ces fixtures sont volontairement petites pour ne pas polluer les mesures avec du parsing input. Pour tester des payloads plus lourds, dupliquer et remplacer.
