"""Tests de l'enveloppe des workers arq (idempotence, écriture Redis, pub/sub,
métriques, gestion d'erreurs).

Les 6 workers de `src/workers/*.py` partagent la même enveloppe :
    1. Parse QueueMessage
    2. `job_already_processed` → skip si oui (idempotence)
    3. Increment `jobs_in_progress`
    4. Appelle le service métier
    5. Écrit un `JobResult(status=completed)` dans Redis + publie une
       notification pub/sub
    6. Increment `jobs_total{status=completed}`, observe `jobs_duration_seconds`
    7. Sur `SkilluvAIError` → `JobResult(status=failed, error='TypeName: msg')`
       + notification failed + `jobs_total{status=failed}`
    8. Sur `Exception` générique → même chose mais error='Unexpected: ...'
    9. Finally : decrement `jobs_in_progress`

Ces tests couvrent les 3 workers les plus critiques (backend Rust dépend de
leur résultat pour des décisions produit). Les 3 autres (media, recommender,
analytics) sont laissés pour une session ultérieure — leur pattern est
identique donc la couverture ici sert de baseline validée.

Infra :
    - `fakeredis.aioredis.FakeRedis` remplace la vraie connexion Redis. Le
      singleton `_redis` est patché avant chaque test et reset après.
    - Les fonctions service (detect_plagiarism / review_code / match_talents)
      sont mockées au niveau du module (patch AsyncMock) — on ne veut PAS
      tester le service, seulement l'enveloppe.
    - Les compteurs Prometheus étant globaux, on capture les valeurs
      avant/après plutôt que d'assumer un état 0.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from src.exceptions import ValidationError
from src.models.analytics import (
    ChurnPrediction,
    ChurnResult,
    HiddenGem,
    HiddenGemsResult,
)
from src.models.code_review import CodeReviewResult
from src.models.job_results import (
    JobResult,
    MatchedTalent,
    MediaResult,
    PlagiarismMatch,
    PlagiarismResult,
    TalentMatchResult,
)
from src.models.recommendations import (
    ChallengeRecommendation,
    RecommendationResult,
)
from src.utils import redis_client as redis_client_module
from src.utils.metrics import (
    jobs_duration_seconds,
    jobs_in_progress,
    jobs_total,
)


# =========================================================================
# Fixtures — Redis fake + service mocks + capture pub/sub
# =========================================================================


@pytest.fixture
async def fake_redis():
    """Injecte un FakeRedis async en lieu et place du singleton `_redis`.

    Le worker importe `get_redis`, `job_already_processed`, `write_result`,
    `publish_notification` depuis `src.utils.redis_client`. Toutes ces fonctions
    passent par `get_redis()` qui retourne le singleton — donc patcher le
    singleton suffit à intercepter tous les accès Redis.
    """
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)
    # Nettoie une éventuelle fuite entre tests si un test précédent avait
    # ouvert la vraie connexion.
    redis_client_module._redis = fake
    yield fake
    await fake.aclose()
    redis_client_module._redis = None


@pytest.fixture
async def captured_notifications(fake_redis):
    """Souscrit au channel `skilluv:notifications` et collecte les messages.

    Utilisé pour vérifier que le worker a bien publié la bonne notification.
    Retourne une liste live — les tests peuvent la lire après avoir fait
    tourner le worker.
    """
    collected: list[dict] = []
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe("skilluv:notifications")
    # Consomme le message "subscribe" ack immédiatement.
    await pubsub.get_message(timeout=0.1)

    async def _collect_all():
        # Vide toute la file de messages accumulés.
        while True:
            msg = await pubsub.get_message(timeout=0.1)
            if msg is None:
                break
            if msg.get("type") == "message":
                collected.append(json.loads(msg["data"]))

    # On expose la liste + la méthode pour drainer. Les tests appelleront
    # `await drain()` après le worker.
    yield collected, _collect_all
    await pubsub.unsubscribe("skilluv:notifications")
    await pubsub.aclose()


def make_raw_message(*, job_id: str, job_type: str, payload: dict) -> dict:
    """Fabrique un message brut prêt à être passé au worker."""
    return {
        "job_id": job_id,
        "job_type": job_type,
        "payload": payload,
        "created_at": datetime.now(UTC).isoformat(),
        "retry_count": 0,
    }


def metric_counter_value(counter, **labels) -> float:
    """Lit la valeur courante d'un Counter Prometheus pour un jeu de labels."""
    child = counter.labels(**labels)
    return child._value.get()


