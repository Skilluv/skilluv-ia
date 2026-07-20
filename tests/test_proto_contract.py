"""Contract tests for the v2 skilluv_ai proto (MVP phase IA-M1).

Ces tests protègent contre les régressions du contrat gRPC exposé au backend.
Ne testent PAS la logique métier — juste que les messages/services existent
avec les bons champs et bons types.

Source de vérité : docs/MVP.md (Annexe A) + proto/skilluv_ai.proto.
"""

import pytest

from src.grpc_server.generated import (
    challenge_pb2,
    challenge_pb2_grpc,
)
from src.grpc_server.generated import (
    skilluv_ai_pb2 as pb2,
)
from src.grpc_server.generated import (
    skilluv_ai_pb2_grpc as pb2_grpc,
)

# --- 1. Les 4 servicers du contrat sont exposés --------------------------

EXPECTED_SERVICERS = {
    "CodeReviewServiceServicer",
    "ChallengeGenerationServiceServicer",
    "TalentDetectionServiceServicer",
    "PlagiarismServiceServicer",
}


def test_all_four_servicers_are_generated():
    found = {s for s in dir(pb2_grpc) if s.endswith("Servicer") and not s.startswith("_")}
    missing = EXPECTED_SERVICERS - found
    assert not missing, f"Servicers manquants dans le stub: {missing}"


@pytest.mark.parametrize(
    "servicer_name,rpc_method",
    [
        ("CodeReviewServiceServicer", "ReviewCode"),
        ("ChallengeGenerationServiceServicer", "GenerateChallenge"),
        ("ChallengeGenerationServiceServicer", "GenerateVariant"),
        ("TalentDetectionServiceServicer", "AnalyzePerformance"),
        ("TalentDetectionServiceServicer", "SuggestCareerPath"),
        ("PlagiarismServiceServicer", "CheckPlagiarism"),
    ],
)
def test_rpc_method_exists_on_servicer(servicer_name, rpc_method):
    servicer_cls = getattr(pb2_grpc, servicer_name)
    assert hasattr(servicer_cls, rpc_method), (
        f"{servicer_name} devrait avoir la methode RPC {rpc_method}"
    )


# --- 2. Messages critiques présents ----------------------------------------

REQUIRED_MESSAGES = [
    # CodeReview
    "CodeReviewRequest",
    "CodeReviewResponse",
    "Issue",
    "LearningResource",
    # ChallengeGeneration
    "GenerateChallengeRequest",
    "GenerateVariantRequest",
    "GenerateChallengeResponse",
    "GeneratedChallenge",
    "TestCase",
    # TalentDetection
    "AnalyzePerformanceRequest",
    "AnalyzePerformanceResponse",
    "CareerPathRequest",
    "CareerPathResponse",
    "DeliverableSnapshot",
    "SkillSnapshot",
    "OrientationSnapshot",
    "StrengthItem",
    "GapItem",
    "NextAction",
    "RankReadiness",
    "MissingCriterion",
    "OrientationSuggestion",
    # Plagiarism
    "CheckPlagiarismRequest",
    "CheckPlagiarismResponse",
    "PreviousSubmission",
    "MatchedRange",
]


@pytest.mark.parametrize("msg_name", REQUIRED_MESSAGES)
def test_message_type_exists(msg_name):
    assert hasattr(pb2, msg_name), f"Message manquant: {msg_name}"
    # Doit être instantiable
    getattr(pb2, msg_name)()


# --- 3. Champs consommés par le backend Rust présents ----------------------
# Extrait de skilluv-backend/src/grpc/client.rs et llm_verifier.rs
# (voir MVP.md §2.1, §2.2, §2.3).

def _field_names(msg_cls) -> set[str]:
    return {f.name for f in msg_cls.DESCRIPTOR.fields}


def test_code_review_response_has_backend_consumed_fields():
    got = _field_names(pb2.CodeReviewResponse)
    required = {"quality_score", "summary", "strengths", "improvements", "issues", "model_version"}
    assert required.issubset(got), f"Champs manquants: {required - got}"


def test_check_plagiarism_response_has_backend_consumed_fields():
    got = _field_names(pb2.CheckPlagiarismResponse)
    required = {"similarity_score", "similar_submission_id", "matched_ranges", "is_plagiarism", "model_version"}
    assert required.issubset(got), f"Champs manquants: {required - got}"


def test_generate_challenge_request_has_p16_orientation_slug():
    # P16 = orientations métier, nouvelle exigence backend
    assert "orientation_slug" in _field_names(pb2.GenerateChallengeRequest)


