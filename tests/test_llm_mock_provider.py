"""Tests du MockProvider — synthèse JSON conforme au schema, aucun réseau."""

from __future__ import annotations

import pytest

from src.llm.base import ModelTier
from src.llm.factory import get_llm, reset_provider_for_tests
from src.llm.mock_provider import MockProvider, _synthesize_from_schema


def test_synthesize_primitive_types() -> None:
    assert _synthesize_from_schema({"type": "string"}) == "mock-value"
    assert _synthesize_from_schema({"type": "integer"}) == 0
    assert _synthesize_from_schema({"type": "number"}) == 0.0
    assert _synthesize_from_schema({"type": "boolean"}) is False
    assert _synthesize_from_schema({"type": "null"}) is None
    assert _synthesize_from_schema({"type": "array"}) == []


def test_synthesize_object_all_properties_when_no_required() -> None:
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "score": {"type": "integer"},
            "flags": {"type": "array"},
        },
    }
    result = _synthesize_from_schema(schema)
    assert result == {"title": "mock-value", "score": 0, "flags": []}


def test_synthesize_object_only_required_when_listed() -> None:
    schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "optional": {"type": "string"},
        },
        "required": ["id"],
    }
    result = _synthesize_from_schema(schema)
    assert result == {"id": "mock-value"}


def test_synthesize_enum_picks_first_value() -> None:
    schema = {"type": "string", "enum": ["a", "b", "c"]}
    assert _synthesize_from_schema(schema) == "a"


def test_synthesize_nested_object() -> None:
    schema = {
        "type": "object",
        "properties": {
            "user": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
            },
        },
    }
    result = _synthesize_from_schema(schema)
    assert result == {"user": {"name": "mock-value", "age": 0}}


@pytest.mark.asyncio
async def test_mock_provider_complete_structured_returns_dict() -> None:
    provider = MockProvider()
    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    result = await provider.complete_structured(
        tier=ModelTier.FAST,
        system="s",
        user="u",
        schema=schema,
    )
    assert result == {"answer": "mock-value"}


def test_mock_provider_model_for_tier_labels() -> None:
    provider = MockProvider()
    assert provider.model_for_tier(ModelTier.PREMIUM) == "mock-premium"
    assert provider.model_for_tier(ModelTier.STANDARD) == "mock-standard"
    assert provider.model_for_tier(ModelTier.FAST) == "mock-fast"


def test_factory_returns_mock_when_env_flag_set(monkeypatch) -> None:
    """SKILLUV_AI_MOCK_CLAUDE=1 doit court-circuiter le provider configuré."""
    from src import config

    monkeypatch.setattr(config.settings, "mock_llm", True)
    reset_provider_for_tests()
    try:
        provider = get_llm()
        assert provider.name == "mock"
    finally:
        reset_provider_for_tests()


def test_factory_falls_back_to_configured_when_flag_off(monkeypatch) -> None:
    from src import config

    monkeypatch.setattr(config.settings, "mock_llm", False)
    monkeypatch.setattr(config.settings, "llm_provider", "mock")
    reset_provider_for_tests()
    try:
        provider = get_llm()
        # Match sur "mock" explicite dans _create_provider → même provider mais
        # par un autre chemin (utile pour distinguer bench "explicite" vs env
        # global).
        assert provider.name == "mock"
    finally:
        reset_provider_for_tests()
