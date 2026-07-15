"""M4 tests: generate_variant + v2 ChallengeGenerationService gRPC servicer.

Claude est mocké au niveau de `_get_client()`. Aucun appel réseau, aucun coût.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from grpc import aio

from src.exceptions import ValidationError
from src.grpc_server.challenge_generation_servicer import (
    ChallengeGenerationServicer,
    _generated_to_proto,
    _proto_original_to_pydantic,
)
from src.grpc_server.generated import skilluv_ai_pb2 as pb2
from src.grpc_server.generated import skilluv_ai_pb2_grpc as pb2_grpc
from src.models.challenge import GeneratedChallenge, TestCase
from src.services.challenge_generator import (
    _resolve_variant_metadata,
    _VALID_VARIANT_TYPES,
    generate_variant,
)


# =========================================================================
# 1. Helpers unitaires
# =========================================================================


def _sample_original() -> GeneratedChallenge:
    return GeneratedChallenge(
        title="FizzBuzz",
        description="Écrire un programme FizzBuzz.",
        instructions="Nombres de 1 à 100, remplacer par Fizz/Buzz/FizzBuzz.",
        difficulty=2,
        duration_minutes=30,
        skill_domain="code",
        tone="serious",
        tags=["python", "basics"],
        starter_code="def fizzbuzz(n):\n    pass",
        test_cases=[
            TestCase(input="3", expected_output="Fizz", description="mult 3"),
            TestCase(input="5", expected_output="Buzz", description="mult 5"),
        ],
        evaluation_criteria="Boucle correcte, if/elif ordonnés.",
        fragment_reward=10,
        ai_allowed=False,
        language="fr",
    )


class TestResolveVariantMetadata:
    def test_harder_bumps_difficulty(self):
        orig = _sample_original()
        diff, dur = _resolve_variant_metadata(orig, "harder", "")
        assert diff == 3 and dur == 30

    def test_harder_with_target_param(self):
        orig = _sample_original()
        diff, _ = _resolve_variant_metadata(orig, "harder", "5")
        assert diff == 5

    def test_easier_floors_at_1(self):
        orig = _sample_original()
        orig2 = orig.model_copy(update={"difficulty": 1})
        diff, _ = _resolve_variant_metadata(orig2, "easier", "")
        assert diff == 1

    def test_shorter_halves_duration(self):
        orig = _sample_original()
        _, dur = _resolve_variant_metadata(orig, "shorter", "")
        assert dur == 15

    def test_longer_caps_at_180(self):
        orig = _sample_original()
        orig2 = orig.model_copy(update={"duration_minutes": 120})
        _, dur = _resolve_variant_metadata(orig2, "longer", "")
        assert dur == 180

    def test_different_lang_preserves_metadata(self):
        orig = _sample_original()
        diff, dur = _resolve_variant_metadata(orig, "different_lang", "rust")
        assert diff == orig.difficulty and dur == orig.duration_minutes

    def test_target_param_non_int_falls_back(self):
        orig = _sample_original()
        diff, _ = _resolve_variant_metadata(orig, "harder", "notanumber")
        assert diff == 3  # fallback = +1


# =========================================================================
# 2. generate_variant — Claude mocké
# =========================================================================


def _mock_claude_response(payload_dict: dict) -> MagicMock:
    """Construit un mock de messages.create return value."""
    mock_content = MagicMock()
    mock_content.text = json.dumps(payload_dict)
    mock_message = MagicMock()
    mock_message.content = [mock_content]
    return mock_message


class TestGenerateVariant:
    @pytest.mark.asyncio
    async def test_invalid_variant_type_raises(self):
        with pytest.raises(ValidationError):
            await generate_variant(_sample_original(), "nope", "")

    @pytest.mark.asyncio
    async def test_empty_original_raises(self):
        empty = _sample_original().model_copy(update={"title": ""})
        with pytest.raises(ValidationError):
            await generate_variant(empty, "harder", "")

    @pytest.mark.asyncio
    async def test_harder_variant_calls_claude_and_maps(self):
        original = _sample_original()
        fake_claude_output = {
            "title": "FizzBuzz Avancé",
            "description": "Version corsée.",
            "instructions": "Ajout : nombres premiers -> Prime.",
            "difficulty": 3,
            "duration_minutes": 30,
            "tags": ["python", "advanced"],
            "starter_code": "def fizzbuzz_plus(n): pass",
            "test_cases": [
                {"input": "7", "expected_output": "Prime", "description": "prime"},
            ],
            "evaluation_criteria": "Gestion premiers correcte.",
        }
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_claude_response(fake_claude_output)
        )
        with patch(
            "src.services.challenge_generator._get_client", return_value=mock_client,
        ):
            variant = await generate_variant(original, "harder", "3")

        assert variant.title == "FizzBuzz Avancé"
        assert variant.difficulty == 3
        assert variant.duration_minutes == 30
        # Metadata héritée
        assert variant.skill_domain == "code"
        assert variant.language == "fr"
        # fragment_reward recalculé
        assert variant.fragment_reward > 0
        # Un seul appel Claude
        mock_client.messages.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_variant_falls_back_to_expected_metadata_when_claude_omits(self):
        original = _sample_original()
        # Claude retourne un JSON minimal, sans difficulty ni duration
        fake = {"title": "FizzBuzz Facile", "description": "Simplifié."}
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(fake))
        with patch(
            "src.services.challenge_generator._get_client", return_value=mock_client,
        ):
            variant = await generate_variant(original, "easier", "")
        # _resolve_variant_metadata a calculé difficulty=1
        assert variant.difficulty == 1
        # duration inchangée pour easier
        assert variant.duration_minutes == original.duration_minutes


# =========================================================================
# 3. Mapping proto <-> pydantic
# =========================================================================


class TestGeneratedToProto:
    def test_maps_all_fields(self):
        original = _sample_original()
        proto_msg = _generated_to_proto(original)
        assert proto_msg.title == "FizzBuzz"
        assert proto_msg.difficulty == 2
        assert proto_msg.duration_minutes == 30
        assert list(proto_msg.tags) == ["python", "basics"]
        assert len(proto_msg.test_cases) == 2
        assert proto_msg.test_cases[0].input == "3"
        assert proto_msg.test_cases[0].expected_output == "Fizz"
        assert proto_msg.starter_code == "def fizzbuzz(n):\n    pass"

    def test_none_starter_code_becomes_empty(self):
        original = _sample_original().model_copy(update={"starter_code": None})
        proto_msg = _generated_to_proto(original)
        assert proto_msg.starter_code == ""


class TestProtoOriginalToPydantic:
    def test_roundtrip_preserves_fields(self):
        original = _sample_original()
        proto_msg = _generated_to_proto(original)
        back = _proto_original_to_pydantic(proto_msg)
        assert back.title == original.title
        assert back.difficulty == original.difficulty
        assert back.duration_minutes == original.duration_minutes
        assert back.tags == original.tags
        assert len(back.test_cases) == 2
        assert back.test_cases[0].input == "3"


# =========================================================================
# 4. Servicer end-to-end (aio.grpc)
# =========================================================================


class TestChallengeGenerationServicerOverWire:
    @pytest.mark.asyncio
    async def test_generate_variant_missing_original_returns_failure(self):
        server = aio.server()
        pb2_grpc.add_ChallengeGenerationServiceServicer_to_server(
            ChallengeGenerationServicer(), server
        )
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = pb2_grpc.ChallengeGenerationServiceStub(channel)
                response = await stub.GenerateVariant(
                    pb2.GenerateVariantRequest(
                        original_challenge_id="x", variant_type="harder", target_param="",
                    ),
                    timeout=5,
                )
            assert response.success is False
            assert "original" in response.error_message.lower()
        finally:
            await server.stop(grace=None)

    @pytest.mark.asyncio
    async def test_generate_variant_happy_path(self):
        server = aio.server()
        pb2_grpc.add_ChallengeGenerationServiceServicer_to_server(
            ChallengeGenerationServicer(), server
        )
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        fake = {
            "title": "FizzBuzz Hard",
            "description": "corsé",
            "instructions": "règles supplémentaires",
            "difficulty": 4,
            "duration_minutes": 30,
            "tags": ["python"],
            "starter_code": "def x(): pass",
            "test_cases": [],
            "evaluation_criteria": "OK",
        }
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=_mock_claude_response(fake))
        try:
            with patch(
                "src.services.challenge_generator._get_client", return_value=mock_client,
            ):
                original_pb = _generated_to_proto(_sample_original())
                async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                    stub = pb2_grpc.ChallengeGenerationServiceStub(channel)
                    request = pb2.GenerateVariantRequest(
                        original_challenge_id="ch-1",
                        variant_type="harder",
                        target_param="4",
                    )
                    request.original.CopyFrom(original_pb)
                    response = await stub.GenerateVariant(request, timeout=10)
            assert response.success is True
            assert response.challenge.title == "FizzBuzz Hard"
            assert response.challenge.difficulty == 4
            assert response.model_version.startswith("claude-sonnet-4")
        finally:
            await server.stop(grace=None)
