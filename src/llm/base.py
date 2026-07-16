"""Protocol du provider LLM + enum des tiers de qualité.

Tiers volontairement abstraits pour découpler le code métier du choix de
modèle. `PREMIUM` peut être Opus 4.7 côté Claude ou Qwen 32B côté Ollama —
peu importe pour le code appelant.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol


class ModelTier(str, Enum):
    """Niveaux de qualité demandés au provider.

    Le provider mappe chaque tier vers un modèle concret (voir MVP.md §0.2).

    - PREMIUM : analyse approfondie, verdicts qui engagent la crédibilité
      (ex: ReviewCode). Claude Opus / Qwen 32B / Llama 70B.
    - STANDARD : génération créative + structurée (ex: GenerateChallenge,
      AnalyzePerformance). Claude Sonnet / Qwen 14B / Llama 8B.
    - FAST : mapping structuré rapide, faible coût (ex: SuggestCareerPath).
      Claude Haiku / Qwen 7B / Llama 3B.
    """

    PREMIUM = "premium"
    STANDARD = "standard"
    FAST = "fast"


class LLMProvider(Protocol):
    """Interface abstraite qu'un provider LLM doit implémenter."""

    @property
    def name(self) -> str:
        """Identifiant court du provider (ex: 'claude', 'ollama')."""
        ...

    def model_for_tier(self, tier: ModelTier) -> str:
        """Nom du modèle concret utilisé pour ce tier.

        Sert à peupler `model_version` dans les réponses gRPC pour la
        traçabilité audit (MVP.md §0.5).
        """
        ...

    async def complete_structured(
        self,
        *,
        tier: ModelTier,
        system: str,
        user: str,
        schema: dict[str, Any],
        max_tokens: int = 4000,
    ) -> dict[str, Any]:
        """Appel LLM avec sortie JSON respectant `schema` (JSON Schema).

        Le provider est responsable de garantir un dict valide en sortie.
        Si le LLM produit un JSON invalide, retry jusqu'à `max_retries` fois
        (implémentation-dépendant), puis lève `ValidationError`.

        Raises:
            ExternalServiceError: si le LLM est down / timeout.
            ValidationError: si la sortie ne matche pas le schema après retries.
        """
        ...