def metric_gauge_value(gauge, **labels) -> float:
    child = gauge.labels(**labels)
    return child._value.get()


def histogram_sample_count(histogram, **labels) -> float:
    """Nombre d'observations dans un Histogram pour ces labels."""
    child = histogram.labels(**labels)
    return child._sum.get(), sum(b.get() for b in child._buckets)


# =========================================================================
# Payloads de test
# =========================================================================


_PLAGIARISM_PAYLOAD = {
    "submission_id": "sub-plag-001",
    "challenge_id": "chal-001",
    "source_code": "def foo(): return 42\n",
    "language": "python",
    "compare_with": [
        {
            "submission_id": "sub-other-001",
            "user_id": "user-other-001",
            "source_code": "def bar(): return 42\n",
        }
    ],
}


_CODE_REVIEW_PAYLOAD = {
    "submission_id": "sub-cr-001",
    "challenge_id": "chal-cr-001",
    "user_id": "user-cr-001",
    "language": "python",
    "source_code": "def add(a, b): return a + b\n",
    "challenge_title": "Addition",
    "challenge_description": "Écris une fonction add.",
    "difficulty": 1,
    "user_level": "beginner",
}


_RECOMMENDATION_PAYLOAD = {
    "user": {
        "user_id": "user-reco-001",
        "skill_domain": "code",
        "title": "artisan",
        "total_fragments": 30,
        "streak_current": 3,
        "top_sub_skills": ["python"],
        "top_languages": ["python"],
        "recently_completed_challenge_ids": [],
        "weak_areas": [],
    },
    "candidates": [
        {
            "challenge_id": "chal-r-1",
            "title": "Fibonacci",
            "skill_domain": "code",
            "sub_skills": ["python", "recursion"],
            "difficulty": 2,
            "duration_minutes": 20,
            "tags": [],
            "completion_count": 5,
        }
    ],
    "top_n": 3,
}


_REPLAY_PAYLOAD = {
    "submission_id": "sub-rep-001",
    "challenge_id": "chal-rep-001",
    "user_id": "user-rep-001",
    "events": [
        {"t": 0, "type": "insert", "text": "def "},
        {"t": 1, "type": "insert", "text": "foo():"},
    ],
    "stats": {
        "duration_seconds": 60,
        "keystrokes": 20,
        "tests_passed": 2,
        "tests_total": 2,
        "fragments_earned": 5,
    },
}


_CLIP_PAYLOAD = {
    "submission_id": "sub-clip-001",
    "challenge_id": "chal-clip-001",
    "user_id": "user-clip-001",
    "clip_type": "top3",
    "replay_key": "replays/sub-rep-001.webm",
    "highlight_start_seconds": 10,
    "highlight_duration_seconds": 30,
}


_HIDDEN_GEMS_PAYLOAD = {
    "talents": [
        {
            "user_id": "user-hg-001",
            "username": "bob",
            "total_fragments": 100,
            "golden_stars": 2,
            "streak_current": 5,
            "challenges_completed_30d": 10,
            "avg_score_30d": 82.0,
            "days_since_last_activity": 1,
            "days_since_signup": 90,
            "profile_active": True,
            "followers_count": 3,
            "hidden_gem_score_prev": 0.5,
        }
    ],
    "top_n": 10,
}


_CHURN_PAYLOAD = {
    "talents": [
        {
            "user_id": "user-ch-001",
            "username": "carol",
            "total_fragments": 45,
            "golden_stars": 0,
            "streak_current": 0,
            "challenges_completed_30d": 0,
            "avg_score_30d": 0.0,
            "days_since_last_activity": 20,
            "days_since_signup": 120,
            "profile_active": True,
            "followers_count": 1,
            "hidden_gem_score_prev": 0.1,
        }
    ],
    "horizon_days": 14,
}


