"""Service de code review pédagogique via Claude — Phase 5.2.

Utilise Claude Opus 4.7 avec `output_config.format` (structured outputs) pour
garantir un JSON valide et éviter le prompt-parsing fragile.
"""

from src.llm import ModelTier, get_llm
from src.models.code_review import CodeReviewFinding, CodeReviewPayload, CodeReviewResult
from src.utils.logging import get_logger

logger = get_logger("service.code_reviewer")


# Schéma JSON pour structured outputs — Claude retournera un JSON qui matche.
_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "summary": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["bug", "style", "perf", "security", "pedagogy", "best_practice"],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["info", "low", "medium", "high", "critical"],
                    },
                    "line": {"type": ["integer", "null"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "suggestion": {"type": ["string", "null"]},
                },
                "required": ["category", "severity", "title", "description"],
                "additionalProperties": False,
            },
        },
        "learning_resources": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["overall_score", "summary", "strengths", "findings", "learning_resources"],
    "additionalProperties": False,
}


def _build_system_prompt(payload: CodeReviewPayload) -> str:
    tone = {
        "beginner": (
            "Adopte un ton pédagogique et encourageant. Explique en détail "
            "les concepts. Célèbre les progrès."
        ),
        "intermediate": (
            "Adopte un ton de mentor. Sois précis, va à l'essentiel, mais "
            "explique le 'pourquoi' derrière chaque remarque."
        ),
        "advanced": (
            "Adopte un ton de senior peer-reviewer. Sois direct, "
            "concentre-toi sur les subtilités et les trade-offs."
        ),
    }[payload.user_level if payload.user_level in ("beginner", "intermediate", "advanced") else "intermediate"]

    return (
        "Tu es un mentor senior en code review pour la plateforme Skilluv "
        "(plateforme gamifiée de démonstration de compétences tech). "
        f"{tone}\n\n"
        "Ta mission : évaluer une soumission de challenge et produire un review "
        "structuré JSON. Le review doit être pédagogique — l'objectif est que "
        "l'utilisateur apprenne, pas juste que tu juges.\n\n"
        "Règles :\n"
        "- overall_score sur 100 : 90+ excellent, 70-89 bien, 50-69 correct, <50 à retravailler\n"
        "- strengths : au moins 1 point positif (motivation)\n"
        "- findings : 3 à 8 remarques concrètes, triées par sévérité décroissante\n"
        "- learning_resources : 1 à 3 pistes concrètes (nom de pattern, doc, article) — pas d'URLs inventées\n"
        "- Si le code est vide/invalide, mets un score bas et explique gentiment\n"
        "- Reste en français (langue de la plateforme)"
    )


def _build_user_prompt(payload: CodeReviewPayload) -> str:
    header = (
        f"# Challenge : {payload.challenge_title}\n"
        f"Difficulté : {payload.difficulty}/5\n"
        f"Langage : {payload.language}\n"
    )
    if payload.challenge_description:
        header += f"\n## Énoncé\n{payload.challenge_description}\n"
    if payload.test_output:
        header += f"\n## Sortie des tests\n```\n{payload.test_output[:2000]}\n```\n"
    header += (
        f"\n## Soumission de l'utilisateur\n"
        f"```{payload.language}\n{payload.source_code[:15000]}\n```\n"
    )
    header += "\nProduis le review au format JSON demandé."
    return header


async def review_code(payload: CodeReviewPayload) -> CodeReviewResult:
    """Review une soumission de code et retourne un CodeReviewResult."""
    logger.info(
        "code_review_started",
        submission_id=payload.submission_id,
        challenge_id=payload.challenge_id,
        language=payload.language,
        code_length=len(payload.source_code),
    )

    if not payload.source_code.strip():
        return CodeReviewResult(
            submission_id=payload.submission_id,
            challenge_id=payload.challenge_id,
            overall_score=0,
            summary="Aucun code soumis.",
            strengths=[],
            findings=[
                CodeReviewFinding(
                    category="bug",
                    severity="critical",
                    title="Soumission vide",
                    description="Aucun code n'a été soumis pour évaluation.",
                    suggestion="Recommence en remplissant l'éditeur.",
                )
            ],
        )

    # PREMIUM tier : Opus 4.7 côté Claude, Qwen 14B/32B côté Ollama.
    # Analyse profonde requise pour un review pédagogique de qualité.
    data = await get_llm().complete_structured(
        tier=ModelTier.PREMIUM,
        system=_build_system_prompt(payload),
        user=_build_user_prompt(payload),
        schema=_REVIEW_SCHEMA,
        max_tokens=8000,
    )

    findings = [CodeReviewFinding.model_validate(f) for f in data.get("findings", [])]

    # Bonus fragments corrélé au score : +0 si <50, jusqu'à +5 si >=90.
    score = int(data.get("overall_score", 0))
    if score >= 90:
        fragments_bonus = 5
    elif score >= 75:
        fragments_bonus = 3
    elif score >= 60:
        fragments_bonus = 1
    else:
        fragments_bonus = 0

    result = CodeReviewResult(
        submission_id=payload.submission_id,
        challenge_id=payload.challenge_id,
        overall_score=score,
        summary=data.get("summary", ""),
        strengths=data.get("strengths", []),
        findings=findings,
        learning_resources=data.get("learning_resources", []),
        fragments_bonus=fragments_bonus,
    )

    logger.info(
        "code_review_completed",
        submission_id=payload.submission_id,
        score=score,
        findings_count=len(findings),
        fragments_bonus=fragments_bonus,
    )
    return result