def test_generate_variant_request_carries_original_inline():
    # M4 : le backend fournit le challenge original inline (IA reste stateless)
    got = _field_names(pb2.GenerateVariantRequest)
    assert "original" in got
    # Type check : le champ doit être un GeneratedChallenge
    field = pb2.GenerateVariantRequest.DESCRIPTOR.fields_by_name["original"]
    assert field.message_type is not None
    assert field.message_type.name == "GeneratedChallenge"


def test_analyze_performance_response_has_rank_readiness():
    got = _field_names(pb2.AnalyzePerformanceResponse)
    assert "rank_readiness" in got
    assert "next_actions" in got
    assert "model_version" in got


def test_career_path_response_has_primary_recommendation():
    got = _field_names(pb2.CareerPathResponse)
    assert "primary_recommendation" in got
    assert "suggestions" in got


# --- 4. Versioning rules (MVP.md §0.5) -------------------------------------

RESPONSES_REQUIRING_MODEL_VERSION = [
    "CodeReviewResponse",
    "GenerateChallengeResponse",
    "AnalyzePerformanceResponse",
    "CareerPathResponse",
    "CheckPlagiarismResponse",
]


@pytest.mark.parametrize("response_name", RESPONSES_REQUIRING_MODEL_VERSION)
def test_every_response_carries_model_version(response_name):
    msg_cls = getattr(pb2, response_name)
    assert "model_version" in _field_names(msg_cls), (
        f"{response_name} doit exposer model_version (MVP.md §0.5)"
    )


# --- 5. Types de champs critiques (évite les erreurs d'unités) -------------

def test_quality_score_is_int32_range_hint():
    # Contract: quality_score is int32 0-100 (backend normalise à [0,1])
    field = pb2.CodeReviewResponse.DESCRIPTOR.fields_by_name["quality_score"]
    from google.protobuf.descriptor import FieldDescriptor
    assert field.type == FieldDescriptor.TYPE_INT32


def test_similarity_score_is_double():
    # Contract: [0,1] côté IA (backend attend un float 0-1)
    from google.protobuf.descriptor import FieldDescriptor
    field = pb2.CheckPlagiarismResponse.DESCRIPTOR.fields_by_name["similarity_score"]
    assert field.type == FieldDescriptor.TYPE_DOUBLE


def test_overall_score_is_double():
    from google.protobuf.descriptor import FieldDescriptor
    field = pb2.AnalyzePerformanceResponse.DESCRIPTOR.fields_by_name["overall_score"]
    assert field.type == FieldDescriptor.TYPE_DOUBLE


# --- 6. Backward compat : v1 legacy proto reste fonctionnel ----------------

def test_legacy_v1_proto_still_available():
    # Tant que backend n'a pas migré, le v1 doit continuer à charger.
    assert hasattr(challenge_pb2_grpc, "ChallengeServiceServicer")
    assert hasattr(challenge_pb2, "GenerateChallengeRequest")


# --- 7. Sanity round-trip : sérialiser un message et le relire -------------

def test_code_review_response_serialization_roundtrip():
    resp = pb2.CodeReviewResponse(
        quality_score=87,
        summary="Solid implementation.",
        strengths=["clear naming", "good tests"],
        improvements=["extract helper"],
        model_version="claude-opus-4-7",
    )
    resp.issues.add(severity="minor", category="style", message="line too long", line_number=42)
    blob = resp.SerializeToString()
    parsed = pb2.CodeReviewResponse.FromString(blob)
    assert parsed.quality_score == 87
    assert parsed.summary == "Solid implementation."
    assert list(parsed.strengths) == ["clear naming", "good tests"]
    assert len(parsed.issues) == 1
    assert parsed.issues[0].line_number == 42


def test_check_plagiarism_response_roundtrip():
    resp = pb2.CheckPlagiarismResponse(
        similarity_score=0.91,
        similar_submission_id="sub-42",
        ast_similarity=0.88,
        embedding_similarity=0.94,
        is_plagiarism=True,
        model_version="ast+embed-v1",
    )
    resp.matched_ranges.add(
        source_start_line=1, source_end_line=10,
        target_start_line=3, target_end_line=12, confidence=0.9,
    )
    parsed = pb2.CheckPlagiarismResponse.FromString(resp.SerializeToString())
    assert parsed.is_plagiarism is True
    assert 0.90 < parsed.similarity_score < 0.92
    assert len(parsed.matched_ranges) == 1