_TALENT_MATCH_PAYLOAD = {
    "enterprise_id": "ent-001",
    "criteria": {
        "skill_domains": ["code"],
        "min_fragments": 10,
        "min_title": None,
        "country": None,
        "languages": [],
        "job_description": None,
    },
    "candidates": [
        {
            "user_id": "user-cand-001",
            "username": "alice",
            "skill_domains": ["code"],
            "total_fragments": 42,
            "title": "artisan",
            "country": "BJ",
            "top_languages": ["python"],
            "trust_score": 0.7,
            "bio": None,
        }
    ],
}


def _plagiarism_ok_result() -> PlagiarismResult:
    return PlagiarismResult(
        submission_id="sub-plag-001",
        challenge_id="chal-001",
        matches=[
            PlagiarismMatch(
                compared_submission_id="sub-other-001",
                compared_user_id="user-other-001",
                ast_similarity=0.3,
                embedding_similarity=0.4,
                combined_score=0.35,
                is_plagiarism=False,
            )
        ],
        highest_score=0.35,
        flagged=False,
    )


def _code_review_ok_result() -> CodeReviewResult:
    return CodeReviewResult(
        submission_id="sub-cr-001",
        challenge_id="chal-cr-001",
        overall_score=80,
        summary="Bon travail.",
        strengths=["clarté"],
        findings=[],
        learning_resources=[],
        fragments_bonus=3,
    )


def _recommendation_ok_result() -> RecommendationResult:
    return RecommendationResult(
        user_id="user-reco-001",
        recommendations=[
            ChallengeRecommendation(
                challenge_id="chal-r-1",
                score=0.72,
                reason="Bien aligné avec ton profil Python.",
                growth_category="growth",
            )
        ],
    )


def _replay_ok_result() -> MediaResult:
    return MediaResult(
        submission_id="sub-rep-001",
        media_type="replay",
        minio_key="replays/sub-rep-001.webm",
        file_size_bytes=12345,
        duration_seconds=60.0,
    )


def _clip_ok_result() -> MediaResult:
    return MediaResult(
        submission_id="sub-clip-001",
        media_type="clip",
        minio_key="clips/sub-clip-001.mp4",
        file_size_bytes=4321,
        duration_seconds=30.0,
    )


def _hidden_gems_ok_result() -> HiddenGemsResult:
    return HiddenGemsResult(
        total_evaluated=1,
        gems=[HiddenGem(user_id="user-hg-001", username="bob", score=0.78, signals=["streak"])],
    )


def _churn_ok_result() -> ChurnResult:
    return ChurnResult(
        total_evaluated=1,
        predictions=[
            ChurnPrediction(
                user_id="user-ch-001",
                username="carol",
                churn_risk=0.65,
                risk_band="high",
                top_signals=["inactivity"],
                recommended_action="reengagement_email",
            )
        ],
    )


def _talent_match_ok_result() -> TalentMatchResult:
    return TalentMatchResult(
        enterprise_id="ent-001",
        matched_talents=[
            MatchedTalent(
                user_id="user-cand-001",
                username="alice",
                relevance_score=0.85,
                matching_criteria=["skill_domain:code"],
            )
        ],
        total_candidates=1,
        total_matched=1,
    )


# =========================================================================
# Descripteurs de worker — DRY pour les 3 workers
# =========================================================================


class WorkerCase:
    def __init__(
        self,
        *,
        name: str,
        import_worker,
        service_module_path: str,
        service_attr: str,
        job_type: str,
        payload: dict,
        ok_result_factory,
    ):
        self.name = name
        self.import_worker = import_worker
        self.service_module_path = service_module_path
        self.service_attr = service_attr
        self.job_type = job_type
        self.payload = payload
        self.ok_result_factory = ok_result_factory


