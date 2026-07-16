# LLM local avec Ollama

> **Décision produit** : à moyen terme, Skilluv opère son propre stack IA (souveraineté données + fine-tuning sur nos réviews réelles + coût fixe qui devient un actif). Court terme : dev en local sur Ollama, prod éventuellement Claude jusqu'à provisioning GPU.
>
> **Switch de provider** : `SKILLUV_AI_LLM_PROVIDER=ollama|claude` — même code métier, aucun refactor requis.

## 1. Setup rapide

### Option A — Ollama natif (recommandé pour dev)

```bash
# Windows/macOS/Linux : install en 1 commande
curl -fsSL https://ollama.com/install.sh | sh
# ou télécharger le .exe/.dmg depuis https://ollama.com/download

# Vérifier
ollama --version

# Pull des modèles par tier
ollama pull qwen2.5-coder:7b-instruct-q4_K_M   # STANDARD + PREMIUM (~4.5 GB)
ollama pull qwen2.5-coder:3b-instruct-q4_K_M   # FAST (~2 GB)
```

Le service Ollama tourne en arrière-plan sur `http://localhost:11434` (par défaut).

Config `.env` :
```dotenv
LLM_PROVIDER=ollama
OLLAMA_ENDPOINT=http://localhost:11434
```

### Option B — Ollama via docker-compose

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Pull des modèles à l'intérieur du container (persistant via volume)
docker compose exec ollama ollama pull qwen2.5-coder:7b-instruct-q4_K_M
docker compose exec ollama ollama pull qwen2.5-coder:3b-instruct-q4_K_M
```

skilluv-ai est auto-wired vers `http://ollama:11434` (voir `docker-compose.dev.yml`).

## 2. Choix du modèle selon ta machine

Les valeurs par défaut (Qwen 2.5 Coder 7B Q4_K_M) sont dimensionnées pour **16 GB RAM CPU-only**. Ajuster via env :

| Ton hardware | PREMIUM | STANDARD | FAST | Notes |
|---|---|---|---|---|
| **16 GB RAM, pas de GPU** (défaut) | `qwen2.5-coder:7b-instruct-q4_K_M` | idem | `qwen2.5-coder:3b-instruct-q4_K_M` | ReviewCode ~150s |
| 16 GB RAM CPU + iGPU AMD | idem | idem | idem | ROCm non fiable sur iGPU, reste CPU |
| 32 GB RAM CPU-only | `qwen2.5-coder:14b-instruct-q4_K_M` | `qwen2.5-coder:7b-instruct-q4_K_M` | `qwen2.5-coder:3b-instruct-q4_K_M` | Qualité +, latence ~2× |
| GPU 8 GB VRAM (RTX 3060, etc.) | `qwen2.5-coder:7b-instruct-q4_K_M` | idem | `qwen2.5-coder:3b-instruct-q4_K_M` | ~10× plus rapide qu'CPU |
| GPU 16 GB VRAM (RTX 4080, T4) | `qwen2.5-coder:14b-instruct-q4_K_M` | `qwen2.5-coder:7b-instruct` (fp16) | idem | Qualité Sonnet-ish |
| GPU 24 GB VRAM (RTX 3090/4090) | `qwen2.5-coder:32b-instruct-q4_K_M` | `qwen2.5-coder:14b-instruct-q4_K_M` | `qwen2.5-coder:7b-instruct-q4_K_M` | Qualité Opus-ish sur code |

Override par env :
```dotenv
OLLAMA_MODEL_PREMIUM=qwen2.5-coder:14b-instruct-q4_K_M
OLLAMA_MODEL_STANDARD=qwen2.5-coder:7b-instruct-q4_K_M
OLLAMA_MODEL_FAST=qwen2.5-coder:3b-instruct-q4_K_M
```

Alternatives non-Qwen à essayer :
- `deepseek-coder-v2:16b-lite-instruct-q4_K_M` — excellent sur code
- `llama3.1:8b-instruct-q4_K_M` — meilleur généraliste (SuggestCareerPath)
- `qwen2.5:14b-instruct-q4_K_M` — non-Coder, mais bon sur analyse pédagogique

## 3. Attentes de latence

