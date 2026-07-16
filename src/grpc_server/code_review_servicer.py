"""gRPC servicer for CodeReviewService (MVP phase IA-M2).

Wrappe `services.code_reviewer.review_code` (async, Claude Opus 4.7) et
mappe le résultat pydantic sur le message `CodeReviewResponse` v2.

Le service métier existe déjà (utilisé par worker ARQ). Ce servicer expose
la même logique en synchrone gRPC pour que le backend Rust puisse
appeler `AiClient::review_code` sans passer par la queue.
"""

from __future__ import annotations

import grpc

from src.exceptions import ExternalServiceError, ValidationError
from src.llm import ModelTier, get_llm
from src.models.code_review import CodeReviewPayload, CodeReviewResult
from src.services.code_reviewer import review_code
from src.utils.logging import get_logger

from src.grpc_server.generated import skilluv_ai_pb2 as pb2
from src.grpc_server.generated import skilluv_ai_pb2_grpc as pb2_grpc

logger = get_logger("grpc.code_review_servicer")


# Mapping internal severity (Claude/pydantic) -> proto severity vocabulary.
# Internal: info | low | medium | high | critical
# Proto:    blocker | critical | major | minor
_SEVERITY_MAP = {
    "critical": "critical",
    "high": "major",
    "medium": "major",
    "low": "minor",
    "info": "minor",
}

def _model_version() -> str:
    """Nom du modèle actif pour ReviewCode (provider-dependent).

    Retourné dans la réponse gRPC pour audit — permet au backend de tracer
    quel modèle a produit quel review (§MVP.md 0.5).
    """
    return get_llm().model_for_tier(ModelTier.PREMIUM)


def _build_payload(request: pb2.CodeReviewRequest) -> CodeReviewPayload:
    return CodeReviewPayload(
        submission_id=request.submission_id,
        # Proto ne transporte pas challenge_id : on réutilise submission_id
        # comme clé d'observabilité (le service ne fait aucune lookup dessus).
        challenge_id=request.submission_id,
        user_id="",
        language=request.language or "text",
        source_code=request.code,
        challenge_title=request.challenge_title,
        challenge_description=request.challenge_instructions,
        difficulty=request.difficulty or 1,
    )


def _to_response(result: CodeReviewResult) -> pb2.CodeReviewResponse:
    response = pb2.CodeReviewResponse(
        quality_score=result.overall_score,
        summary=result.summary,
        strengths=list(result.strengths),
        # Backend cap à 3 côté Rust ; on envoie tout ce qu'on a, tri déjà fait.
        improvements=[f.suggestion for f in result.findings if f.suggestion],
        model_version=_model_version(),
    )
    for finding in result.findings:
        message = finding.title
        if finding.description:
            message = f"{finding.title} — {finding.description}"
        response.issues.add(
            severity=_SEVERITY_MAP.get(finding.severity, "minor"),
            category=finding.category,
            message=message,
            line_number=finding.line or 0,
        )
    for res in result.learning_resources:
        # Le service actuel retourne des strings libres, pas d'URL structurée.
        response.resources.add(title=res, url="", kind="doc")
    return response


class CodeReviewServicer(pb2_grpc.CodeReviewServiceServicer):
    """gRPC front pour le code reviewer pédagogique."""

    async def ReviewCode(
        self,
        request: pb2.CodeReviewRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.CodeReviewResponse:
        payload = _build_payload(request)
        logger.info(
            "grpc_review_code_received",
            submission_id=payload.submission_id,
            language=payload.language,
            code_length=len(payload.source_code),
        )
        try:
            result = await review_code(payload)
        except ExternalServiceError as e:
            logger.error("grpc_review_code_external_error", error=str(e))
            await context.abort(grpc.StatusCode.UNAVAILABLE, f"llm upstream: {e}")
        except ValidationError as e:
            logger.error("grpc_review_code_validation_error", error=str(e))
            await context.abort(grpc.StatusCode.INTERNAL, f"llm invalid output: {e}")
        return _to_response(result)


__all__ = ["CodeReviewServicer"]
