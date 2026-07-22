"""Item 26 — couverture élargie des services qui utilisent Redis en vrai.

Complète `test_redis_integration.py` (raw ops SET/GET/PUBSUB) par des scénarios
haut-niveau qui exercent les modules `_challenge_cache`, `_talent_cache`, et le
singleton `get_redis()` contre un vrai Docker Redis.

Prérequis :
    docker compose up -d redis

Skip auto si `REDIS_URL` inaccessible (voir conftest.py).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
import pytest_asyncio

from src.models.challenge import ChallengeParams, GeneratedChallenge, TestCase
from src.models.talent_analysis import (
    AnalyzePerformancePayload,
    AnalyzePerformanceResult,
    OrientationSnapshot,
    RankReadiness,
    SkillSnapshot,
)
from src.services import _challenge_cache, _talent_cache
from src.utils.redis_client import get_redis

if TYPE_CHECKING:
    from redis.asyncio import Redis


@pytest_asyncio.fixture(autouse=True)
async def _override_redis(monkeypatch, redis_client: Redis):
    """Force `get_redis()` à retourner le client Redis du fixture.

    Sans ça, les services créeraient leur propre connexion sur `settings.redis_url`
    (peut être différent du REDIS_URL du fixture en CI).
    """
    from src.utils import redis_client as redis_module

    monkeypatch.setattr(redis_module, "_redis", redis_client)

    async def _returns_fixture() -> Redis:
        return redis_client

    monkeypatch.setattr(redis_module, "get_redis", _returns_fixture)
    monkeypatch.setattr(_challenge_cache, "get_redis", _returns_fixture)
    monkeypatch.setattr(_talent_cache, "get_redis", _returns_fixture)
    yield


def _sample_params(**overrides: Any) -> ChallengeParams:
    base: dict[str, Any] = {
        "skill_domain": "code",
        "difficulty": 3,
        "duration_minutes": 30,
        "mode": "solo",
        "tone": "serious",
        "ai_allowed": True,
        "language": "fr",
        "tags": ["python", "test"],
        "programming_language": "python",
    }
    base.update(overrides)
    return ChallengeParams(**base)


def _sample_challenge(title: str = "Test challenge") -> GeneratedChallenge:
    return GeneratedChallenge(
        title=title,
        description="Description du test challenge (>=50 caractères pour valider Pydantic).",
        instructions="Faire quelque chose de simple.",
        difficulty=3,
        duration_minutes=30,
        skill_domain="code",
        mode="solo",
        tone="serious",
        tags=["python", "test"],
        starter_code="def solve(): pass",
        test_cases=[TestCase(input="1", expected_output="1", description="Cas basique")],
        evaluation_criteria="Doit passer les tests unitaires.",
        fragment_reward=10,
        ai_allowed=True,
        language="fr",
    )


# ═══════════════════════════════════════════════════════════════════
# _challenge_cache — vrai roundtrip Redis
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_challenge_cache_miss_then_hit(redis_client: Redis) -> None:
    params = _sample_params(tags=["cache-miss-hit"])

    # Miss initial : rien en cache.
    got = await _challenge_cache.get_cached_challenge(params)
    assert got is None

    # Écriture, puis hit.
    challenge = _sample_challenge(title="Cached A")
    await _challenge_cache.cache_challenge(params, challenge)

    got2 = await _challenge_cache.get_cached_challenge(params)
    assert got2 is not None
    assert got2.title == "Cached A"


@pytest.mark.asyncio
async def test_challenge_cache_key_depends_on_v2_fields(redis_client: Redis) -> None:
    """Deux paramètres identiques mais orientation_slug différente = cache différent.

    Régression #31 : sinon collision entre challenges (même params mais
    orientation ou training différents).
    """
    base = _sample_params(tags=["v2-fields"])
    orient_a = _sample_params(tags=["v2-fields"], orientation_slug="dev-frontend")
    orient_b = _sample_params(tags=["v2-fields"], orientation_slug="dev-backend")

    await _challenge_cache.cache_challenge(base, _sample_challenge("Base"))
    await _challenge_cache.cache_challenge(orient_a, _sample_challenge("Frontend"))
    await _challenge_cache.cache_challenge(orient_b, _sample_challenge("Backend"))

    got_base = await _challenge_cache.get_cached_challenge(base)
    got_a = await _challenge_cache.get_cached_challenge(orient_a)
    got_b = await _challenge_cache.get_cached_challenge(orient_b)
    assert got_base is not None and got_base.title == "Base"
    assert got_a is not None and got_a.title == "Frontend"
    assert got_b is not None and got_b.title == "Backend"


@pytest.mark.asyncio
async def test_challenge_cache_skips_absurd_tone(redis_client: Redis) -> None:
    """`tone == 'absurd'` = jamais caché (variété garantie)."""
    params = _sample_params(tone="absurd", tags=["absurd-skip"])
    await _challenge_cache.cache_challenge(params, _sample_challenge("Absurd"))

    # La clé n'a jamais été écrite.
    got = await _challenge_cache.get_cached_challenge(params)
    assert got is None


@pytest.mark.asyncio
async def test_challenge_cache_invalidate(redis_client: Redis) -> None:
    params = _sample_params(tags=["invalidate"])
    await _challenge_cache.cache_challenge(params, _sample_challenge("Before invalidate"))
    assert await _challenge_cache.get_cached_challenge(params) is not None

    await _challenge_cache.invalidate_cache(params)
    assert await _challenge_cache.get_cached_challenge(params) is None


@pytest.mark.asyncio
async def test_challenge_cache_stats_counts_only_challenge_keys(redis_client: Redis) -> None:
    # Bruit hors préfixe → ne doit pas apparaître dans stats.
    await redis_client.set("skilluv:noise:x", "1", ex=10)
    await redis_client.set("skilluv:noise:y", "2", ex=10)
    for i in range(3):
        await _challenge_cache.cache_challenge(
            _sample_params(tags=[f"stats-{i}"]),
            _sample_challenge(f"C{i}"),
        )
    stats = await _challenge_cache.get_cache_stats()
    assert stats["cached_challenges"] >= 3


# ═══════════════════════════════════════════════════════════════════
# _talent_cache — hash key stable + roundtrip Pydantic
# ═══════════════════════════════════════════════════════════════════


def _sample_talent_payload(user_id: str = "user-talent-int") -> AnalyzePerformancePayload:
    return AnalyzePerformancePayload(
        user_id=user_id,
        skills=[
            SkillSnapshot(skill_slug="python", wpc_total=100, evidence_count=5),
            SkillSnapshot(skill_slug="sql", wpc_total=50, evidence_count=3),
        ],
        orientations=[
            OrientationSnapshot(orientation_slug="dev-backend", completion_ratio=0.55),
        ],
        current_rank="ranger",
    )


def _sample_talent_result() -> AnalyzePerformanceResult:
    return AnalyzePerformanceResult(
        overall_score=0.72,
        rank_readiness=RankReadiness(current_rank="ranger", next_rank="artisan"),
    )


@pytest.mark.asyncio
async def test_talent_cache_roundtrip(redis_client: Redis) -> None:
    payload = _sample_talent_payload("user-cache-roundtrip")
    result = _sample_talent_result()

    assert await _talent_cache.get_cached_analysis(payload) is None
    await _talent_cache.cache_analysis(payload, result)

    got = await _talent_cache.get_cached_analysis(payload)
    assert got is not None
    assert got.overall_score == pytest.approx(0.72)
    assert got.rank_readiness.next_rank == "artisan"


@pytest.mark.asyncio
async def test_talent_cache_key_stable_across_ordering(redis_client: Redis) -> None:
    """La clé doit être stable quel que soit l'ordre des skills/orientations envoyés."""
    a = AnalyzePerformancePayload(
        user_id="user-order-stable",
        skills=[
            SkillSnapshot(skill_slug="python", wpc_total=100, evidence_count=5),
            SkillSnapshot(skill_slug="sql", wpc_total=50, evidence_count=3),
        ],
        current_rank="ranger",
    )
    b = AnalyzePerformancePayload(
        user_id="user-order-stable",
        skills=[
            SkillSnapshot(skill_slug="sql", wpc_total=50, evidence_count=3),
            SkillSnapshot(skill_slug="python", wpc_total=100, evidence_count=5),
        ],
        current_rank="ranger",
    )
    await _talent_cache.cache_analysis(a, _sample_talent_result())
    assert await _talent_cache.get_cached_analysis(b) is not None, (
        "le cache doit hit même si les skills sont dans un ordre différent"
    )


@pytest.mark.asyncio
async def test_talent_cache_key_differs_on_snapshot_change(redis_client: Redis) -> None:
    """Deux snapshots différents (même user) = clés différentes = pas de hit."""
    a = _sample_talent_payload("user-snapshot-differs")
    b = AnalyzePerformancePayload(
        user_id="user-snapshot-differs",
        skills=[
            SkillSnapshot(skill_slug="python", wpc_total=999, evidence_count=99),
        ],
        current_rank="ranger",
    )
    await _talent_cache.cache_analysis(a, _sample_talent_result())
    assert await _talent_cache.get_cached_analysis(b) is None


# ═══════════════════════════════════════════════════════════════════
# get_redis() — singleton lazy fonctionnel contre un vrai serveur
# ═══════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_get_redis_returns_working_client(redis_client: Redis) -> None:
    """`get_redis()` (via monkeypatch fixture) doit répondre à PING."""
    client = await get_redis()
    pong = await client.ping()
    assert pong is True
