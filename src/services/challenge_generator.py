"""Service de génération de challenges via Claude API."""

import json

import anthropic

from src.config import settings
from src.exceptions import ExternalServiceError, ValidationError
from src.models.challenge import ChallengeParams, GeneratedChallenge
from src.utils.logging import get_logger
from src.utils.metrics import external_errors_total

logger = get_logger("service.challenge_generator")

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def _build_system_prompt(params: ChallengeParams) -> str:
    """Construit le prompt système pour la génération de challenges."""
    lang = "français" if params.language == "fr" else "English"

    tone_guide = {
        "serious": "Ton professionnel et technique. Le challenge doit ressembler à un vrai problème d'entreprise.",
        "fun": "Ton décontracté et motivant. Le challenge doit donner envie de coder avec des métaphores créatives.",
        "absurd": "Ton absurde et décalé. Le challenge doit être drôle et surprenant tout en restant techniquement rigoureux.",
    }

    domain_guide = {
        "code": "Challenge de programmation avec des test cases automatisés.",
        "design": "Challenge de design UI/UX avec critères visuels et d'ergonomie.",
        "game": "Challenge de développement de jeu (mécanique, gameplay, rendu).",
        "security": "Challenge de sécurité/CTF (vulnérabilités, cryptographie, forensics).",
    }

    return f"""Tu es le générateur de challenges de Skilluv, une plateforme gamifiée africaine où les talents prouvent leurs compétences par la pratique.

RÈGLES ABSOLUES :
- Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après
- Langue du contenu : {lang}
- Le challenge doit être réalisable dans le temps imparti ({params.duration_minutes} minutes)
- Difficulté {params.difficulty}/5 : {"débutant, concepts de base" if params.difficulty == 1 else "intermédiaire facile" if params.difficulty == 2 else "intermédiaire, patterns courants" if params.difficulty == 3 else "avancé, optimisation et edge cases" if params.difficulty == 4 else "expert, algorithmes complexes et architecture"}
- Mode : {params.mode}
- IA autorisée pour le candidat : {"oui" if params.ai_allowed else "non — le challenge doit tester des compétences que l'IA ne peut pas résoudre trivialement"}

DOMAINE : {domain_guide.get(params.skill_domain, domain_guide["code"])}

TON : {tone_guide.get(params.tone, tone_guide["serious"])}

{f"Langage de programmation imposé : {params.programming_language}" if params.programming_language else "Le candidat choisit son langage de programmation."}
{f"Tags thématiques à intégrer : {', '.join(params.tags)}" if params.tags else ""}

FORMAT JSON ATTENDU :
{{
  "title": "Titre court et accrocheur",
  "description": "Énoncé complet en markdown. Contexte, problème, exemples.",
  "instructions": "Instructions pas-à-pas pour réaliser le challenge.",
  "starter_code": "Code de départ fourni au candidat (ou null si aucun)",
  "test_cases": [
    {{
      "input": "entrée du test",
      "expected_output": "sortie attendue",
      "description": "Ce que ce test vérifie",
      "is_hidden": false
    }}
  ],
  "evaluation_criteria": "Critères d'évaluation détaillés",
  "tags": ["tag1", "tag2"]
}}

EXIGENCES TEST CASES :
- Minimum 3 tests visibles + 2 tests cachés pour difficulté ≤ 3
- Minimum 3 tests visibles + 4 tests cachés pour difficulté > 3
- Les tests cachés doivent couvrir les edge cases
- Chaque test doit avoir un input/output clair et vérifiable automatiquement"""


def _build_user_prompt(params: ChallengeParams) -> str:
    """Construit le prompt utilisateur."""
    lang = "français" if params.language == "fr" else "English"
    return (
        f"Génère un challenge {params.skill_domain} de difficulté {params.difficulty}/5, "
        f"réalisable en {params.duration_minutes} minutes, "
        f"ton {params.tone}, mode {params.mode}, "
        f"en {lang}."
    )


def _calculate_fragment_reward(params: ChallengeParams) -> int:
    """Calcule la récompense en fragments : difficulté × durée_factor × complexité."""
    duration_factor = max(1, params.duration_minutes // 15)
    complexity = 1 + (0.5 if params.tone == "absurd" else 0) + (0.3 if not params.ai_allowed else 0)
    return int(params.difficulty * duration_factor * complexity)


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

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=_build_system_prompt(params),
            messages=[{"role": "user", "content": _build_user_prompt(params)}],
        )
    except anthropic.APIError as e:
        external_errors_total.labels(service="claude_api").inc()
        raise ExternalServiceError(
            f"Claude API error: {e.message}",
            {"status_code": getattr(e, "status_code", None)},
        ) from e

    # Extraire le JSON de la réponse
    raw_text = response.content[0].text.strip()

    # Nettoyer si Claude enveloppe dans ```json ... ```
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3].strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValidationError(
            "Claude a retourné un JSON invalide",
            {"raw_response": raw_text[:500], "error": str(e)},
        ) from e

    # Construire le challenge complet
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
