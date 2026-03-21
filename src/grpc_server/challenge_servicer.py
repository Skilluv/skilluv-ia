"""Implémentation du service gRPC ChallengeService."""

import json

import grpc

from src.models.challenge import ChallengeParams
from src.services.challenge_generator import generate_challenge
from src.utils.logging import get_logger

logger = get_logger("grpc.challenge_servicer")


class ChallengeServiceServicer:
    """Servicer gRPC pour la génération et validation de challenges.

    Fonctionne avec les stubs générés (challenge_pb2_grpc) ou en mode manuel
    via _manual_handler quand les stubs ne sont pas encore compilés.
    """

    async def GenerateChallenge(self, request, context):
        """Génère un challenge complet à partir des paramètres."""
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
        """Valide la cohérence d'un challenge existant."""
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
