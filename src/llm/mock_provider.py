"""Mock LLM provider — sortie déterministe qui satisfait le JSON schema.

Utilisé quand `SKILLUV_AI_MOCK_CLAUDE=1` (voir config.py). Aucun appel réseau,
aucune facture Claude, aucune dépendance Ollama. Utile pour :

- **Load tests `ghz`** : mesurer l'overhead gRPC + sérialisation pure sans
  bruit LLM.
- **CI** : pas besoin d'`ANTHROPIC_API_KEY` ni de tourner un Ollama pour
  faire passer la test suite.
- **Tests intégration end-to-end** : réponses stables entre runs.

Le mock produit une valeur "safe" par type JSON schema :
- `string` → `"mock-value"`
- `integer` / `number` → `0`
- `boolean` → `false`
- `array` → `[]`
- `object` → récursion sur `properties`

Champs `required` sont TOUS peuplés (contrat schema respecté). Les champs
optionnels sont ignorés pour minimiser le payload.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from src.llm.base import ModelTier

logger = get_logger("llm.mock")


class MockProvider:
    """Provider LLM qui synthétise une réponse conforme au JSON schema."""

    name = "mock"

    def model_for_tier(self, tier: ModelTier) -> str:
        return f"mock-{tier.value}"

    async def complete_structured(
        self,
        *,
        tier: ModelTier,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        del system, user, max_tokens  # unused
        result = _synthesize_from_schema(schema)
        logger.debug(
            "mock_llm_response",
            tier=tier.value,
            keys=list(result.keys()) if isinstance(result, dict) else None,
        )
        return result if isinstance(result, dict) else {}


def _synthesize_from_schema(schema: dict[str, Any]) -> Any:
    """Génère une valeur mock conforme à un JSON schema minimal.

    Support : type, properties, required, items, enum. Les autres mots-clés
    (pattern, minLength, ...) sont ignorés — le mock ne cherche pas à passer
    la validation JSON Schema stricte, juste à produire un dict typé.
    """
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]

    t = schema.get("type", "object")

    if t == "string":
        return "mock-value"
    if t == "integer":
        return 0
    if t == "number":
        return 0.0
    if t == "boolean":
        return False
    if t == "null":
        return None
    if t == "array":
        return []
    if t == "object":
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        out: dict[str, Any] = {}
        for key, sub_schema in props.items():
            if required and key not in required:
                continue
            out[key] = _synthesize_from_schema(sub_schema)
        # Si `required` n'est pas listé, on peuple TOUS les properties (safe
        # default : mieux vaut trop que trop peu pour un mock).
        if not required:
            for key, sub_schema in props.items():
                out[key] = _synthesize_from_schema(sub_schema)
        return out

    return None