WORKERS = [
    WorkerCase(
        name="plagiarism",
        import_worker=lambda: __import__(
            "src.workers.plagiarism", fromlist=["process_plagiarism_job"]
        ).process_plagiarism_job,
        service_module_path="src.services.plagiarism_detector",
        service_attr="detect_plagiarism",
        job_type="plagiarism_check",
        payload=_PLAGIARISM_PAYLOAD,
        ok_result_factory=_plagiarism_ok_result,
    ),
    WorkerCase(
        name="code_review",
        import_worker=lambda: __import__(
            "src.workers.code_reviewer", fromlist=["process_code_review_job"]
        ).process_code_review_job,
        service_module_path="src.services.code_reviewer",
        service_attr="review_code",
        job_type="code_review",
        payload=_CODE_REVIEW_PAYLOAD,
        ok_result_factory=_code_review_ok_result,
    ),
    WorkerCase(
        name="talent_match",
        import_worker=lambda: __import__(
            "src.workers.talent_matcher", fromlist=["process_talent_match_job"]
        ).process_talent_match_job,
        service_module_path="src.services.talent_matcher",
        service_attr="match_talents",
        job_type="talent_match",
        payload=_TALENT_MATCH_PAYLOAD,
        ok_result_factory=_talent_match_ok_result,
    ),
    # Phase 2 : recommender + media (2 sous-types) + analytics (2 job_types).
    WorkerCase(
        name="recommendation",
        import_worker=lambda: __import__(
            "src.workers.recommender", fromlist=["process_recommendation_job"]
        ).process_recommendation_job,
        service_module_path="src.services.recommender",
        service_attr="recommend_challenges",
        job_type="recommendation",
        payload=_RECOMMENDATION_PAYLOAD,
        ok_result_factory=_recommendation_ok_result,
    ),
    # media_processor : `job_type` du QueueMessage détermine le sous-type
    # (replay ou clip). Le service function appelé diffère aussi.
    WorkerCase(
        name="media_replay",
        import_worker=lambda: __import__(
            "src.workers.media_processor", fromlist=["process_media_job"]
        ).process_media_job,
        service_module_path="src.services.media_processor",
        service_attr="generate_replay",
        job_type="replay_generate",
        payload=_REPLAY_PAYLOAD,
        ok_result_factory=_replay_ok_result,
    ),
    WorkerCase(
        name="media_clip",
        import_worker=lambda: __import__(
            "src.workers.media_processor", fromlist=["process_media_job"]
        ).process_media_job,
        service_module_path="src.services.media_processor",
        service_attr="generate_clip",
        job_type="clip_generate",
        payload=_CLIP_PAYLOAD,
        ok_result_factory=_clip_ok_result,
    ),
    # analytics_ai : 2 entrypoints workers distincts (hidden_gems / churn),
    # chacun avec son job_type et sa fonction service dédiée.
    WorkerCase(
        name="analytics_hidden_gems",
        import_worker=lambda: __import__(
            "src.workers.analytics_ai", fromlist=["process_hidden_gems_job"]
        ).process_hidden_gems_job,
        service_module_path="src.services.analytics_ai",
        service_attr="detect_hidden_gems",
        job_type="analytics_hidden_gems",
        payload=_HIDDEN_GEMS_PAYLOAD,
        ok_result_factory=_hidden_gems_ok_result,
    ),
    WorkerCase(
        name="analytics_churn",
        import_worker=lambda: __import__(
            "src.workers.analytics_ai", fromlist=["process_churn_job"]
        ).process_churn_job,
        service_module_path="src.services.analytics_ai",
        service_attr="predict_churn",
        job_type="analytics_churn",
        payload=_CHURN_PAYLOAD,
        ok_result_factory=_churn_ok_result,
    ),
]


@pytest.fixture(params=WORKERS, ids=lambda w: w.name)
def worker_case(request) -> WorkerCase:
    return request.param


@pytest.fixture
def patch_service(monkeypatch, worker_case: WorkerCase):
    """Retourne un helper qui remplace la fonction service par un AsyncMock.

    Le mock peut soit renvoyer un résultat (`side_effect=result_factory`) soit
    lever une exception. On patche au niveau du module — le `from X import Y`
    du worker résout Y à l'import au moment de l'appel, donc il verra notre
    patch.
    """
    def _install(*, side_effect: Any = None, return_value: Any = None):
        mock = AsyncMock(side_effect=side_effect, return_value=return_value)
        module = __import__(worker_case.service_module_path, fromlist=[worker_case.service_attr])
        monkeypatch.setattr(module, worker_case.service_attr, mock)
        return mock

    return _install


