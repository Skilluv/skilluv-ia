"""Serveur gRPC pour le service ChallengeService."""

import grpc
from grpc import aio

from src.config import settings
from src.grpc_server.challenge_servicer import ChallengeServiceServicer
from src.utils.logging import get_logger

logger = get_logger("grpc_server")


async def serve() -> None:
    """Démarre le serveur gRPC sur le port configuré."""
    server = aio.server()

    # Enregistrer le servicer
    servicer = ChallengeServiceServicer()

    # Import dynamique des stubs générés
    try:
        from src.grpc_server.generated import challenge_pb2_grpc

        challenge_pb2_grpc.add_ChallengeServiceServicer_to_server(servicer, server)
    except ImportError:
        logger.warning(
            "grpc_stubs_not_generated",
            hint="Run: bash scripts/generate_proto.sh",
        )
        # Fallback: enregistrer le servicer manuellement via generic handler
        from src.grpc_server._manual_handler import add_manual_handlers

        add_manual_handlers(servicer, server)

    listen_addr = f"0.0.0.0:{settings.grpc_port}"
    server.add_insecure_port(listen_addr)

    logger.info("grpc_server_started", port=settings.grpc_port)
    await server.start()
    await server.wait_for_termination()
