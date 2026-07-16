"""Service de génération de challenges via LLM (Claude / Ollama / ...)."""

import json
from typing import Any, Literal

from src.exceptions import ValidationError
from src.llm import ModelTier, get_llm
from src.models.challenge import ChallengeParams, GeneratedChallenge
from src.services._challenge_prompts import build_system_prompt, build_user_prompt
from src.utils.logging import get_logger

VariantType = Literal["harder", "easier", "different_lang", "shorter", "longer"]

_VALID_VARIANT_TYPES: set[str] = {"harder", "easier", "different_lang", "shorter", "longer"}

logger = get_logger("service.challenge_generator")


# JSON Schema pour la sortie challenge — force le LLM à respecter la structure.
# Utilisé par ClaudeProvider (native json_schema) et OllamaProvider (validation
# post-call + prompt hint).
_CHALLENGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "instructions": {"type": "string"},
        "starter_code": {"type": ["string", "null"]},
        "test_cases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "input": {"type": "string"},
                    "expected_output": {"type": "string"},
                    "description": {"type": "string"},
                    "is_hidden": {"type": "boolean"},
                },
                "required": ["input", "expected_output", "description"],
                "additionalProperties": False,
            },
        },
        "evaluation_criteria": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title", "description", "instructions", "test_cases",
        "evaluation_criteria", "tags",
    ],
    "additionalProperties": False,
}


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
    """Génère un challenge complet via l'API Claude.

    Vérifie d'abord le cache Redis. Si un challenge identique existe,
    le retourne directement sans appeler Claude.
    """
    from src.services._challenge_cache import cache_challenge, get_cached_challenge

    # Vérifier le cache
    cached = await get_cached_challenge(params)
    if cached is not None:
        logger.info(
            "challenge_served_from_cache",
            title=cached.title,
            skill_domain=params.skill_domain,
        )
        return cached

    logger.info(
        "generating_challenge",
        skill_domain=params.skill_domain,
        difficulty=params.difficulty,
        duration=params.duration_minutes,
        tone=params.tone,
        language=params.language,
    )

    system_prompt = build_system_prompt(params)
    user_prompt = build_user_prompt(params)

    data = await get_llm().complete_structured(
        tier=ModelTier.STANDARD,
        system=system_prompt,
        user=user_prompt,
        schema=_CHALLENGE_SCHEMA,
        max_tokens=4096,
    )

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

    # Mettre en cache
    await cache_challenge(params, challenge)

    return challenge


# =========================================================================
# GenerateVariant — IA-M4
# =========================================================================


