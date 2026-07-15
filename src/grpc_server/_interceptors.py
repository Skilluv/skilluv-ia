"""Interceptors gRPC pour instrumentation Prometheus (M5.1).

Un seul interceptor `MetricsInterceptor` qui mesure la latence de chaque
RPC et incrémente le compteur `grpc_requests_total` avec le status final.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import grpc
from grpc.aio import ServerInterceptor

from src.utils.logging import get_logger
from src.utils.metrics import grpc_request_duration_seconds, grpc_requests_total

logger = get_logger("grpc.interceptor")


class MetricsInterceptor(ServerInterceptor):
    """Enregistre latence + succès/échec pour chaque RPC."""

    async def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], Awaitable[grpc.RpcMethodHandler]],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler:
        method = handler_call_details.method  # ex: '/skilluv.ai.v2.CodeReviewService/ReviewCode'
        handler = await continuation(handler_call_details)
        if handler is None:
            return handler

        # On ne wrap que le unary_unary — c'est le seul mode utilisé par le contrat MVP.
        if handler.unary_unary is None:
            return handler

        original_rpc = handler.unary_unary

        async def wrapper(request: Any, context: grpc.aio.ServicerContext) -> Any:
            start = time.perf_counter()
            status = "ok"
            try:
                response = await original_rpc(request, context)
                return response
            except Exception:
                status = "error"
                raise
            finally:
                elapsed = time.perf_counter() - start
                grpc_request_duration_seconds.labels(method=method).observe(elapsed)
                grpc_requests_total.labels(method=method, status=status).inc()

        return grpc.unary_unary_rpc_method_handler(
            wrapper,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


__all__ = ["MetricsInterceptor"]
