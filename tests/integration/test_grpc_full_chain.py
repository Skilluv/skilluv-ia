"""M5.4 — Test e2e consolidé multi-services.

Un seul serveur aio.grpc avec les 4 servicers v2 + l'interceptor métrique.
On exerce chaque méthode successivement et on vérifie :
  1. Réponses valides
  2. Métriques `grpc_requests_total` et `grpc_request_duration_seconds`
     incrémentées correctement (labels 'method' et 'status')

Claude est mocké intégralement : aucun appel réseau externe.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from grpc import aio

from src.grpc_server._interceptors import MetricsInterceptor
from src.grpc_server.challenge_generation_servicer import (
    ChallengeGenerationServicer,
    _generated_to_proto,
)
from src.grpc_server.code_review_servicer import CodeReviewServicer
from src.grpc_server.generated import skilluv_ai_pb2 as pb2
from src.grpc_server.generated import skilluv_ai_pb2_grpc as pb2_grpc
from src.grpc_server.plagiarism_servicer import PlagiarismServicer
from src.grpc_server.talent_detection_servicer import TalentDetectionServicer
from src.models.challenge import GeneratedChallenge, TestCase
from src.models.code_review import CodeReviewFinding, CodeReviewResult
from src.services._plagiarism_embeddings import compute_embedding_similarity
from src.utils.metrics import grpc_request_duration_seconds, grpc_requests_total


@pytest.fixture(scope="module", autouse=True)
async def _prewarm_embedding_model():
    """Le modèle sentence-transformers peut mettre 1-3 min à télécharger la
    1re fois. On le charge en dehors de la fenêtre RPC (deadline 120s
    trop courte pour un cold start réel)."""
    await compute_embedding_similarity("warmup", "warmup")


def _sample_original_challenge() -> GeneratedChallenge:
    return GeneratedChallenge(
        title="FizzBuzz",
        description="desc",
        instructions="instr",
        difficulty=2,
        duration_minutes=30,
        skill_domain="code",
        tone="serious",
        tags=["python"],
        starter_code="pass",
        test_cases=[TestCase(input="3", expected_output="Fizz", description="")],
        evaluation_criteria="OK",
        fragment_reward=10,
        ai_allowed=False,
        language="fr",
    )


def _fake_claude_json(payload: dict) -> MagicMock:
    content = MagicMock()
    content.text = json.dumps(payload)
    msg = MagicMock()
    msg.content = [content]
    return msg


def _read_counter(counter, **labels) -> float:
    """Lit la valeur actuelle d'un compteur Prometheus."""
    return counter.labels(**labels)._value.get()


def _read_histogram_count(hist, **labels) -> float:
    """Lit le count total d'un histogram (nombre d'observations)."""
    # prometheus_client n'expose pas le count via un attribut public :
    # on scanne `.collect()` et on filtre sur le sample `_count` + labels.
    for metric_family in hist.collect():
        for sample in metric_family.samples:
            if sample.name.endswith("_count") and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