# =========================================================================
# Tests — 4 scénarios × 3 workers = 12 tests via paramétrisation
# =========================================================================


@pytest.mark.asyncio
class TestWorkerEnvelope:
    async def test_happy_path_writes_result_and_publishes(
        self, worker_case, fake_redis, patch_service, captured_notifications
    ):
        """Scénario nominal : le service réussit → résultat écrit dans Redis
        avec status=completed, notification publiée sur skilluv:notifications,
        métriques mises à jour."""
        notifications, drain = captured_notifications
        mock_service = patch_service(return_value=worker_case.ok_result_factory())

        # Capture les valeurs de métriques avant le run.
        before_completed = metric_counter_value(
            jobs_total, job_type=worker_case.job_type, status="completed"
        )
        before_gauge = metric_gauge_value(jobs_in_progress, job_type=worker_case.job_type)

        worker_fn = worker_case.import_worker()
        job_id = f"job-happy-{worker_case.name}"
        raw = make_raw_message(
            job_id=job_id, job_type=worker_case.job_type, payload=worker_case.payload
        )
        await worker_fn({}, raw)
        await drain()

        # 1. Le service a été appelé une fois avec le payload parsé.
        assert mock_service.call_count == 1

        # 2. Un JobResult 'completed' a été écrit dans Redis.
        raw_result = await fake_redis.get(f"skilluv:result:{job_id}")
        assert raw_result is not None, "worker did not write result to Redis"
        result = JobResult.model_validate_json(raw_result)
        assert result.job_id == job_id
        assert result.status == "completed"
        assert result.result is not None
        assert result.error is None
        assert result.duration_ms >= 0

        # 3. Une notification a été publiée.
        assert len(notifications) == 1
        notif = notifications[0]
        assert notif["job_id"] == job_id
        assert notif["job_type"] == worker_case.job_type
        assert notif["status"] == "completed"

        # 4. Les métriques ont bougé.
        after_completed = metric_counter_value(
            jobs_total, job_type=worker_case.job_type, status="completed"
        )
        assert after_completed == before_completed + 1

        # 5. Le gauge in_progress est revenu à son état initial (inc + dec).
        after_gauge = metric_gauge_value(jobs_in_progress, job_type=worker_case.job_type)
        assert after_gauge == before_gauge

    async def test_idempotence_skips_when_already_processed(
        self, worker_case, fake_redis, patch_service, captured_notifications
    ):
        """Si un résultat existe déjà dans Redis pour ce job_id, le worker
        court-circuite avant d'appeler le service ET sans écrire de nouveau
        résultat ni publier de notification."""
        notifications, drain = captured_notifications
        mock_service = patch_service(return_value=worker_case.ok_result_factory())

        job_id = f"job-idem-{worker_case.name}"
        # Pré-remplit Redis avec un résultat existant.
        preexisting = JobResult(
            job_id=job_id,
            status="completed",
            result={"marker": "preexisting"},
            duration_ms=1234,
            completed_at=datetime.now(UTC),
        )
        await fake_redis.set(
            f"skilluv:result:{job_id}", preexisting.model_dump_json()
        )

        before_completed = metric_counter_value(
            jobs_total, job_type=worker_case.job_type, status="completed"
        )

        worker_fn = worker_case.import_worker()
        raw = make_raw_message(
            job_id=job_id, job_type=worker_case.job_type, payload=worker_case.payload
        )
        await worker_fn({}, raw)
        await drain()

        # Le service n'a PAS été appelé.
        assert mock_service.call_count == 0

        # Le résultat en Redis n'a pas été overwrit (le marker est conservé).
        raw_result = await fake_redis.get(f"skilluv:result:{job_id}")
        result = JobResult.model_validate_json(raw_result)
        assert result.result == {"marker": "preexisting"}

        # Aucune notification publiée.
        assert notifications == []

        # Métrique 'completed' inchangée.
        after_completed = metric_counter_value(
            jobs_total, job_type=worker_case.job_type, status="completed"
        )
        assert after_completed == before_completed

    async def test_skilluv_ai_error_marks_failed(
        self, worker_case, fake_redis, patch_service, captured_notifications
    ):
        """Une SkilluvAIError levée par le service → JobResult failed avec
        error='TypeName: message', notification failed publiée, métrique
        failed incrémentée."""
        notifications, drain = captured_notifications
        mock_service = patch_service(
            side_effect=ValidationError("payload rejected", {"detail": "x"})
        )

        before_failed = metric_counter_value(
            jobs_total, job_type=worker_case.job_type, status="failed"
        )

        worker_fn = worker_case.import_worker()
        job_id = f"job-err-{worker_case.name}"
        raw = make_raw_message(
            job_id=job_id, job_type=worker_case.job_type, payload=worker_case.payload
        )
        # Le worker attrape l'exception en interne — pas de re-raise.
        await worker_fn({}, raw)
        await drain()

        assert mock_service.call_count == 1

        raw_result = await fake_redis.get(f"skilluv:result:{job_id}")
        assert raw_result is not None
        result = JobResult.model_validate_json(raw_result)
        assert result.status == "failed"
        assert result.error is not None
        assert "ValidationError" in result.error
        assert "payload rejected" in result.error

        assert len(notifications) == 1
        assert notifications[0]["status"] == "failed"
        assert "payload rejected" in notifications[0]["summary"]["error"]

        after_failed = metric_counter_value(
            jobs_total, job_type=worker_case.job_type, status="failed"
        )
        assert after_failed == before_failed + 1

    async def test_media_worker_rejects_unknown_job_type(
        self, fake_redis, monkeypatch, captured_notifications
    ):
        """Cas spécifique du media_processor : si `job_type` n'est ni
        `replay_generate` ni `clip_generate`, le worker lui-même lève un
        `ValueError`. Ce n'est PAS le service qui plante, c'est la logique
        du worker qui refuse un routage inconnu.

        Ce test n'est pas paramétré — il ne concerne que media_processor.
        Il vit ici pour rester colocalisé avec les autres tests d'enveloppe.
        """
        notifications, drain = captured_notifications

        # On mocke les deux services quand même — pas censés être appelés,
        # mais évite qu'ils explosent sur des payload invalides.
        from src.services import media_processor as svc

        monkeypatch.setattr(svc, "generate_replay", AsyncMock())
        monkeypatch.setattr(svc, "generate_clip", AsyncMock())

        from src.workers.media_processor import process_media_job

        job_id = "job-unknown-media-type"
        raw = make_raw_message(
            job_id=job_id,
            job_type="totally_bogus_type",  # ni replay_generate ni clip_generate
            payload=_REPLAY_PAYLOAD,
        )
        await process_media_job({}, raw)
        await drain()

        raw_result = await fake_redis.get(f"skilluv:result:{job_id}")
        assert raw_result is not None
        result = JobResult.model_validate_json(raw_result)
        assert result.status == "failed"
        assert result.error is not None
        assert result.error.startswith("Unexpected:")
        assert "Unknown media job_type" in result.error

        assert len(notifications) == 1
        assert notifications[0]["status"] == "failed"

    async def test_unexpected_error_wrapped_and_marked_failed(
        self, worker_case, fake_redis, patch_service, captured_notifications
    ):
        """Une Exception non-SkilluvAIError → JobResult failed avec
        error='Unexpected: ...', notification failed, métrique failed."""
        notifications, drain = captured_notifications
        patch_service(side_effect=RuntimeError("boom from lib"))

        before_failed = metric_counter_value(
            jobs_total, job_type=worker_case.job_type, status="failed"
        )

        worker_fn = worker_case.import_worker()
        job_id = f"job-boom-{worker_case.name}"
        raw = make_raw_message(
            job_id=job_id, job_type=worker_case.job_type, payload=worker_case.payload
        )
        await worker_fn({}, raw)
        await drain()

        raw_result = await fake_redis.get(f"skilluv:result:{job_id}")
        assert raw_result is not None
        result = JobResult.model_validate_json(raw_result)
        assert result.status == "failed"
        assert result.error is not None
        assert result.error.startswith("Unexpected:")
        assert "boom from lib" in result.error

        assert len(notifications) == 1
        assert notifications[0]["status"] == "failed"

        after_failed = metric_counter_value(
            jobs_total, job_type=worker_case.job_type, status="failed"
        )
        assert after_failed == before_failed + 1
