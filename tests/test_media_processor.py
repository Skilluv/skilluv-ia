"""Tests du service de traitement média."""

import os
import tempfile

import pytest

from src.models.queue_messages import ReplayPayload, SubmissionStats
from src.services.media_processor import (
    _generate_code_frames,
    _write_stats_overlay,
)


class TestGenerateCodeFrames:
    def test_insert_events(self) -> None:
        events = [
            {"type": "insert", "content": "def "},
            {"type": "insert", "content": "hello():"},
            {"type": "insert", "content": "\n    return 'world'"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            count = _generate_code_frames(events, tmpdir)
            assert count == 3

            # Dernière frame contient le code complet
            with open(os.path.join(tmpdir, "frame_000002.txt")) as f:
                content = f.read()
            assert content == "def hello():\n    return 'world'"

    def test_delete_events(self) -> None:
        events = [
            {"type": "insert", "content": "hello world"},
            {"type": "delete", "count": 5},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            count = _generate_code_frames(events, tmpdir)
            assert count == 2

            with open(os.path.join(tmpdir, "frame_000001.txt")) as f:
                content = f.read()
            assert content == "hello "

    def test_replace_events(self) -> None:
        events = [
            {"type": "insert", "content": "old code"},
            {"type": "replace", "content": "new code"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            _generate_code_frames(events, tmpdir)

            with open(os.path.join(tmpdir, "frame_000001.txt")) as f:
                content = f.read()
            assert content == "new code"

    def test_empty_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            count = _generate_code_frames([], tmpdir)
            assert count == 0
            assert len(os.listdir(tmpdir)) == 0

    def test_snapshot_event(self) -> None:
        events = [
            {"type": "insert", "content": "garbage"},
            {"type": "snapshot", "content": "clean state"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            _generate_code_frames(events, tmpdir)

            with open(os.path.join(tmpdir, "frame_000001.txt")) as f:
                content = f.read()
            assert content == "clean state"


class TestWriteStatsOverlay:
    def test_writes_stats(self) -> None:
        stats = SubmissionStats(
            duration_seconds=325,
            keystrokes=450,
            tests_passed=5,
            tests_total=7,
            fragments_earned=120,
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            path = f.name

        try:
            _write_stats_overlay(stats, path)
            with open(path) as f:
                content = f.read()

            assert "5m25s" in content
            assert "450" in content
            assert "5/7" in content
            assert "+120" in content
        finally:
            os.unlink(path)


class TestReplayPayloadFixture:
    """Vérifie que les fixtures de test sont valides."""

    def test_replay_payload_from_fixture(self, sample_replay_payload: dict) -> None:
        payload = ReplayPayload.model_validate(sample_replay_payload["payload"])
        assert payload.submission_id == "sub-001"
        assert len(payload.events) == 2
        assert payload.stats.tests_passed == 5