@pytest.mark.asyncio
async def test_full_chain_all_services_with_metrics():
    """Exercice successif Code Review -> Plagiarism -> TalentDetection -> ChallengeGeneration.
    Vérifie que chaque méthode est comptée et chronométrée."""
    server = aio.server(interceptors=[MetricsInterceptor()])
    pb2_grpc.add_CodeReviewServiceServicer_to_server(CodeReviewServicer(), server)
    pb2_grpc.add_PlagiarismServiceServicer_to_server(PlagiarismServicer(), server)
    pb2_grpc.add_TalentDetectionServiceServicer_to_server(TalentDetectionServicer(), server)
    pb2_grpc.add_ChallengeGenerationServiceServicer_to_server(
        ChallengeGenerationServicer(), server
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    review_method = "/skilluv.ai.v2.CodeReviewService/ReviewCode"
    plagiat_method = "/skilluv.ai.v2.PlagiarismService/CheckPlagiarism"
    analyze_method = "/skilluv.ai.v2.TalentDetectionService/AnalyzePerformance"
    career_method = "/skilluv.ai.v2.TalentDetectionService/SuggestCareerPath"
    variant_method = "/skilluv.ai.v2.ChallengeGenerationService/GenerateVariant"

    # Snapshot des compteurs avant (les tests précédents ont pu les toucher).
    def _before(method: str) -> float:
        return _read_counter(grpc_requests_total, method=method, status="ok")

    before = {
        m: _before(m)
        for m in [review_method, plagiat_method, analyze_method, career_method, variant_method]
    }

    fake_review_result = CodeReviewResult(
        submission_id="s", challenge_id="c", overall_score=80,
        summary="OK", strengths=["clair"], findings=[
            CodeReviewFinding(
                category="style", severity="low", title="t", description="d",
            )
        ],
    )
    fake_analyze_json = {
        "overall_score": 0.5, "strengths": [], "gaps": [],
        "next_actions": [
            {"action_type": "attempt_challenge", "target_slug": "x", "priority": 1}
        ],
        "rank_readiness": {
            "current_rank": "bronze", "next_rank": "silver",
            "missing_criteria": [], "estimated_days_to_promotion": 15,
        },
    }
    fake_career_json = {
        "suggestions": [
            {
                "orientation_slug": "dev-backend", "confidence": 0.8,
                "match_reason": "python fort", "required_skills_missing": [],
                "transition_effort": "low", "timeline_estimate_months": 3,
            }
        ],
        "primary_recommendation": "dev-backend",
        "secondary_recommendations": [],
    }
    fake_variant_response = _fake_claude_json({
        "title": "FizzBuzz Hard", "description": "", "instructions": "",
        "difficulty": 4, "duration_minutes": 30, "tags": [],
        "starter_code": "", "test_cases": [], "evaluation_criteria": "",
    })
    mock_variant_client = MagicMock()
    mock_variant_client.messages.create = AsyncMock(return_value=fake_variant_response)

    try:
        with (
            patch("src.grpc_server.code_review_servicer.review_code",
                  new=AsyncMock(return_value=fake_review_result)),
            patch("src.services.talent_analyzer._call_claude_structured",
                  new=AsyncMock(side_effect=[fake_analyze_json, fake_career_json])),
            patch("src.services.challenge_generator._get_client",
                  return_value=mock_variant_client),
        ):
            async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                # 1. ReviewCode
                review_stub = pb2_grpc.CodeReviewServiceStub(channel)
                review_resp = await review_stub.ReviewCode(
                    pb2.CodeReviewRequest(
                        submission_id="s-1", code="print('hi')", language="python",
                    ),
                    timeout=10,
                )
                assert review_resp.quality_score == 80

                # 2. CheckPlagiarism (déterministe, pas de mock)
                plagiat_stub = pb2_grpc.PlagiarismServiceStub(channel)
                plagiat_req = pb2.CheckPlagiarismRequest(
                    submission_id="s-1", code="print('hi')", language="python",
                )
                plagiat_req.comparison_pool.add(
                    submission_id="clone", code="print('hi')", language="python",
                    submitted_at="2026-07-15T10:00:00Z",
                )
                # timeout large : 1er run peut télécharger/charger le modèle
                # d'embeddings sentence-transformers (~40-60s à froid).
                plagiat_resp = await plagiat_stub.CheckPlagiarism(plagiat_req, timeout=120)
                assert plagiat_resp.is_plagiarism is True

                # 3. AnalyzePerformance
                talent_stub = pb2_grpc.TalentDetectionServiceStub(channel)
                analyze_req = pb2.AnalyzePerformanceRequest(
                    user_id="u-1", current_rank="bronze",
                )
                analyze_req.skills.add(skill_slug="python", wpc_total=100, evidence_count=5)
                analyze_resp = await talent_stub.AnalyzePerformance(analyze_req, timeout=10)
                assert analyze_resp.overall_score == pytest.approx(0.5)

                # 4. SuggestCareerPath
                career_req = pb2.CareerPathRequest(
                    user_id="u-1", target_market="africa", max_suggestions=3,
                )
                career_req.skills.add(skill_slug="python", wpc_total=200, evidence_count=15)
                career_resp = await talent_stub.SuggestCareerPath(career_req, timeout=10)
                assert career_resp.primary_recommendation == "dev-backend"

                # 5. GenerateVariant
                cg_stub = pb2_grpc.ChallengeGenerationServiceStub(channel)
                original_pb = _generated_to_proto(_sample_original_challenge())
                variant_req = pb2.GenerateVariantRequest(
                    original_challenge_id="ch-1", variant_type="harder", target_param="4",
                )
                variant_req.original.CopyFrom(original_pb)
                variant_resp = await cg_stub.GenerateVariant(variant_req, timeout=10)
                assert variant_resp.success is True
                assert variant_resp.challenge.difficulty == 4
    finally:
        await server.stop(grace=None)

    # --- Vérification des métriques ---
    for m in [review_method, plagiat_method, analyze_method, career_method, variant_method]:
        after = _read_counter(grpc_requests_total, method=m, status="ok")
        assert after == before[m] + 1, f"Counter non incrémenté pour {m}"
        # Le histogram a bien vu l'observation
        hist_count = _read_histogram_count(grpc_request_duration_seconds, method=m)
        assert hist_count >= 1, f"Aucune observation d'histogramme pour {m}"


@pytest.mark.asyncio
async def test_error_status_recorded_in_metrics():
    """Un abort() interne doit incrémenter status=error."""
    server = aio.server(interceptors=[MetricsInterceptor()])
    pb2_grpc.add_CodeReviewServiceServicer_to_server(CodeReviewServicer(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    method = "/skilluv.ai.v2.CodeReviewService/ReviewCode"
    before_err = _read_counter(grpc_requests_total, method=method, status="error")
    try:
        # review_code lève ExternalServiceError -> servicer.abort UNAVAILABLE
        from src.exceptions import ExternalServiceError
        with patch(
            "src.grpc_server.code_review_servicer.review_code",
            new=AsyncMock(side_effect=ExternalServiceError("upstream down", {})),
        ):
            async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = pb2_grpc.CodeReviewServiceStub(channel)
                with pytest.raises(Exception):
                    await stub.ReviewCode(
                        pb2.CodeReviewRequest(
                            submission_id="s-err", code="x", language="python",
                        ),
                        timeout=5,
                    )
    finally:
        await server.stop(grace=None)

    after_err = _read_counter(grpc_requests_total, method=method, status="error")
    assert after_err == before_err + 1
