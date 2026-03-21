"""Tests du rendu des frames de code en images."""

import os
import tempfile

import pytest

from src.services._frame_renderer import (
    _tokenize_line,
    render_frame,
    render_frames_to_dir,
)


class TestTokenizeLine:
    def test_keyword_detection(self) -> None:
        tokens = _tokenize_line("def hello():")
        words = [t[0] for t in tokens]
        assert "def" in words

    def test_string_detection(self) -> None:
        tokens = _tokenize_line('x = "hello"')
        strings = [t[0] for t in tokens if t[0].startswith('"')]
        assert len(strings) == 1

    def test_number_detection(self) -> None:
        tokens = _tokenize_line("x = 42")
        numbers = [t[0] for t in tokens if t[0].isdigit()]
        assert "42" in numbers

    def test_comment_detection(self) -> None:
        tokens = _tokenize_line("x = 1  # comment")
        # Le commentaire est un seul token à la fin
        assert any("comment" in t[0] for t in tokens)

    def test_empty_line(self) -> None:
        tokens = _tokenize_line("")
        assert tokens == []

    def test_mixed_code(self) -> None:
        tokens = _tokenize_line('for i in range(10):')
        words = [t[0] for t in tokens]
        assert "for" in words
        assert "in" in words
        assert "range" in words


class TestRenderFrame:
    def test_returns_png_bytes(self) -> None:
        data = render_frame("print('hello')", frame_index=0, total_frames=1)
        assert isinstance(data, bytes)
        assert len(data) > 100
        # PNG magic bytes
        assert data[:4] == b"\x89PNG"

    def test_with_stats(self) -> None:
        data = render_frame(
            "x = 1\ny = 2",
            frame_index=0,
            total_frames=5,
            stats_text="Duration: 5m00s | Tests: 3/3",
        )
        assert data[:4] == b"\x89PNG"

    def test_multiline_code(self) -> None:
        code = "\n".join([f"line_{i} = {i}" for i in range(50)])
        data = render_frame(code, frame_index=25, total_frames=50)
        assert data[:4] == b"\x89PNG"

    def test_empty_code(self) -> None:
        data = render_frame("", frame_index=0, total_frames=1)
        assert data[:4] == b"\x89PNG"


class TestRenderFramesToDir:
    def test_generates_png_files(self) -> None:
        events = [
            {"type": "insert", "content": "def "},
            {"type": "insert", "content": "hello():"},
            {"type": "insert", "content": "\n    return 42"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            count = render_frames_to_dir(events, tmpdir, stats_text="Test stats")
            assert count == 3

            files = sorted(os.listdir(tmpdir))
            assert len(files) == 3
            assert files[0] == "frame_000000.png"

            # Vérifier que ce sont des PNG
            with open(os.path.join(tmpdir, files[0]), "rb") as f:
                assert f.read(4) == b"\x89PNG"

    def test_empty_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            count = render_frames_to_dir([], tmpdir)
            assert count == 0
            assert len(os.listdir(tmpdir)) == 0
