"""Serveur gRPC skilluv-ai.

Expose :
  - v1 (legacy) : ChallengeService (via proto/challenge.proto, deprecate en IA-M6)
  - v2 (MVP)    : CodeReview + Plagiarism + TalentDetection + ChallengeGeneration
  - grpc.health.v1.Health : healthcheck standard (Docker/K8s)
"""

from grpc import aio
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection

from src.config import settings
from src.grpc_server._interceptors import MetricsInterceptor
from src.grpc_server.challenge_generation_servicer import ChallengeGenerationServicer
from src.grpc_server.challenge_servicer import ChallengeServiceServicer
from src.grpc_server.code_review_servicer import CodeReviewServicer
from src.grpc_server.plagiarism_servicer import PlagiarismServicer
from src.grpc_server.talent_detection_servicer import TalentDetectionServicer
from src.utils.logging import get_logger

logger = get_logger("grpc_server")


V2_SERVICE_NAMES = (
    "skilluv.ai.v2.CodeReviewService",
    "skilluv.ai.v2.ChallengeGenerationService",
    "skilluv.ai.v2.TalentDetectionService",
    "skilluv.ai.v2.PlagiarismService",
)


def register_all_servicers(server: aio.Server) -> None:
    """Enregistre les servicers v1 + v2 + health sur un serveur aio.grpc.

    Extrait pour permettre aux tests d'invoquer sur un serveur ad-hoc sans
    dupliquer le câblage.
    """
    # v1 legacy — ChallengeService
    legacy_servicer = ChallengeServiceServicer()
    try:
        from src.grpc_server.generated import challenge_pb2_grpc

        challenge_pb2_grpc.add_ChallengeServiceServicer_to_server(legacy_servicer, server)
    except ImportError:
        logger.warning(
            "grpc_stubs_v1_not_generated",
            hint="Run: bash scripts/generate_proto.sh",
        )
        from src.grpc_server._manual_handler import add_manual_handlers

        add_manual_handlers(legacy_servicer, server)

    # v2 MVP — 4 services
    try:
        from src.grpc_server.generated import skilluv_ai_pb2_grpc as v2_grpc

        v2_grpc.add_CodeReviewServiceServicer_to_server(CodeReviewServicer(), server)
        v2_grpc.add_PlagiarismServiceServicer_to_server(PlagiarismServicer(), server)
        v2_grpc.add_TalentDetectionServiceServicer_to_server(
            TalentDetectionServicer(), server
        )
        v2_grpc.add_ChallengeGenerationServiceServicer_to_server(
            ChallengeGenerationServicer(), server
        )
        logger.info(
            "grpc_v2_servicers_registered",
            services=["CodeReview", "Plagiarism", "TalentDetection", "ChallengeGeneration"],
        )
    except ImportError:
        logger.error(
            "grpc_stubs_v2_missing",
            hint="Run: bash scripts/generate_proto.sh",
        )
        raise

    # gRPC health check standard (M6.1) — utilisable par Docker HEALTHCHECK,
    # Kubernetes liveness probes, ou grpc_health_probe.
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    for svc in V2_SERVICE_NAMES:
        health_servicer.set(svc, health_pb2.HealthCheckResponse.SERVING)
    logger.info("grpc_health_check_ready")

    # gRPC reflection : ACTIVÉE en dev pour permettre `grpcurl list` sans -proto.
    # Désactivée en prod pour ne pas exposer le schéma au monde entier.
    if settings.environment == "development":
        try:
            from src.grpc_server.generated import (
                skilluv_ai_pb2 as _v2_pb2,
            )
            service_names = tuple(
                _v2_pb2.DESCRIPTOR.services_by_name[name].full_name
                for name in _v2_pb2.DESCRIPTOR.services_by_name
            ) + (
                reflection.SERVICE_NAME,
                health.SERVICE_NAME,
            )
            reflection.enable_server_reflection(service_names, server)
            logger.info("grpc_reflection_enabled", services=list(service_names))
        except Exception as e:
            logger.warning("grpc_reflection_setup_failed", error=str(e))
    else:
        logger.info(
            "grpc_reflection_disabled",
            reason="environment != development (sécurité prod)",
        )


async def serve() -> None:
    """Démarre le serveur gRPC sur le port configuré."""
    server = aio.server(interceptors=[MetricsInterceptor()])
    register_all_servicers(server)

    listen_addr = f"0.0.0.0:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)

    logger.info("grpc_server_started", port=settings.grpc_port)
    await server.start()
    await server.wait_for_termination()