def _build_variant_prompt(
    original: GeneratedChallenge, variant_type: str, target_param: str
) -> tuple[str, str]:
    """Construit (system, user) pour transformer un challenge existant."""
    transformations = {
        "harder": (
            f"Rends ce challenge PLUS DIFFICILE. Passe de difficulté "
            f"{original.difficulty} à {target_param or original.difficulty + 1}. "
            "Ajoute des contraintes, cas limites, ou complexifie les tests."
        ),
        "easier": (
            f"Rends ce challenge PLUS FACILE. Passe de difficulté "
            f"{original.difficulty} à {target_param or max(1, original.difficulty - 1)}. "
            "Simplifie l'énoncé, réduis les cas à couvrir, guide davantage."
        ),
        "different_lang": (
            f"Adapte ce challenge à un autre langage de programmation : {target_param}. "
            "Garde la logique et la difficulté équivalentes, mais réécris starter_code "
            "et test_cases en {target_param}."
        ),
        "shorter": (
            f"Raccourcis la durée estimée. Passe de {original.duration_minutes} min "
            f"à {target_param or max(5, original.duration_minutes // 2)} min. "
            "Réduis la portée sans casser l'apprentissage central."
        ),
        "longer": (
            f"Allonge la durée estimée. Passe de {original.duration_minutes} min "
            f"à {target_param or min(180, original.duration_minutes * 2)} min. "
            "Ajoute des extensions ou des cas d'usage avancés."
        ),
    }
    instruction = transformations[variant_type]

    system = (
        "Tu es un concepteur pédagogique sur Skilluv. Ta mission : transformer un "
        "challenge existant en respectant une consigne précise. Tu dois PRÉSERVER "
        "l'esprit et le domaine du challenge original, et ne modifier que ce qui "
        "est demandé.\n\n"
        "Retourne UN SEUL objet JSON avec les mêmes champs que le challenge original "
        "(title, description, instructions, difficulty, duration_minutes, tags, "
        "starter_code, test_cases, evaluation_criteria). Pas de texte hors du JSON."
    )
    user = (
        f"# Consigne\n{instruction}\n\n"
        f"# Challenge original\n"
        + json.dumps(
            {
                "title": original.title,
                "description": original.description,
                "instructions": original.instructions,
                "difficulty": original.difficulty,
                "duration_minutes": original.duration_minutes,
                "skill_domain": original.skill_domain,
                "tone": original.tone,
                "tags": original.tags,
                "starter_code": original.starter_code,
                "test_cases": [tc.model_dump() for tc in original.test_cases],
                "evaluation_criteria": original.evaluation_criteria,
                "language": original.language,
                "ai_allowed": original.ai_allowed,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n\nProduis la variante au format JSON."
    )
    return system, user


def _resolve_variant_metadata(
    original: GeneratedChallenge, variant_type: str, target_param: str
) -> tuple[int, int]:
    """Détermine (difficulty, duration_minutes) attendus pour la variante."""
    difficulty = original.difficulty
    duration = original.duration_minutes
    if variant_type == "harder":
        try:
            difficulty = int(target_param) if target_param else min(5, difficulty + 1)
        except ValueError:
            difficulty = min(5, difficulty + 1)
    elif variant_type == "easier":
        try:
            difficulty = int(target_param) if target_param else max(1, difficulty - 1)
        except ValueError:
            difficulty = max(1, difficulty - 1)
    elif variant_type == "shorter":
        try:
            duration = int(target_param) if target_param else max(5, duration // 2)
        except ValueError:
            duration = max(5, duration // 2)
    elif variant_type == "longer":
        try:
            duration = int(target_param) if target_param else min(180, duration * 2)
        except ValueError:
            duration = min(180, duration * 2)
    return difficulty, duration


async def generate_variant(
    original: GeneratedChallenge, variant_type: str, target_param: str
) -> GeneratedChallenge:
    """Génère une variante d'un challenge existant.

    variant_type ∈ {'harder','easier','different_lang','shorter','longer'}.
    target_param est spécifique au variant : difficulté cible, langage, minutes...
    """
    if variant_type not in _VALID_VARIANT_TYPES:
        raise ValidationError(
            f"variant_type invalide : {variant_type!r}",
            {"allowed": sorted(_VALID_VARIANT_TYPES)},
        )
    if not original.title:
        raise ValidationError(
            "Challenge original requis (backend doit fournir GenerateVariantRequest.original)",
            {},
        )

    logger.info(
        "generate_variant_started",
        variant_type=variant_type,
        original_title=original.title,
        target_param=target_param,
    )
    system, user = _build_variant_prompt(original, variant_type, target_param)
    # Variant reprend la même schema structurée que generate_challenge —
    # cohérence du contrat de sortie côté LLM (facilite Ollama en particulier).
    data = await get_llm().complete_structured(
        tier=ModelTier.STANDARD,
        system=system,
        user=user,
        schema=_CHALLENGE_SCHEMA,
        max_tokens=4096,
    )

    # Difficulty / duration : préfère la valeur retournée si présente, sinon
    # calcule à partir des règles de _resolve_variant_metadata (defensive).
    expected_diff, expected_dur = _resolve_variant_metadata(
        original, variant_type, target_param
    )

    variant = GeneratedChallenge(
        title=data.get("title", f"{original.title} — {variant_type}"),
        description=data.get("description", original.description),
        instructions=data.get("instructions", original.instructions),
        difficulty=int(data.get("difficulty", expected_diff)),
        duration_minutes=int(data.get("duration_minutes", expected_dur)),
        skill_domain=original.skill_domain,
        tone=original.tone,
        tags=data.get("tags", original.tags),
        starter_code=data.get("starter_code", original.starter_code),
        test_cases=data.get("test_cases", []),
        evaluation_criteria=data.get("evaluation_criteria", original.evaluation_criteria),
        # Récompense recalculée sur les nouvelles dimensions.
        fragment_reward=_calculate_fragment_reward(
            ChallengeParams(
                skill_domain=original.skill_domain,
                difficulty=int(data.get("difficulty", expected_diff)),
                duration_minutes=int(data.get("duration_minutes", expected_dur)),
                tone=original.tone,
                ai_allowed=original.ai_allowed,
                language=original.language,
                tags=original.tags,
            )
        ),
        ai_allowed=original.ai_allowed,
        language=original.language,
    )
    logger.info(
        "generate_variant_completed",
        variant_type=variant_type,
        title=variant.title,
        difficulty=variant.difficulty,
        duration=variant.duration_minutes,
    )
    return variant
