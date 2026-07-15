"""M6.1 — Test du gRPC health check standard.

Le service `grpc.health.v1.Health` doit répondre SERVING pour le service global
et pour chacun des 4 services v2. Utilisé par Docker HEALTHCHECK et K8s probes.
"""

from __future__ import annotations

import pytest
from grpc import aio
from grpc_health.v1 import health_pb2, health_pb2_grpc

from src.grpc_server.server import V2_SERVICE_NAMES, register_all_servicers


@pytest.mark.asyncio
async def test_health_check_reports_serving_globally():
    server = aio.server()
    register_all_servicers(server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = health_pb2_grpc.HealthStub(channel)
            response = await stub.Check(
                health_pb2.HealthCheckRequest(service=""), timeout=5,
            )
        assert response.status == health_pb2.HealthCheckResponse.SERVING
    finally:
        await server.stop(grace=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("service", V2_SERVICE_NAMES)
async def test_health_check_per_service_reports_serving(service: str):
    server = aio.server()
    register_all_servicers(server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = health_pb2_grpc.HealthStub(channel)
            response = await stub.Check(
                health_pb2.HealthCheckRequest(service=service), timeout=5,
            )
        assert response.status == health_pb2.HealthCheckResponse.SERVING, (
            f"{service} devrait être SERVING"
        )
    finally:
        await server.stop(grace=None)
