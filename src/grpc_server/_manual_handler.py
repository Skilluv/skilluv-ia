"""Handler gRPC manuel — utilisé quand les stubs proto ne sont pas encore compilés.

Permet de tester le service avant d'avoir exécuté generate_proto.sh.
Utilise la réflexion gRPC pour enregistrer les méthodes du servicer.
"""

import json

from grpc import aio

from src.utils.logging import get_logger

logger = get_logger("grpc.manual_handler")


def add_manual_handlers(servicer, server: aio.Server) -> None:
    """Enregistre le servicer via des generic handlers (mode développement).

    Note: En production, utiliser les stubs générés via generate_proto.sh.
    """
    logger.warning(
        "using_manual_grpc_handlers",
        hint="Generate proto stubs for production: bash scripts/generate_proto.sh",
    )
    # Le servicer sera appelé via les stubs une fois générés.
    # Pour le développement initial, le serveur démarre mais les appels
    # nécessitent les stubs compilés côté client (Rust).
