"""Service TalentDetection — AnalyzePerformance + SuggestCareerPath (IA-M3).

Deux méthodes indépendantes :

  - `analyze_performance(payload)` — Sonnet 4.6 — verdict pédagogique sur
    un utilisateur (strengths, gaps, next actions, rank readiness).
  - `suggest_career_path(payload)` — Haiku 4.5 — mapping skills -> orientations.

Principe (MVP.md §4) : l'IA ne recalcule PAS les rangs, badges ou capabilities.
Elle reçoit des snapshots déjà agrégés par le backend et produit une couche
sémantique par-dessus.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import anthropic

from src.config import settings
from src.exceptions import ExternalServiceError, ValidationError
from src.models.talent_analysis import (
    AnalyzePerformancePayload,
    AnalyzePerformanceResult,
    CareerPathPayload,
    CareerPathResult,
    GapItem,
    MissingCriterion,
    NextAction,
    OrientationSuggestion,
    RankReadiness,
    StrengthItem,
)
from src.utils.logging import get_logger
from src.utils.metrics import external_errors_total

logger = get_logger("service.talent_analyzer")

_client: anthropic.AsyncAnthropic | None = None

# Modèles Claude — règle unique (MVP.md §0.2).
_MODEL_ANALYZE = "claude-sonnet-4-6"
_MODEL_CAREER = "claude-haiku-4-5-20251001"


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


@lru_cache(maxsize=1)
def _load_orientations_catalog() -> dict[str, Any]:
    """Charge le catalogue orientations depuis src/data/orientations_catalog.json."""
    path = Path(__file__).resolve().parents[1] / "data" / "orientations_catalog.json"
    with path.open(encoding="utf-8") as f:
        return json.load(f)


# =========================================================================
# JSON schemas Claude structured outputs
# =========================================================================

_ANALYZE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overall_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "strengths": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "skill_slug": {"type": "string"},
                    "evidence_count": {"type": "integer", "minimum": 0},
                    "wpc_total": {"type": "integer", "minimum": 0},
                },
                "required": ["skill_slug", "evidence_count", "wpc_total"],
                "additionalProperties": False,
            },
        },
        "gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "skill_slug": {"type": "string"},
                    "importance": {"type": "string", "enum": ["critical", "nice_to_have"]},
                    "reason": {"type": "string"},
                },
                "required": ["skill_slug", "importance", "reason"],
                "additionalProperties": False,
            },
        },
        "next_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action_type": {
                        "type": "string",
                        "enum": ["attempt_challenge", "seek_mentor", "take_attestation"],
                    },
                    "target_slug": {"type": "string"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 5},
                },
                "required": ["action_type", "target_slug", "priority"],
                "additionalProperties": False,
            },
        },
        "rank_readiness": {
            "type": "object",
            "properties": {
                "current_rank": {"type": "string"},
                "next_rank": {"type": "string"},
                "missing_criteria": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "criterion": {"type": "string"},
                            "current_value": {"type": "number"},
                            "threshold": {"type": "number"},
                        },
                        "required": ["criterion", "current_value", "threshold"],
                        "additionalProperties": False,
                    },
                },
                "estimated_days_to_promotion": {"type": "integer", "minimum": 0},
            },
            "required": [
                "current_rank",
                "next_rank",
                "missing_criteria",
                "estimated_days_to_promotion",
            ],
            "additionalProperties": False,
        },
    },
    "required": ["overall_score", "strengths", "gaps", "next_actions", "rank_readiness"],
    "additionalProperties": False,
}


_CAREER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "orientation_slug": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "match_reason": {"type": "string"},
                    "required_skills_missing": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "transition_effort": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "timeline_estimate_months": {"type": "integer", "minimum": 0},
                },
                "required": [
                    "orientation_slug",
                    "confidence",
                    "match_reason",
                    "required_skills_missing",
                    "transition_effort",
                    "timeline_estimate_months",
                ],
                "additionalProperties": False,
            },
        },
        "primary_recommendation": {"type": "string"},
        "secondary_recommendations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["suggestions", "primary_recommendation", "secondary_recommendations"],
    "additionalProperties": False,
}


# =========================================================================
# Prompts
# =========================================================================


def _build_analyze_prompt(payload: AnalyzePerformancePayload) -> tuple[str, str]:
    system = (
        "Tu es un coach carrière tech pour la plateforme Skilluv "
        "(plateforme gamifiée africaine de démonstration de compétences). "
        "Ton rôle : lire le snapshot d'un utilisateur et produire un verdict "
        "pédagogique factuel qui l'aide à progresser.\n\n"
        "Règles strictes :\n"
        "- Ne calcule PAS les rangs ni les WPC toi-même (le backend l'a déjà fait). "
        "Utilise les données fournies telles quelles.\n"
        "- overall_score ∈ [0,1] : rapport global (activité, diversité skills, "
        "progression, cohérence avec les orientations).\n"
        "- strengths : 3-5 top skills basés sur wpc_total et evidence_count.\n"
        "- gaps : 2-5 skills manquants ou sous-représentés (importance = critical "
        "si bloque une orientation active, sinon nice_to_have).\n"
        "- next_actions : 3-5 actions concrètes, priorité 1 (haute) à 5 (basse). "
        "target_slug = un skill_slug ou un challenge_slug existant.\n"
        "- rank_readiness : missing_criteria doit lister les seuils quantitatifs "
        "qu'il reste à franchir. Sois honnête sur estimated_days_to_promotion.\n"
        "- Reste en français dans les champs textuels (reason, etc.)."
    )
    user = (
        f"# Utilisateur : {payload.user_id}\n"
        f"Rang actuel : {payload.current_rank or 'inconnu'}\n\n"
        f"## Skills ({len(payload.skills)})\n"
        + json.dumps([s.model_dump() for s in payload.skills], ensure_ascii=False, indent=2)
        + f"\n\n## Deliverables ({len(payload.deliverables)})\n"
        + json.dumps(
            [d.model_dump() for d in payload.deliverables[:50]],
            ensure_ascii=False,
            indent=2,
        )
        + f"\n\n## Orientations actives ({len(payload.orientations)})\n"
        + json.dumps(
            [o.model_dump() for o in payload.orientations], ensure_ascii=False, indent=2
        )
        + "\n\nProduis le verdict au format JSON demandé."
    )
    return system, user


def _build_career_prompt(payload: CareerPathPayload) -> tuple[str, str]:
    catalog = _load_orientations_catalog()
    orientations_summary = [
        {
            "slug": o["slug"],
            "label": o["label_fr"],
            "critical_skills": o["critical_skills"],
            "nice_to_have": o["nice_to_have_skills"],
            "target_markets": o["target_markets"],
            "typical_transition_months": o["typical_transition_months"],
        }
        for o in catalog["orientations"]
    ]
    system = (
        "Tu es un conseiller d'orientation professionnelle tech. "
        "Tu reçois le profil de compétences d'un utilisateur et un catalogue "
        "d'orientations métier disponibles sur Skilluv. Recommande les "
        "orientations les plus pertinentes.\n\n"
        "Règles strictes :\n"
        "- Utilise UNIQUEMENT les orientation_slug du catalogue fourni.\n"
        "- confidence ∈ [0,1] : rapport skills couverts / skills critiques.\n"
        "- transition_effort : 'low' si >70% critical_skills déjà maîtrisés, "
        "'medium' si 30-70%, 'high' sinon.\n"
        "- timeline_estimate_months : ajuste typical_transition_months selon les "
        "gaps réels.\n"
        "- required_skills_missing : liste les critical_skills que le user n'a pas.\n"
        "- Prends en compte target_market : filtre si l'orientation n'est pas "
        "disponible dans ce marché.\n"
        "- match_reason : 1-2 phrases en français expliquant le rationnel."
    )
    user = (
        f"# User : {payload.user_id}\n"
        f"Marché cible : {payload.target_market or 'non spécifié'}\n"
        f"Langues de travail : {', '.join(payload.working_languages) or 'non spécifié'}\n"
        f"max_suggestions : {payload.max_suggestions}\n\n"
        f"## Skills ({len(payload.skills)})\n"
        + json.dumps([s.model_dump() for s in payload.skills], ensure_ascii=False, indent=2)
        + "\n\n## Catalogue orientations\n"
        + json.dumps(orientations_summary, ensure_ascii=False, indent=2)
        + f"\n\nRetourne au plus {payload.max_suggestions} suggestions, triées "
        "par confidence décroissante. primary_recommendation = la meilleure, "
        "secondary_recommendations = les slug des autres. Format JSON demandé."
    )
    return system, user


# =========================================================================
# Appels Claude
# =========================================================================


async def _call_claude_structured(
    *,
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int = 4000,
) -> dict[str, Any]:
    """Appel Claude avec structured outputs. Renvoie le dict JSON parsé."""
    client = _get_client()
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
            f"Claude returned invalid JSON despite schema ({model})",
            {"raw_response": raw[:500], "error": str(e)},
        ) from e


# =========================================================================
# Points d'entrée publics
# =========================================================================


async def analyze_performance(
    payload: AnalyzePerformancePayload,
) -> AnalyzePerformanceResult:
    """Verdict pédagogique + rank readiness. Sonnet 4.6."""
    logger.info(
        "analyze_performance_started",
        user_id=payload.user_id,
        skills_count=len(payload.skills),
        deliverables_count=len(payload.deliverables),
        current_rank=payload.current_rank,
    )

    # Cas dégénéré : profil vide -> réponse safe sans appeler Claude.
    if not payload.skills and not payload.deliverables:
        return AnalyzePerformanceResult(
            overall_score=0.0,
            strengths=[],
            gaps=[],
            next_actions=[
                NextAction(
                    action_type="attempt_challenge",
                    target_slug="onboarding-hello-world",
                    priority=1,
                )
            ],
            rank_readiness=RankReadiness(current_rank=payload.current_rank),
        )

    system, user = _build_analyze_prompt(payload)
    data = await _call_claude_structured(
        model=_MODEL_ANALYZE, system=system, user=user, schema=_ANALYZE_SCHEMA,
    )

    result = AnalyzePerformanceResult(
        overall_score=float(data["overall_score"]),
        strengths=[StrengthItem(**s) for s in data.get("strengths", [])],
        gaps=[GapItem(**g) for g in data.get("gaps", [])],
        next_actions=[NextAction(**a) for a in data.get("next_actions", [])],
        rank_readiness=RankReadiness(
            current_rank=data["rank_readiness"].get("current_rank", ""),
            next_rank=data["rank_readiness"].get("next_rank", ""),
            missing_criteria=[
                MissingCriterion(**c)
                for c in data["rank_readiness"].get("missing_criteria", [])
            ],
            estimated_days_to_promotion=int(
                data["rank_readiness"].get("estimated_days_to_promotion", 0)
            ),
        ),
    )
    logger.info(
        "analyze_performance_completed",
        user_id=payload.user_id,
        overall_score=result.overall_score,
        strengths=len(result.strengths),
        gaps=len(result.gaps),
        next_actions=len(result.next_actions),
    )
    return result


async def suggest_career_path(payload: CareerPathPayload) -> CareerPathResult:
    """Recommande des orientations métier. Haiku 4.5."""
    logger.info(
        "career_path_started",
        user_id=payload.user_id,
        skills_count=len(payload.skills),
        target_market=payload.target_market,
    )

    if not payload.skills:
        # Onboarding pur : recommande une orientation généraliste par défaut.
        return CareerPathResult(
            suggestions=[],
            primary_recommendation="dev-frontend",
            secondary_recommendations=["dev-backend", "ui-designer"],
        )

    system, user = _build_career_prompt(payload)
    data = await _call_claude_structured(
        model=_MODEL_CAREER,
        system=system,
        user=user,
        schema=_CAREER_SCHEMA,
        max_tokens=2000,
    )

    # Validation défensive : les slug retournés doivent exister dans le catalogue.
    catalog_slugs = {o["slug"] for o in _load_orientations_catalog()["orientations"]}
    filtered_suggestions = [
        OrientationSuggestion(**s)
        for s in data.get("suggestions", [])
        if s.get("orientation_slug") in catalog_slugs
    ]
    primary = data.get("primary_recommendation", "")
    if primary not in catalog_slugs:
        primary = filtered_suggestions[0].orientation_slug if filtered_suggestions else ""
    secondary = [s for s in data.get("secondary_recommendations", []) if s in catalog_slugs]

    result = CareerPathResult(
        suggestions=filtered_suggestions,
        primary_recommendation=primary,
        secondary_recommendations=secondary,
    )
    logger.info(
        "career_path_completed",
        user_id=payload.user_id,
        suggestions=len(result.suggestions),
        primary=primary,
    )
    return result
