"""Implémentation du service gRPC ChallengeService.

DEPRECATED — v1 legacy. Migré vers `skilluv.ai.v2.ChallengeGenerationService`
depuis IA-M2. Ce servicer reste enregistré pour catcher les callers non
migrés ; chaque appel log `grpc_v1_call_detected` avec le peer pour repérage.
Retrait planifié M+2 si aucun warning en prod pendant 30 j.
"""

import json

import grpc

from src.models.challenge import ChallengeParams
from src.services.challenge_generator import generate_challenge
from src.utils.logging import get_logger

logger = get_logger("grpc.challenge_servicer")


def _log_deprecated_call(context, method: str) -> None:
    """Log warn structuré pour repérer les callers v1 encore actifs."""
    peer = None
    try:
        peer = context.peer() if context is not None else None
    except Exception:
        peer = None
    logger.warning(
        "grpc_v1_call_detected",
        method=method,
        peer=peer,
        migration_path="skilluv.ai.v2.ChallengeGenerationService",
    )


class ChallengeServiceServicer:
    """Servicer gRPC v1 legacy (DEPRECATED, voir docstring module)."""

    async def GenerateChallenge(self, request, context):
        """Génère un challenge complet à partir des paramètres. v1 DEPRECATED."""
        _log_deprecated_call(context, "GenerateChallenge")
        try:
            # Extraire les paramètres du message protobuf
            params = ChallengeParams(
                skill_domain=request.skill_domain,
                difficulty=request.difficulty,
                duration_minutes=request.duration_minutes,
                mode=request.mode or "solo",
                tone=request.tone or "serious",
                ai_allowed=request.ai_allowed,
                language=request.language or "fr",
                tags=list(request.tags),
                programming_language=request.programming_language or None,
            )

            logger.info(
                "grpc_generate_challenge",
                skill_domain=params.skill_domain,
                difficulty=params.difficulty,
            )

            challenge = await generate_challenge(params)

            # Construire la réponse protobuf
            try:
                from src.grpc_server.generated import challenge_pb2

                test_cases = [
                    challenge_pb2.TestCase(
                        input=tc.input,
                        expected_output=tc.expected_output,
                        description=tc.description,
                        is_hidden=tc.is_hidden,
                    )
                    for tc in challenge.test_cases
                ]

                return challenge_pb2.GenerateChallengeResponse(
                    success=True,
                    challenge=challenge_pb2.GeneratedChallenge(
                        title=challenge.title,
                        description=challenge.description,
                        instructions=challenge.instructions,
                        difficulty=challenge.difficulty,
                        duration_minutes=challenge.duration_minutes,
                        skill_domain=challenge.skill_domain,
                        tone=challenge.tone,
                        tags=challenge.tags,
                        starter_code=challenge.starter_code or "",
                        test_cases=test_cases,
                        evaluation_criteria=challenge.evaluation_criteria,
                        fragment_reward=challenge.fragment_reward,
                        ai_allowed=challenge.ai_allowed,
                        language=challenge.language,
                    ),
                    error_message="",
                )
            except ImportError:
                # Mode sans stubs : retourne du JSON sérialisé
                return _json_response(challenge.model_dump())

        except Exception as e:
            logger.error("grpc_generate_challenge_failed", error=str(e))
            await context.abort(grpc.StatusCode.INTERNAL, str(e))

    async def ValidateChallenge(self, request, context):
        """Valide la cohérence d'un challenge existant. v1 DEPRECATED."""
        _log_deprecated_call(context, "ValidateChallenge")
        issues = []

        if not request.title or len(request.title) < 5:
            issues.append("Le titre doit faire au moins 5 caractères")

        if not request.description or len(request.description) < 50:
            issues.append("La description doit faire au moins 50 caractères")

        if not request.test_cases:
            issues.append("Au moins un test case est requis")

        for i, tc in enumerate(request.test_cases):
            if not tc.expected_output:
                issues.append(f"Test case {i + 1}: expected_output manquant")

        try:
            from src.grpc_server.generated import challenge_pb2

            return challenge_pb2.ValidateChallengeResponse(
                valid=len(issues) == 0,
                issues=issues,
            )
        except ImportError:
            return _json_response({"valid": len(issues) == 0, "issues": issues})


def _json_response(data: dict) -> object:
    """Fallback quand les stubs proto ne sont pas générés."""

    class JsonResponse:
        def __init__(self, d: dict):
            self._data = d

        def SerializeToString(self) -> bytes:
            return json.dumps(self._data).encode()

    return JsonResponse(data)
