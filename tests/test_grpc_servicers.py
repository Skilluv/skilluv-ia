"""M2 tests: gRPC servicers CodeReview + Plagiarism.

Deux niveaux :
  - Unit : appel direct sur le servicer avec mocks.
  - Integration : round-trip complet via un aio.Server local.

Le service Claude est mocké (pas de token, pas d'appel réseau). Le service
plagiarism utilise le vrai AST + embeddings (déterministes).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import grpc
import pytest
from grpc import aio

from src.grpc_server.code_review_servicer import (
    CodeReviewServicer,
    _SEVERITY_MAP,
    _to_response as codereview_to_response,
)
from src.grpc_server.generated import skilluv_ai_pb2 as pb2
from src.grpc_server.generated import skilluv_ai_pb2_grpc as pb2_grpc
from src.grpc_server.plagiarism_servicer import (
    PlagiarismServicer,
    _to_response as plagiarism_to_response,
)
from src.models.code_review import CodeReviewFinding, CodeReviewResult
from src.models.job_results import PlagiarismMatch, PlagiarismResult


# =========================================================================
# CodeReview — mapping unitaire pydantic -> proto
# =========================================================================


def _sample_review_result(**overrides) -> CodeReviewResult:
    base = dict(
        submission_id="sub-1",
        challenge_id="chall-1",
        overall_score=82,
        summary="Bien structuré, quelques détails à corriger.",
        strengths=["nommage clair", "tests présents"],
        findings=[
            CodeReviewFinding(
                category="bug",
                severity="high",
                line=12,
                title="Race condition",
                description="Accès concurrent non protégé sur `counter`.",
                suggestion="Utiliser un Lock ou passer counter par valeur.",
            ),
            CodeReviewFinding(
                category="style",
                severity="low",
                line=None,
                title="Ligne trop longue",
                description="La ligne 42 fait 130 caractères.",
                suggestion=None,
            ),
        ],
        learning_resources=["Concurrence Python", "PEP 8"],
        fragments_bonus=3,
    )
    base.update(overrides)
    return CodeReviewResult(**base)


class TestCodeReviewMapping:
    def test_maps_score_summary_strengths(self):
        response = codereview_to_response(_sample_review_result())
        assert response.quality_score == 82
        assert response.summary.startswith("Bien structuré")
        assert list(response.strengths) == ["nommage clair", "tests présents"]

    def test_improvements_come_from_finding_suggestions_only(self):
        response = codereview_to_response(_sample_review_result())
        # Seule la 1re finding a une suggestion (2nd = None)
        assert len(response.improvements) == 1
        assert "Lock" in response.improvements[0]

    def test_issues_mapped_with_severity_translation(self):
        response = codereview_to_response(_sample_review_result())
        assert len(response.issues) == 2
        # 'high' interne -> 'major' proto
        assert response.issues[0].severity == "major"
        # 'low' -> 'minor'
        assert response.issues[1].severity == "minor"
        # Ligne None -> 0 (proto3 int32 default)
        assert response.issues[1].line_number == 0
        assert response.issues[0].line_number == 12
        # Le message inclut titre + description
        assert "Race condition" in response.issues[0].message
        assert "Accès concurrent" in response.issues[0].message

    def test_resources_wrapped_in_LearningResource(self):
        response = codereview_to_response(_sample_review_result())
        assert len(response.resources) == 2
        assert response.resources[0].title == "Concurrence Python"
        assert response.resources[0].kind == "doc"
        assert response.resources[0].url == ""

    def test_model_version_stamped_with_active_provider(self):
        # Force le provider Claude pour vérifier le mapping PREMIUM -> Opus.
        from unittest.mock import patch
        from src.llm.claude_provider import ClaudeProvider
        with patch(
            "src.grpc_server.code_review_servicer.get_llm",
            return_value=ClaudeProvider(),
        ):
            response = codereview_to_response(_sample_review_result())
        assert response.model_version == "claude-opus-4-7"

    def test_model_version_non_empty_with_default_provider(self):
        # Avec le provider par défaut (Ollama en dev, Claude en prod), on
        # exige juste une chaîne non vide — le mapping strict est testé
        # ailleurs par provider.
        response = codereview_to_response(_sample_review_result())
        assert response.model_version != ""

    def test_severity_map_covers_all_internal_severities(self):
        # Défense contre régression : si le service ajoute une severity,
        # le map doit être mis à jour sinon default 'minor' pourrait masquer un bug.
        internal_severities = {"info", "low", "medium", "high", "critical"}
        assert internal_severities.issubset(_SEVERITY_MAP.keys())


class TestCodeReviewServicerReviewCode:
    @pytest.mark.asyncio
    async def test_calls_review_code_and_maps_result(self):
        servicer = CodeReviewServicer()
        request = pb2.CodeReviewRequest(
            submission_id="sub-42",
            code="def foo():\n    return 1",
            language="python",
            challenge_title="Sum two numbers",
            challenge_instructions="Return a + b",
            difficulty=2,
        )
        with patch(
            "src.grpc_server.code_review_servicer.review_code",
            new=AsyncMock(return_value=_sample_review_result()),
        ) as mock_review:
            response = await servicer.ReviewCode(request, context=_DummyContext())
        # Le service a été appelé avec un payload construit à partir du proto
        args, _ = mock_review.call_args
        payload = args[0]
        assert payload.submission_id == "sub-42"
        assert payload.language == "python"
        assert payload.source_code.startswith("def foo")
        assert payload.difficulty == 2
        # Réponse mappée
        assert response.quality_score == 82
        assert len(response.issues) == 2


# =========================================================================
# Plagiarism — mapping unitaire
# =========================================================================


def _sample_plagiarism_result(highest: float = 0.91, flagged: bool = True) -> PlagiarismResult:
    return PlagiarismResult(
        submission_id="sub-1",
        challenge_id="chall-1",
        matches=[
            PlagiarismMatch(
                compared_submission_id="sub-clone",
                compared_user_id="",
                ast_similarity=0.88,
                embedding_similarity=0.94,
                combined_score=highest,
                is_plagiarism=flagged,
            ),
            PlagiarismMatch(
                compared_submission_id="sub-far",
                compared_user_id="",
                ast_similarity=0.10,
                embedding_similarity=0.20,
                combined_score=0.15,
                is_plagiarism=False,
            ),
        ],
        highest_score=highest,
        flagged=flagged,
    )


class TestPlagiarismMapping:
    def test_top_match_extracted(self):
        response = plagiarism_to_response(_sample_plagiarism_result(), threshold=0.0)
        assert response.similar_submission_id == "sub-clone"
        assert response.ast_similarity == pytest.approx(0.88)
        assert response.embedding_similarity == pytest.approx(0.94)

    def test_is_plagiarism_uses_service_flag_when_no_threshold(self):
        response = plagiarism_to_response(_sample_plagiarism_result(flagged=True), threshold=0.0)
        assert response.is_plagiarism is True

    def test_is_plagiarism_uses_client_threshold_when_provided(self):
        # highest=0.91, service flagged False, but client threshold=0.80 -> plagiat
        result = _sample_plagiarism_result(highest=0.91, flagged=False)
        response = plagiarism_to_response(result, threshold=0.80)
        assert response.is_plagiarism is True

        # highest=0.91, client threshold=0.99 -> pas plagiat
        response = plagiarism_to_response(result, threshold=0.99)
        assert response.is_plagiarism is False

    def test_empty_matches(self):
        empty = PlagiarismResult(
            submission_id="s", challenge_id="c", matches=[], highest_score=0.0, flagged=False,
        )
        response = plagiarism_to_response(empty, threshold=0.0)
        assert response.similar_submission_id == ""
        assert response.ast_similarity == 0.0
        assert response.embedding_similarity == 0.0
        assert response.is_plagiarism is False

    def test_model_version_stamped(self):
        response = plagiarism_to_response(_sample_plagiarism_result(), threshold=0.0)
        assert response.model_version == "ast+embedding-v1"


class TestPlagiarismServicerCheckPlagiarism:
    @pytest.mark.asyncio
    async def test_end_to_end_with_real_detector_identical_code(self):
        """Round-trip complet, vrai AST + embeddings, code identique => plagiat."""
        servicer = PlagiarismServicer()
        code = "def hello():\n    return 'world'"
        request = pb2.CheckPlagiarismRequest(
            submission_id="sub-1",
            code=code,
            language="python",
        )
        request.comparison_pool.add(
            submission_id="sub-clone",
            code=code,
            language="python",
            submitted_at="2026-07-15T10:00:00Z",
        )
        response = await servicer.CheckPlagiarism(request, context=_DummyContext())
        assert response.is_plagiarism is True
        assert response.similarity_score > 0.80
        assert response.similar_submission_id == "sub-clone"

    @pytest.mark.asyncio
    async def test_end_to_end_different_code_not_plagiat(self):
        servicer = PlagiarismServicer()
        request = pb2.CheckPlagiarismRequest(
            submission_id="sub-1",
            code="def bubble_sort(a):\n    for i in range(len(a)):\n        for j in range(len(a)-1):\n            if a[j]>a[j+1]: a[j],a[j+1]=a[j+1],a[j]",
            language="python",
        )
        request.comparison_pool.add(
            submission_id="sub-far",
            code="class Node:\n    def __init__(self,v):\n        self.v=v\n        self.next=None",
            language="python",
            submitted_at="2026-07-15T10:00:00Z",
        )
        response = await servicer.CheckPlagiarism(request, context=_DummyContext())
        assert response.is_plagiarism is False
        assert response.similarity_score < 0.80


# =========================================================================
# Integration — vrai serveur aio.grpc + vrai client sur socket local
# =========================================================================


class TestGrpcIntegration:
    @pytest.mark.asyncio
    async def test_code_review_over_the_wire(self):
        server = aio.server()
        pb2_grpc.add_CodeReviewServiceServicer_to_server(CodeReviewServicer(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            with patch(
                "src.grpc_server.code_review_servicer.review_code",
                new=AsyncMock(return_value=_sample_review_result()),
            ):
                async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                    stub = pb2_grpc.CodeReviewServiceStub(channel)
                    response = await stub.ReviewCode(
                        pb2.CodeReviewRequest(
                            submission_id="s-e2e",
                            code="def x(): pass",
                            language="python",
                            difficulty=1,
                        ),
                        timeout=10,
                    )
            assert response.quality_score == 82
            assert len(response.issues) == 2
            assert response.model_version != ""
        finally:
            await server.stop(grace=None)

    @pytest.mark.asyncio
    async def test_plagiarism_over_the_wire(self):
        server = aio.server()
        pb2_grpc.add_PlagiarismServiceServicer_to_server(PlagiarismServicer(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            async with aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = pb2_grpc.PlagiarismServiceStub(channel)
                request = pb2.CheckPlagiarismRequest(
                    submission_id="s-e2e",
                    code="print('hi')",
                    language="python",
                )
                request.comparison_pool.add(
                    submission_id="clone", code="print('hi')", language="python",
                    submitted_at="2026-07-15T10:00:00Z",
                )
                response = await stub.CheckPlagiarism(request, timeout=15)
            assert response.similar_submission_id == "clone"
            assert response.is_plagiarism is True
            assert response.model_version == "ast+embedding-v1"
        finally:
            await server.stop(grace=None)


# =========================================================================
# Helper — minimal ServicerContext pour appels unitaires
# =========================================================================


class _DummyContext:
    """Contexte minimaliste ; ne sert que si le servicer appelle abort()."""

    async def abort(self, code, details):  # pragma: no cover - not hit sur happy path
        raise grpc.RpcError(f"{code}: {details}")
