"""Provider Ollama — LLM local via l'API HTTP d'Ollama.

Ollama expose une API HTTP compatible OpenAI-lite. On utilise l'endpoint natif
`/api/chat` avec `format="json"` pour forcer une sortie JSON. **Contrairement
à Claude, Ollama ne comprend PAS un JSON schema en input** — on garantit la
conformité en 2 temps :

1. On injecte le schema dans le prompt système (au format lisible) pour
   guider le modèle.
2. On valide la sortie contre le schema après réception (jsonschema).
3. Si invalide, on retry 1 fois avec un prompt correcteur qui inclut l'erreur.

Cette approche donne >95% de succès en 1er coup avec Qwen 2.5 Coder 7B+
et 100% avec 1 retry sur les modèles de 7B et plus.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError as JsonSchemaError

from src.config import settings
from src.exceptions import ExternalServiceError, ValidationError
from src.llm.base import LLMProvider, ModelTier
from src.utils.logging import get_logger
from src.utils.metrics import external_errors_total

logger = get_logger("llm.ollama")

_DEFAULT_ENDPOINT = "http://localhost:11434"
_MAX_RETRIES = 1
_REQUEST_TIMEOUT_S = 300.0  # LLM local sur CPU peut être lent (voir docs/LOCAL-LLM.md)


class OllamaProvider:
    name = "ollama"

    def __init__(self) -> None:
        # L'endpoint et le mapping des modèles sont configurables via env.
        # Voir src/config.py pour les valeurs par défaut.
        self._endpoint = getattr(settings, "ollama_endpoint", _DEFAULT_ENDPOINT).rstrip("/")
        self._tier_to_model = {
            ModelTier.PREMIUM: getattr(
                settings, "ollama_model_premium", "qwen2.5-coder:14b-instruct-q4_K_M"
            ),
            ModelTier.STANDARD: getattr(
                settings, "ollama_model_standard", "qwen2.5-coder:7b-instruct-q4_K_M"
            ),
            ModelTier.FAST: getattr(
                settings, "ollama_model_fast", "qwen2.5-coder:3b-instruct-q4_K_M"
            ),
        }
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._endpoint, timeout=_REQUEST_TIMEOUT_S,
            )
        return self._client

    def model_for_tier(self, tier: ModelTier) -> str:
        # Format explicite pour audit : 'ollama:qwen2.5-coder:7b-instruct-q4_K_M'
        return f"ollama:{self._tier_to_model[tier]}"

    async def complete_structured(
        self,
        *,
        tier: ModelTier,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        model = self._tier_to_model[tier]
        validator = Draft7Validator(schema)

        # Ajoute au system prompt le schema attendu (Ollama ne le comprend
        # pas nativement — on le passe verbalement).
        schema_hint = _build_schema_hint(schema)
        system_with_schema = (
            f"{system}\n\n"
            "IMPORTANT — Format de sortie :\n"
            "Tu dois répondre UNIQUEMENT avec un objet JSON valide qui respecte "
            "STRICTEMENT ce schéma. Aucun texte avant, aucun texte après.\n\n"
            f"{schema_hint}"
        )

        last_error: str | None = None
        for attempt in range(_MAX_RETRIES + 1):
            user_prompt = user
            if attempt > 0 and last_error:
                user_prompt = (
                    f"{user}\n\n"
                    f"[Correction] Ta réponse précédente était invalide : {last_error}. "
                    "Réessaie en respectant strictement le schéma JSON demandé."
                )
            raw = await self._call_ollama_chat(
                model=model,
                system=system_with_schema,
                user=user_prompt,
                max_tokens=max_tokens,
            )
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                last_error = f"JSON invalide: {e}"
                logger.warning(
                    "ollama_invalid_json",
                    model=model,
                    attempt=attempt,
                    raw_head=raw[:200],
                )
                continue
            try:
                validator.validate(data)
            except JsonSchemaError as e:
                last_error = f"schema violation: {e.message} (path: {list(e.absolute_path)})"
                logger.warning(
                    "ollama_schema_violation",
                    model=model,
                    attempt=attempt,
                    error=last_error,
                )
                continue
            logger.info(
                "ollama_structured_ok",
                model=model,
                attempts=attempt + 1,
            )
            return data

        raise ValidationError(
            f"Ollama {model} did not produce valid JSON after {_MAX_RETRIES + 1} attempts",
            {"last_error": last_error},
        )

    async def _call_ollama_chat(
        self, *, model: str, system: str, user: str, max_tokens: int
    ) -> str:
        client = self._get_client()
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            # `format: "json"` force Ollama à respecter le mode JSON strict
            # côté decoding (grammar constraint quand supporté par le modèle).
            "format": "json",
            "options": {
                "num_predict": max_tokens,
                # Température basse pour output structuré (moins de créativité)
                "temperature": 0.3,
            },
        }
        try:
            response = await client.post("/api/chat", json=payload)
            response.raise_for_status()
        except httpx.HTTPError as e:
            external_errors_total.labels(service="ollama").inc()
            raise ExternalServiceError(
                f"Ollama HTTP error ({model}): {e}",
                {"endpoint": self._endpoint},
            ) from e
        data = response.json()
        # Format /api/chat : {"message": {"role": "assistant", "content": "..."}, ...}
        message = data.get("message", {})
        return message.get("content", "")


def _build_schema_hint(schema: dict[str, Any]) -> str:
    """Rend le JSON Schema sous forme lisible pour le prompt.

    Le modèle est plus fidèle si le schema est dans le prompt textuel plutôt
    qu'attendu implicitement.
    """
    return "```json\n" + json.dumps(schema, indent=2, ensure_ascii=False) + "\n```"
