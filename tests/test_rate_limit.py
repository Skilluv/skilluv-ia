"""Tests du RateLimitInterceptor gRPC."""

from __future__ import annotations

from src.grpc_server._rate_limit import DEFAULT_BUDGETS, RateLimitInterceptor


def _consume_n(rl: RateLimitInterceptor, peer: str, method: str, n: int) -> int:
    """Consomme n tokens ; retourne combien ont été acceptés."""
    ok = 0
    for _ in range(n):
        if rl._check_and_consume(peer, method):
            ok += 1
    return ok


class TestRateLimitBucket:
    def test_first_calls_within_budget_pass(self):
        rl = RateLimitInterceptor()
        method = "/skilluv.ai.v2.CodeReviewService/ReviewCode"
        # Budget 30/min → les 30 premiers doivent passer
        assert _consume_n(rl, "1.2.3.4", method, 30) == 30

    def test_exceeding_budget_gets_rejected(self):
        rl = RateLimitInterceptor()
        method = "/skilluv.ai.v2.CodeReviewService/ReviewCode"
        _consume_n(rl, "1.2.3.4", method, 30)
        # Le 31e devrait échouer (pas de refill instantané suffisant)
        assert rl._check_and_consume("1.2.3.4", method) is False

    def test_peers_have_independent_buckets(self):
        rl = RateLimitInterceptor()
        method = "/skilluv.ai.v2.CodeReviewService/ReviewCode"
        _consume_n(rl, "1.2.3.4", method, 30)
        # Un autre peer doit avoir son propre budget plein
        assert _consume_n(rl, "5.6.7.8", method, 30) == 30

    def test_methods_have_independent_budgets(self):
        rl = RateLimitInterceptor()
        peer = "1.2.3.4"
        _consume_n(rl, peer, "/skilluv.ai.v2.CodeReviewService/ReviewCode", 30)
        # Autre méthode = budget non entamé
        assert rl._check_and_consume(
            peer, "/skilluv.ai.v2.PlagiarismService/CheckPlagiarism"
        ) is True

    def test_unlisted_method_never_rate_limited(self):
        rl = RateLimitInterceptor()
        # Health et reflection ne sont pas dans DEFAULT_BUDGETS
        for _ in range(10_000):
            assert rl._check_and_consume(
                "1.2.3.4", "/grpc.health.v1.Health/Check"
            ) is True

    def test_custom_budgets_override_default(self):
        rl = RateLimitInterceptor(budgets={
            "/skilluv.ai.v2.CodeReviewService/ReviewCode": 2,
        })
        peer = "1.2.3.4"
        method = "/skilluv.ai.v2.CodeReviewService/ReviewCode"
        assert rl._check_and_consume(peer, method) is True
        assert rl._check_and_consume(peer, method) is True
        assert rl._check_and_consume(peer, method) is False


class TestDefaultBudgets:
    def test_review_code_stricter_than_plagiarism(self):
        # Cohérent avec la logique de coût : Opus >> AST déterministe
        assert (
            DEFAULT_BUDGETS["/skilluv.ai.v2.CodeReviewService/ReviewCode"]
            < DEFAULT_BUDGETS["/skilluv.ai.v2.PlagiarismService/CheckPlagiarism"]
        )

    def test_haiku_larger_than_sonnet(self):
        assert (
            DEFAULT_BUDGETS["/skilluv.ai.v2.TalentDetectionService/SuggestCareerPath"]
            > DEFAULT_BUDGETS["/skilluv.ai.v2.TalentDetectionService/AnalyzePerformance"]
        )

    def test_all_v2_methods_have_budget(self):
        expected = {
            "/skilluv.ai.v2.CodeReviewService/ReviewCode",
            "/skilluv.ai.v2.ChallengeGenerationService/GenerateChallenge",
            "/skilluv.ai.v2.ChallengeGenerationService/GenerateVariant",
            "/skilluv.ai.v2.TalentDetectionService/AnalyzePerformance",
            "/skilluv.ai.v2.TalentDetectionService/SuggestCareerPath",
            "/skilluv.ai.v2.PlagiarismService/CheckPlagiarism",
        }
        assert expected.issubset(DEFAULT_BUDGETS.keys())


class TestPeerParsing:
    def test_ipv4_peer_parsed(self):
        class _Ctx:
            def peer(self):
                return "ipv4:203.0.113.1:54321"
        rl = RateLimitInterceptor()
        assert rl._peer_of(_Ctx()) == "203.0.113.1"

    def test_unknown_when_peer_fails(self):
        class _Ctx:
            def peer(self):
                raise RuntimeError("no peer")
        rl = RateLimitInterceptor()
        assert rl._peer_of(_Ctx()) == "unknown"
