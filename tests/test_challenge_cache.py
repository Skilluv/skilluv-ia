"""Tests du cache de challenges."""

from unittest.mock import AsyncMock, patch

import pytest

from src.models.challenge import ChallengeParams, GeneratedChallenge, TestCase
from src.services._challenge_cache import (
    _build_cache_key,
    _is_cacheable,
)


def _make_params(**kwargs) -> ChallengeParams:
    defaults = {"skill_domain": "code", "difficulty": 3, "duration_minutes": 30}
    defaults.update(kwargs)
    return ChallengeParams(**defaults)


def _make_challenge() -> GeneratedChallenge:
    return GeneratedChallenge(
        title="Test Challenge",
        description="A test",
        instructions="Do the thing",
        difficulty=3,
        duration_minutes=30,
        skill_domain="code",
        tone="serious",
        tags=["test"],
        test_cases=[
            TestCase(input="1", expected_output="1", description="identity"),
        ],
        evaluation_criteria="correctness",
        fragment_reward=6,
        ai_allowed=False,
        language="fr",
    )


class TestIsCacheable:
    def test_serious_tone_cacheable(self) -> None:
        assert _is_cacheable(_make_params(tone="serious")) is True

    def test_fun_tone_cacheable(self) -> None:
        assert _is_cacheable(_make_params(tone="fun")) is True

    def test_absurd_tone_not_cacheable(self) -> None:
        assert _is_cacheable(_make_params(tone="absurd")) is False


class TestBuildCacheKey:
    def test_deterministic(self) -> None:
        params = _make_params()
        key1 = _build_cache_key(params)
        key2 = _build_cache_key(params)
        assert key1 == key2

    def test_different_params_different_keys(self) -> None:
        key1 = _build_cache_key(_make_params(difficulty=1))
        key2 = _build_cache_key(_make_params(difficulty=5))
        assert key1 != key2

    def test_tag_order_irrelevant(self) -> None:
        key1 = _build_cache_key(_make_params(tags=["a", "b"]))
        key2 = _build_cache_key(_make_params(tags=["b", "a"]))
        assert key1 == key2

    def test_prefix_format(self) -> None:
        key = _build_cache_key(_make_params())
        assert key.startswith("skilluv:cache:challenge:")


class TestCacheIntegration:
    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("src.services._challenge_cache.get_redis", return_value=mock_redis):
            from src.services._challenge_cache import get_cached_challenge

            result = await get_cached_challenge(_make_params())
            assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_returns_challenge(self) -> None:
        challenge = _make_challenge()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=challenge.model_dump_json())

        with patch("src.services._challenge_cache.get_redis", return_value=mock_redis):
            from src.services._challenge_cache import get_cached_challenge

            result = await get_cached_challenge(_make_params())
            assert result is not None
            assert result.title == "Test Challenge"

    @pytest.mark.asyncio
    async def test_cache_store(self) -> None:
        challenge = _make_challenge()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("src.services._challenge_cache.get_redis", return_value=mock_redis):
            from src.services._challenge_cache import cache_challenge

            await cache_challenge(_make_params(), challenge)
            mock_redis.set.assert_called_once()

    @pytest.mark.asyncio
    async def test_absurd_not_cached(self) -> None:
        challenge = _make_challenge()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("src.services._challenge_cache.get_redis", return_value=mock_redis):
            from src.services._challenge_cache import cache_challenge

            await cache_challenge(_make_params(tone="absurd"), challenge)
            mock_redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_redis_error_returns_none(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("src.services._challenge_cache.get_redis", return_value=mock_redis):
            from src.services._challenge_cache import get_cached_challenge

            result = await get_cached_challenge(_make_params())
            assert result is None  # Graceful fallback
