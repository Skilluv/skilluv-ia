"""gRPC servicer for PlagiarismService (MVP phase IA-M2).

Wrappe `services.plagiarism_detector.detect_plagiarism` (AST + embeddings) et
mappe les résultats sur `CheckPlagiarismResponse` v2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.grpc_server.generated import skilluv_ai_pb2 as pb2
from src.grpc_server.generated import skilluv_ai_pb2_grpc as pb2_grpc
from src.models.queue_messages import PlagiarismPayload, PlagiarismSubmission
from src.services.plagiarism_detector import detect_plagiarism
from src.utils.logging import get_logger

if TYPE_CHECKING:
    import grpc

    from src.models.job_results import PlagiarismMatch, PlagiarismResult

logger = get_logger("grpc.plagiarism_servicer")

_MODEL_VERSION = "ast+embedding-v1"


def _build_payload(request: pb2.CheckPlagiarismRequest) -> PlagiarismPayload:
    submissions = [
        PlagiarismSubmission(
            submission_id=prev.submission_id,
            # Le proto n'a pas user_id : le service métier l'ignore côté logique
            # et le renvoie tel quel dans la réponse. On met vide.
            user_id="",
            source_code=prev.code,
        )
        for prev in request.comparison_pool
    ]
    return PlagiarismPayload(
        submission_id=request.submission_id,
        # Idem que CodeReview : pas de challenge_id transporté, on utilise
        # submission_id comme clé de trace.
        challenge_id=request.submission_id,
        source_code=request.code,
        language=request.language or "text",
        compare_with=submissions,
    )


def _pick_top_match(result: PlagiarismResult) -> PlagiarismMatch | None:
    if not result.matches:
        return None
    return max(result.matches, key=lambda m: m.combined_score)


def _to_response(
    result: PlagiarismResult, threshold: float
) -> pb2.CheckPlagiarismResponse:
    top = _pick_top_match(result)
    # Le "is_plagiarism" côté proto respecte le threshold du client si fourni,
    # sinon le flagged du service (basé sur settings.plagiarism_threshold).
    is_plagiarism = result.highest_score >= threshold if threshold > 0 else result.flagged
    return pb2.CheckPlagiarismResponse(
        similarity_score=result.highest_score,
        similar_submission_id=top.compared_submission_id if top else "",
        ast_similarity=top.ast_similarity if top else 0.0,
        embedding_similarity=top.embedding_similarity if top else 0.0,
        is_plagiarism=is_plagiarism,
        model_version=_MODEL_VERSION,
    )


class PlagiarismServicer(pb2_grpc.PlagiarismServiceServicer):
    async def CheckPlagiarism(
        self,
        request: pb2.CheckPlagiarismRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb2.CheckPlagiarismResponse:
        payload = _build_payload(request)
        logger.info(
            "grpc_plagiarism_received",
            submission_id=payload.submission_id,
            candidates=len(payload.compare_with),
            threshold_override=request.threshold if request.threshold > 0 else None,
        )
        result = await detect_plagiarism(payload)
        response = _to_response(result, request.threshold)
        logger.info(
            "grpc_plagiarism_completed",
            submission_id=payload.submission_id,
            similarity_score=response.similarity_score,
            is_plagiarism=response.is_plagiarism,
        )
        return response


__all__ = ["PlagiarismServicer"]
