"""gRPC servicer for ChallengeGenerationService v2 (MVP phase IA-M4).

Expose `GenerateChallenge` et `GenerateVariant` sur le nouveau proto v2.
Le legacy v1 (`ChallengeService` sur challenge.proto) reste actif jusqu'en M6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.exceptions import ExternalServiceError, ValidationError
from src.grpc_server.generated import skilluv_ai_pb2 as pb2
from src.grpc_server.generated import skilluv_ai_pb2_grpc as pb2_grpc
from src.llm import ModelTier, get_llm
from src.models.challenge import ChallengeParams, GeneratedChallenge, TestCase
from src.services.challenge_generator import generate_challenge, generate_variant
from src.utils.logging import get_logger

if TYPE_CHECKING:
    import grpc

logger = get_logger("grpc.challenge_generation_servicer")

def _model_version() -> str:
    """Nom du modèle actif pour ChallengeGeneration (provider-dependent)."""
    return get_llm().model_for_tier(ModelTier.STANDARD)


# --- proto <-> pydantic --------------------------------------------------


def _build_params(request: pb2.GenerateChallengeRequest) -> ChallengeParams:
    return ChallengeParams(
        skill_domain=request.skill_domain,
        difficulty=request.difficulty or 1,
        duration_minutes=request.duration_minutes or 30,
        mode=request.mode or "solo",
        tone=request.tone or "serious",
        ai_allowed=bool(request.ai_allowed),
        language=request.language or "fr",
        tags=list(request.tags),
        programming_language=request.programming_language or None,
        # Champs v2 (P16) — consommés par _challenge_prompts.py :
        # - orientation_slug biaise le contexte skill (via catalogue)
        # - is_training abaisse la difficulté effective d'un cran + guide plus
        # - project_id ancre le contexte OSS
        orientation_slug=request.orientation_slug or "",
        is_training=bool(request.is_training),
        project_id=request.project_id or "",
    )


def _generated_to_proto(challenge: GeneratedChallenge) -> pb2.GeneratedChallenge:
    proto_msg = pb2.GeneratedChallenge(
        title=challenge.title,
        description=challenge.description,
        instructions=challenge.instructions,
        difficulty=challenge.difficulty,
        duration_minutes=challenge.duration_minutes,
        skill_domain=challenge.skill_domain,
        tone=challenge.tone,
        tags=list(challenge.tags),
        starter_code=challenge.starter_code or "",
        evaluation_criteria=challenge.evaluation_criteria,
        fragment_reward=challenge.fragment_reward,
        ai_allowed=challenge.ai_allowed,
        language=challenge.language,
    )
    for tc in challenge.test_cases:
        proto_msg.test_cases.add(
            input=tc.input if isinstance(tc, TestCase) else tc.get("input", ""),
            expected_output=(
                tc.expected_output if isinstance(tc, TestCase) else tc.get("expected_output", "")
            ),
            description=(
                tc.description if isinstance(tc, TestCase) else tc.get("description", "")
            ),
            is_hidden=(
                tc.is_hidden if isinstance(tc, TestCase) else bool(tc.get("is_hidden", False))
            ),
        )
    return proto_msg


def _proto_original_to_pydantic(proto_original: pb2.GeneratedChallenge) -> GeneratedChallenge:
    return GeneratedChallenge(
        title=proto_original.title,
        description=proto_original.description,
        instructions=proto_original.instructions,
        difficulty=proto_original.difficulty or 1,
        duration_minutes=proto_original.duration_minutes or 30,
        skill_domain=proto_original.skill_domain or "code",
        tone=proto_original.tone or "serious",
        tags=list(proto_original.tags),
        starter_code=proto_original.starter_code or None,
        test_cases=[
            TestCase(
                input=tc.input,
                expected_output=tc.expected_output,
                description=tc.description,
                is_hidden=bool(tc.is_hidden),
            )
            for tc in proto_original.test_cases
        ],
        evaluation_criteria=proto_original.evaluation_criteria,
        fragment_reward=proto_original.fragment_reward or 0,
        ai_allowed=bool(proto_original.ai_allowed),
        language=proto_original.language or "fr",
    )


# --- servicer -------------------------------------------------------------


class ChallengeGenerationServicer(pb2_grpc.ChallengeGenerationServiceServicer):
    async def GenerateChallenge(
        self,
        request: pb2.GenerateChallengeRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.GenerateChallengeResponse:
        try:
            params = _build_params(request)
        except Exception as e:
            return pb2.GenerateChallengeResponse(
                success=False, error_message=f"invalid params: {e}", model_version=_model_version(),
            )
        logger.info(
            "grpc_generate_challenge_received",
            skill_domain=params.skill_domain,
            difficulty=params.difficulty,
            language=params.language,
        )
        try:
            challenge = await generate_challenge(params)
        except ExternalServiceError as e:
            return pb2.GenerateChallengeResponse(
                success=False, error_message=str(e), model_version=_model_version(),
            )
        except ValidationError as e:
            return pb2.GenerateChallengeResponse(
                success=False, error_message=str(e), model_version=_model_version(),
            )
        return pb2.GenerateChallengeResponse(
            success=True,
            challenge=_generated_to_proto(challenge),
            model_version=_model_version(),
        )

    async def GenerateVariant(
        self,
        request: pb2.GenerateVariantRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.GenerateChallengeResponse:
        if not request.original.title:
            return pb2.GenerateChallengeResponse(
                success=False,
                error_message="original challenge must be provided inline",
                model_version=_model_version(),
            )
        original = _proto_original_to_pydantic(request.original)
        logger.info(
            "grpc_generate_variant_received",
            variant_type=request.variant_type,
            original_title=original.title,
            target_param=request.target_param,
        )
        try:
            variant = await generate_variant(
                original=original,
                variant_type=request.variant_type,
                target_param=request.target_param,
            )
        except ValidationError as e:
            return pb2.GenerateChallengeResponse(
                success=False, error_message=str(e), model_version=_model_version(),
            )
        except ExternalServiceError as e:
            return pb2.GenerateChallengeResponse(
                success=False, error_message=str(e), model_version=_model_version(),
            )
        return pb2.GenerateChallengeResponse(
            success=True,
            challenge=_generated_to_proto(variant),
            model_version=_model_version(),
        )


__all__ = ["ChallengeGenerationServicer"]
