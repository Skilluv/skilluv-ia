import pytest


@pytest.fixture
def sample_plagiarism_payload() -> dict:
    """Payload de test pour la détection de plagiat."""
    return {
        "job_id": "test-job-001",
        "job_type": "plagiarism_check",
        "payload": {
            "submission_id": "sub-001",
            "challenge_id": "chall-001",
            "source_code": "def hello():\n    return 'world'",
            "language": "python",
            "compare_with": [
                {
                    "submission_id": "sub-002",
                    "user_id": "user-002",
                    "source_code": "def hello():\n    return 'world'",
                },
            ],
        },
        "created_at": "2026-03-21T10:00:00Z",
        "retry_count": 0,
    }


@pytest.fixture
def sample_talent_match_payload() -> dict:
    """Payload de test pour le matching talent."""
    return {
        "job_id": "test-job-002",
        "job_type": "talent_match",
        "payload": {
            "enterprise_id": "ent-001",
            "criteria": {
                "skill_domains": ["code"],
                "min_fragments": 500,
                "min_title": "Artisan",
                "country": "BJ",
            },
            "candidates": [
                {
                    "user_id": "user-001",
                    "username": "kofi",
                    "skill_domains": ["code"],
                    "total_fragments": 1200,
                    "title": "Maître",
                    "country": "BJ",
                    "top_languages": ["python", "rust"],
                    "trust_score": 0.85,
                },
            ],
        },
        "created_at": "2026-03-21T10:00:00Z",
        "retry_count": 0,
    }


@pytest.fixture
def sample_replay_payload() -> dict:
    """Payload de test pour la génération de replay."""
    return {
        "job_id": "test-job-003",
        "job_type": "replay_generate",
        "payload": {
            "submission_id": "sub-001",
            "challenge_id": "chall-001",
            "user_id": "user-001",
            "events": [
                {"timestamp": 0, "type": "insert", "content": "def "},
                {"timestamp": 1200, "type": "insert", "content": "hello():"},
            ],
            "stats": {
                "duration_seconds": 300,
                "keystrokes": 450,
                "tests_passed": 5,
                "tests_total": 5,
                "fragments_earned": 120,
            },
        },
        "created_at": "2026-03-21T10:00:00Z",
        "retry_count": 0,
    }
