"""Test que la reflection gRPC est active en mode development.

Comportement attendu :
- ENVIRONMENT=development -> reflection ON, `ServerReflectionInfo` répond
- ENVIRONMENT=production -> reflection OFF (schéma non exposé)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from grpc import aio
from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

from src.grpc_server.server import register_all_servicers


async def _call_list_services(channel: aio.Channel) -> list[str]:
    stub = reflection_pb2_grpc.ServerReflectionStub(channel)

    async def request_iter():
        yield reflection_pb2.ServerReflectionRequest(list_services="")

    seen = []
    async for response in stub.ServerReflectionInfo(request_iter()):
        for svc in response.list_services_response.service:
            seen.append(svc.name)
    return seen


@pytest.mark.asyncio
async def test_reflection_lists_v2_services_in_dev():
    with patch("src.grpc_server.server.settings") as mock_settings:
        mock_settings.environment = "development"
        mock_settings.grpc_port = 50051
        server = aio.server()
        register_all_servicers(server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                services = await _call_list_services(channel)
            # Les 4 services v2 doivent être exposés via reflection
            for svc in (
                "skilluv.ai.v2.CodeReviewService",
                "skilluv.ai.v2.ChallengeGenerationService",
                "skilluv.ai.v2.TalentDetectionService",
                "skilluv.ai.v2.PlagiarismService",
            ):
                assert svc in services, f"{svc} manquant : {services}"
        finally:
            await server.stop(grace=None)


@pytest.mark.asyncio
async def test_reflection_disabled_in_production():
    with patch("src.grpc_server.server.settings") as mock_settings:
        mock_settings.environment = "production"
        mock_settings.grpc_port = 50051
        server = aio.server()
        register_all_servicers(server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                # ServerReflectionInfo doit échouer (unimplemented)
                with pytest.raises(Exception):
                    await _call_list_services(channel)
        finally:
            await server.stop(grace=None)
