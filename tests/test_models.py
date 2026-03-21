"""Tests de validation des modèles Pydantic."""

import pytest
from pydantic import ValidationError

from src.models.challenge import ChallengeParams, GeneratedChallenge
from src.models.job_results import JobResult, PlagiarismMatch
from src.models.queue_messages import QueueMessage, PlagiarismPayload


class TestQueueMessage:
    def test_valid_message(self, sample_plagiarism_payload: dict) -> None:
        msg = QueueMessage.model_validate(sample_plagiarism_payload)
        assert msg.job_id == "test-job-001"
        assert msg.job_type == "plagiarism_check"
        assert msg.retry_count == 0

    def test_missing_job_id_fails(self) -> None:
        with pytest.raises(ValidationError):
            QueueMessage.model_validate({
                "job_type": "plagiarism_check",
                "payload": {},
                "created_at": "2026-03-21T10:00:00Z",
            })


class TestPlagiarismPayload:
    def test_valid_payload(self, sample_plagiarism_payload: dict) -> None:
        payload = PlagiarismPayload.model_validate(
            sample_plagiarism_payload["payload"]
        )
        assert payload.submission_id == "sub-001"
        assert payload.language == "python"
        assert len(payload.compare_with) == 1


class TestChallengeParams:
    def test_valid_params(self) -> None:
        params = ChallengeParams(
            skill_domain="code",
            difficulty=3,
            duration_minutes=30,
            programming_language="python",
        )
        assert params.tone == "serious"
        assert params.mode == "solo"

    def test_difficulty_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            ChallengeParams(
                skill_domain="code",
                difficulty=6,
                duration_minutes=30,
            )

    def test_duration_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            ChallengeParams(
                skill_domain="code",
                difficulty=3,
                duration_minutes=0,
            )


class TestJobResult:
    def test_completed_result(self) -> None:
        result = JobResult(
            job_id="test-001",
            status="completed",
            result={"flagged": False},
            duration_ms=150,
            completed_at="2026-03-21T10:00:00Z",
        )
        assert result.status == "completed"
        assert result.error is None

    def test_failed_result(self) -> None:
        result = JobResult(
            job_id="test-001",
            status="failed",
            error="ExternalServiceError: Claude API timeout",
            duration_ms=5000,
            completed_at="2026-03-21T10:00:00Z",
        )
        assert result.status == "failed"
        assert result.result is None


class TestPlagiarismMatch:
    def test_plagiarism_detected(self) -> None:
        match = PlagiarismMatch(
            compared_submission_id="sub-002",
            compared_user_id="user-002",
            ast_similarity=0.95,
            embedding_similarity=0.88,
            combined_score=0.92,
            is_plagiarism=True,
        )
        assert match.is_plagiarism
        assert match.combined_score > 0.80
