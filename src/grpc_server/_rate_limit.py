"""Rate-limiting interceptor gRPC (in-memory, per-peer + per-method).

Protège le budget Claude d'un backend compromis ou d'un run pathologique. Chaque
méthode a un budget/minute distinct (ReviewCode plus strict car Opus coûteux).

Design :
- Token bucket : `capacity` tokens, refill à `capacity / 60s` tokens/s.
- Clé : `(peer, method)`. `peer` = IP côté serveur.
- État in-memory (pas de Redis) : perte au restart = OK, la protection est
  contre les burst court terme, pas les abus long terme (qui doivent être
  détectés par Prometheus + alerte).

Fail-open : si l'introspection du peer échoue, on laisse passer (pas de
surprise si l'infra change).

RESOURCE_EXHAUSTED est le code gRPC standard côté client.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import grpc
from grpc.aio import ServerInterceptor

from src.utils.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = get_logger("grpc.rate_limit")


# Budgets par méthode (appels/minute par peer). Cohérents avec MVP.md §0.6
# (usage attendu) et une marge x3 pour absorber les pics légitimes.
DEFAULT_BUDGETS: dict[str, int] = {
    # Opus 4.7, ~$0.05/appel → cap serré
    "/skilluv.ai.v2.CodeReviewService/ReviewCode": 30,
    # Sonnet 4.6, moins coûteux mais reste LLM
    "/skilluv.ai.v2.ChallengeGenerationService/GenerateChallenge": 60,
    "/skilluv.ai.v2.ChallengeGenerationService/GenerateVariant": 60,
    "/skilluv.ai.v2.TalentDetectionService/AnalyzePerformance": 60,
    # Haiku 4.5, bon marché — laisser large
    "/skilluv.ai.v2.TalentDetectionService/SuggestCareerPath": 120,
    # Déterministe, coût = CPU. Cap plus large.
    "/skilluv.ai.v2.PlagiarismService/CheckPlagiarism": 60,
}


@dataclass
class _Bucket:
    tokens: float
    last_refill: float = field(default_factory=time.monotonic)


class RateLimitInterceptor(ServerInterceptor):
    def __init__(self, budgets: dict[str, int] | None = None) -> None:
        self._budgets = budgets or DEFAULT_BUDGETS
        self._buckets: dict[tuple[str, str], _Bucket] = {}

    def _peer_of(self, context: grpc.aio.ServicerContext) -> str:
        try:
            peer = context.peer() or "unknown"
            # tonic/grpcurl retournent 'ipv4:1.2.3.4:5678' → on garde l'IP
            if peer.startswith("ipv4:") or peer.startswith("ipv6:"):
                peer = peer.split(":", 1)[1].rsplit(":", 1)[0]
            return peer
        except Exception:
            return "unknown"

    def _check_and_consume(self, peer: str, method: str) -> bool:
        capacity = self._budgets.get(method)
        if capacity is None:
            # Méthodes non listées (health, reflection) : pas de limite.
            return True
        refill_rate = capacity / 60.0  # tokens / seconde
        now = time.monotonic()
        bucket = self._buckets.get((peer, method))
        if bucket is None:
            bucket = _Bucket(tokens=float(capacity))
            self._buckets[(peer, method)] = bucket
        # Refill
        elapsed = now - bucket.last_refill
        bucket.tokens = min(float(capacity), bucket.tokens + elapsed * refill_rate)
        bucket.last_refill = now
        # Consume
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True
        return False

    async def intercept_service(
        self,
        continuation: Callable[[grpc.HandlerCallDetails], Awaitable[grpc.RpcMethodHandler]],
        handler_call_details: grpc.HandlerCallDetails,
    ) -> grpc.RpcMethodHandler:
        method = handler_call_details.method
        handler = await continuation(handler_call_details)
        if handler is None or handler.unary_unary is None:
            return handler

        original_rpc = handler.unary_unary
        interceptor = self

        async def wrapper(request, context: grpc.aio.ServicerContext):
            peer = interceptor._peer_of(context)
            if not interceptor._check_and_consume(peer, method):
                logger.warning(
                    "rate_limit_exceeded",
                    peer=peer,
                    method=method,
                    budget_per_min=interceptor._budgets.get(method),
                )
                await context.abort(
                    grpc.StatusCode.RESOURCE_EXHAUSTED,
                    f"Rate limit exceeded for {method} (per-peer budget)",
                )
            return await original_rpc(request, context)

        return grpc.unary_unary_rpc_method_handler(
            wrapper,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


__all__ = ["RateLimitInterceptor", "DEFAULT_BUDGETS"]
