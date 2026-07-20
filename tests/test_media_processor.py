"""Tests du service de traitement média."""

import os
import tempfile

from src.models.queue_messages import ReplayPayload, SubmissionStats
from src.services.media_processor import (
    _format_stats_text,
    _generate_text_frames,
)


class TestGenerateTextFrames:
    def test_insert_events(self) -> None:
        events = [
            {"type": "insert", "content": "def "},
            {"type": "insert", "content": "hello():"},
            {"type": "insert", "content": "\n    return 'world'"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            count = _generate_text_frames(events, tmpdir)
            assert count == 3

            with open(os.path.join(tmpdir, "frame_000002.txt")) as f:
                content = f.read()
            assert content == "def hello():\n    return 'world'"

    def test_delete_events(self) -> None:
        events = [
            {"type": "insert", "content": "hello world"},
            {"type": "delete", "count": 5},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            count = _generate_text_frames(events, tmpdir)
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
            _generate_text_frames(events, tmpdir)

            with open(os.path.join(tmpdir, "frame_000001.txt")) as f:
                content = f.read()
            assert content == "new code"

    def test_empty_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            count = _generate_text_frames([], tmpdir)
            assert count == 0
            assert len(os.listdir(tmpdir)) == 0

    def test_snapshot_event(self) -> None:
        events = [
            {"type": "insert", "content": "garbage"},
            {"type": "snapshot", "content": "clean state"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            _generate_text_frames(events, tmpdir)

            with open(os.path.join(tmpdir, "frame_000001.txt")) as f:
                content = f.read()
            assert content == "clean state"


class TestFormatStatsText:
    def test_formats_correctly(self) -> None:
        stats = SubmissionStats(
            duration_seconds=325,
            keystrokes=450,
            tests_passed=5,
            tests_total=7,
            fragments_earned=120,
        )
        text = _format_stats_text(stats)

        assert "5m25s" in text
        assert "450" in text
        assert "5/7" in text
        assert "+120" in text


class TestReplayPayloadFixture:
    def test_replay_payload_from_fixture(self, sample_replay_payload: dict) -> None:
        payload = ReplayPayload.model_validate(sample_replay_payload["payload"])
        assert payload.submission_id == "sub-001"
        assert len(payload.events) == 2
        assert payload.stats.tests_passed == 5