Chiffres réalistes CPU Ryzen 5000/7000 en Q4_K_M :

| Modèle | Vitesse output | ReviewCode (~800 tok) | AnalyzePerformance (~500 tok) | SuggestCareerPath (~300 tok) |
|---|---|---|---|---|
| Qwen 3B | ~12 tok/s | ~70s | ~45s | ~25s |
| Qwen 7B | ~5 tok/s | **~150s** | ~100s | ~60s |
| Qwen 14B | ~2 tok/s | ~400s ⚠️ | ~250s | ~150s |
| Qwen 32B | ~1 tok/s | insoutenable | ~500s | ~300s |

**Avec un GPU dédié : divisez par ~5 à 20** selon le modèle.

## 4. Quelle qualité vs Claude ?

Nos observations (échantillon limité — à affiner sur trafic réel) :

| Tâche | Claude MVP | Ollama 7B Coder | Gap |
|---|---|---|---|
| CheckPlagiarism | déterministe | déterministe | zéro (pas de LLM) |
| SuggestCareerPath | Haiku 4.5 | Qwen 3B | Qwen bat Haiku sur mapping structuré |
| GenerateChallenge | Sonnet 4.6 | Qwen 7B | proche, Qwen un peu moins créatif |
| GenerateVariant | Sonnet 4.6 | Qwen 7B | proche |
| AnalyzePerformance | Sonnet 4.6 | Qwen 7B | proche sur profils simples, gap sur > 30 deliverables |
| **ReviewCode** | Opus 4.7 | Qwen 7B | **notable** — Opus reste devant sur code complexe |

**Recommandation** : Ollama couvre 90% des besoins MVP. Pour ReviewCode en prod payante, envisager fallback Claude au début, puis fine-tune un Qwen 14B sur 500-1000 vrais reviews Skilluv annotés (~2-3 mois post-lancement).

## 5. Troubleshooting

### `connection refused` sur localhost:11434

Ollama pas démarré. Vérifier :
```bash
ollama ps       # liste les modèles chargés
ollama serve    # démarre le serveur en foreground si besoin
```

Sur Windows/macOS, l'installateur Ollama démarre un daemon système — redémarrer le PC après install si nécessaire.

### `model not found`

Le modèle n'est pas pull. Vérifier :
```bash
ollama list
ollama pull qwen2.5-coder:7b-instruct-q4_K_M
```

Nom exact important — `qwen2.5-coder:7b` ≠ `qwen2.5-coder:7b-instruct-q4_K_M`.

### Sortie JSON invalide

L'`OllamaProvider` retry 1 fois automatiquement. Si ça persiste :

- Modèle trop petit pour respecter le schema → passer sur un tier supérieur.
- Schema trop complexe → réduire la profondeur (les 7B ont du mal au-delà de 3 niveaux de nesting).
- Vérifier les logs : `[warning] ollama_schema_violation` te donne l'erreur exacte.

### Latence très supérieure aux estimations

- Vérifier que le modèle n'est pas swappé disque : `ollama ps` doit montrer VRAM/RAM utilisée.
- CPU throttling thermique : lancer un `htop` pendant l'appel.
- Si tu tapes sur Ollama via docker-compose : le container hérite des limites Docker Desktop. Sur Windows/macOS, augmenter RAM allouée à Docker.

### Comment forcer un cas de test à repasser sur Claude ?

Utile pour comparer sortie Ollama vs Claude sur un même prompt :

```bash
LLM_PROVIDER=claude ANTHROPIC_API_KEY=sk-... uv run pytest tests/... -k my_case
```

Le singleton se ré-initialise à chaque process — pas de contamination entre runs.

## 6. CI et tests

- Les tests unitaires **mockent le provider** (`patch("src.services...._call_claude_structured")`), ils n'appellent jamais Ollama réel — CI GitHub Actions n'a ni GPU ni Ollama.
- Un test intégration Ollama optionnel existe pour valider le round-trip local :
  ```bash
  # Uniquement si Ollama tourne + modèle 3B pull
  uv run pytest tests/test_ollama_provider.py -m local_llm
  ```
- Marker `@pytest.mark.local_llm` skip par défaut, activable via `--run-local-llm`.
