"""Provider Claude (Anthropic API) — reprend l'existant _call_claude_structured.

Utilise `output_config.format = json_schema` pour garantir un JSON valide en
sortie (feature Claude native, plus fiable qu'un parsing text).
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from src.config import settings
from src.exceptions import ExternalServiceError, ValidationError
from src.llm.base import LLMProvider, ModelTier
from src.utils.logging import get_logger
from src.utils.metrics import external_errors_total

logger = get_logger("llm.claude")


# Règle unique MVP.md §0.2. Override par env si besoin (rare, à documenter).
_TIER_TO_MODEL: dict[ModelTier, str] = {
    ModelTier.PREMIUM: "claude-opus-4-7",
    ModelTier.STANDARD: "claude-sonnet-4-6",
    ModelTier.FAST: "claude-haiku-4-5-20251001",
}


class ClaudeProvider:
    name = "claude"

    def __init__(self) -> None:
        self._client: anthropic.AsyncAnthropic | None = None

    def _get_client(self) -> anthropic.AsyncAnthropic:
        if self._client is None:
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        return self._client

    def model_for_tier(self, tier: ModelTier) -> str:
        return _TIER_TO_MODEL[tier]

    async def complete_structured(
        self,
        *,
        tier: ModelTier,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        client = self._get_client()
        model = self.model_for_tier(tier)
        try:
            async with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                output_config={
                    "format": {"type": "json_schema", "schema": schema},
                },
                system=system,
                messages=[{"role": "user", "content": user}],
            ) as stream:
                final = await stream.get_final_message()
        except anthropic.APIError as e:
            external_errors_total.labels(service="claude_api").inc()
            raise ExternalServiceError(
                f"Claude API error ({model}): {e.message}",
                {"status_code": getattr(e, "status_code", None)},
            ) from e

        raw = next((b.text for b in final.content if b.type == "text"), "")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValidationError(
                f"Claude returned invalid JSON despite json_schema ({model})",
                {"raw_response": raw[:500], "error": str(e)},
            ) from e
