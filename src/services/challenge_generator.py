"""Service de génération de challenges via Claude API."""

import json

import anthropic

from src.config import settings
from src.exceptions import ExternalServiceError, ValidationError
from src.models.challenge import ChallengeParams, GeneratedChallenge
from src.services._challenge_prompts import build_system_prompt, build_user_prompt
from src.utils.logging import get_logger
from src.utils.metrics import external_errors_total

logger = get_logger("service.challenge_generator")

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def _calculate_fragment_reward(params: ChallengeParams) -> int:
    """Calcule la récompense en fragments : difficulté x durée_factor x complexité."""
    duration_factor = max(1, params.duration_minutes // 15)
    complexity = 1 + (0.5 if params.tone == "absurd" else 0) + (0.3 if not params.ai_allowed else 0)
    return int(params.difficulty * duration_factor * complexity)


def _extract_json(raw_text: str) -> dict:
    """Extrait et parse le JSON de la réponse Claude.

    Gère les cas où Claude enveloppe dans ```json ... ``` ou ajoute du texte autour.
    """
    text = raw_text.strip()

    # Cas 1 : enveloppé dans des code fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3].strip()

    # Cas 2 : texte avant/après le JSON — chercher le premier { et dernier }
    if not text.startswith("{"):
        start = text.find("{")
        if start != -1:
            end = text.rfind("}")
            if end != -1:
                text = text[start : end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationError(
            "Claude a retourné un JSON invalide",
            {"raw_response": raw_text[:500], "error": str(e)},
        ) from e


async def generate_challenge(params: ChallengeParams) -> GeneratedChallenge:
    """Génère un challenge complet via l'API Claude."""
    logger.info(
        "generating_challenge",
        skill_domain=params.skill_domain,
        difficulty=params.difficulty,
        duration=params.duration_minutes,
        tone=params.tone,
        language=params.language,
    )

    client = _get_client()
    system_prompt = build_system_prompt(params)
    user_prompt = build_user_prompt(params)

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except anthropic.APIError as e:
        external_errors_total.labels(service="claude_api").inc()
        raise ExternalServiceError(
            f"Claude API error: {e.message}",
            {"status_code": getattr(e, "status_code", None)},
        ) from e

    raw_text = response.content[0].text.strip()
    data = _extract_json(raw_text)

    fragment_reward = _calculate_fragment_reward(params)

    challenge = GeneratedChallenge(
        title=data["title"],
        description=data["description"],
        instructions=data["instructions"],
        difficulty=params.difficulty,
        duration_minutes=params.duration_minutes,
        skill_domain=params.skill_domain,
        tone=params.tone,
        tags=data.get("tags", params.tags),
        starter_code=data.get("starter_code"),
        test_cases=data.get("test_cases", []),
        evaluation_criteria=data.get("evaluation_criteria", ""),
        fragment_reward=fragment_reward,
        ai_allowed=params.ai_allowed,
        language=params.language,
    )

    logger.info(
        "challenge_generated",
        title=challenge.title,
        test_cases_count=len(challenge.test_cases),
        fragment_reward=fragment_reward,
    )

    return challenge
