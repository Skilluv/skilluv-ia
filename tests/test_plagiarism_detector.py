"""Tests du service de détection de plagiat."""

import pytest

from src.models.queue_messages import PlagiarismPayload, PlagiarismSubmission
from src.services._plagiarism_ast import (
    _normalize_text,
    _sequence_similarity,
    _text_similarity,
    compute_ast_similarity,
)
from src.services._plagiarism_embeddings import (
    _simple_text_hash_similarity,
    compute_embedding_similarity,
)
from src.services.plagiarism_detector import detect_plagiarism

# === Tests AST ===


class TestNormalizeText:
    def test_removes_single_line_comments(self) -> None:
        code = "x = 1  # un commentaire\ny = 2"
        result = _normalize_text(code)
        assert "commentaire" not in result

    def test_removes_multiline_comments(self) -> None:
        code = "x = 1\n/* blah\nblah */\ny = 2"
        result = _normalize_text(code)
        assert "blah" not in result

    def test_replaces_strings(self) -> None:
        code = 'print("hello world")'
        result = _normalize_text(code)
        assert "hello world" not in result
        assert "STR" in result

    def test_normalizes_whitespace(self) -> None:
        code = "x  =   1\n\n\ny  = 2"
        result = _normalize_text(code)
        assert "  " not in result


class TestSequenceSimilarity:
    def test_identical_sequences(self) -> None:
        seq = ["0:module(", "1:function(", "2:VAR", "1:)", "0:)"]
        assert _sequence_similarity(seq, seq) == 1.0

    def test_empty_sequences(self) -> None:
        assert _sequence_similarity([], []) == 1.0

    def test_one_empty(self) -> None:
        assert _sequence_similarity(["a", "b"], []) == 0.0

    def test_completely_different(self) -> None:
        seq_a = ["a", "b", "c", "d"]
        seq_b = ["w", "x", "y", "z"]
        assert _sequence_similarity(seq_a, seq_b) == 0.0

    def test_partial_overlap(self) -> None:
        seq_a = ["a", "b", "c", "d"]
        seq_b = ["a", "b", "e", "f"]
        sim = _sequence_similarity(seq_a, seq_b)
        assert 0.0 < sim < 1.0


class TestTextSimilarity:
    def test_identical_texts(self) -> None:
        assert _text_similarity("x = 1 y = 2", "x = 1 y = 2") == 1.0

    def test_different_texts(self) -> None:
        sim = _text_similarity("def foo bar", "class qux baz nope")
        assert sim < 0.3


class TestComputeAstSimilarity:
    def test_identical_code(self) -> None:
        code = "def hello():\n    return 'world'"
        sim = compute_ast_similarity(code, code, "python")
        assert sim == 1.0

    def test_variable_rename_high_similarity(self) -> None:
        """Le renommage de variables devrait donner un score élevé."""
        code_a = "def calc(x, y):\n    result = x + y\n    return result"
        code_b = "def compute(a, b):\n    total = a + b\n    return total"
        sim = compute_ast_similarity(code_a, code_b, "python")
        # Que ce soit via tree-sitter ou fallback, le score devrait être > 0.5
        assert sim > 0.5

    def test_completely_different_code(self) -> None:
        code_a = "def sort(arr):\n    for i in range(len(arr)):\n        for j in range(i):\n            if arr[j] > arr[j+1]:\n                arr[j], arr[j+1] = arr[j+1], arr[j]"
        code_b = "class Node:\n    def __init__(self, val):\n        self.val = val\n        self.next = None"
        sim = compute_ast_similarity(code_a, code_b, "python")
        assert sim < 0.5

    def test_unknown_language_uses_fallback(self) -> None:
        code = "some code here"
        sim = compute_ast_similarity(code, code, "brainfuck")
        assert sim == 1.0  # Identique même en fallback


# === Tests Embeddings ===


class TestSimpleTextHashSimilarity:
    def test_identical_strings(self) -> None:
        assert _simple_text_hash_similarity("hello world", "hello world") == 1.0

    def test_empty_strings(self) -> None:
        assert _simple_text_hash_similarity("", "") == 1.0

    def test_completely_different(self) -> None:
        sim = _simple_text_hash_similarity("abcdef", "xyz123")
        assert sim < 0.2

    def test_similar_strings(self) -> None:
        sim = _simple_text_hash_similarity(
            "def hello_world():", "def hello_world(x):"
        )
        assert sim > 0.7


def _requires_real_embedding_model() -> None:
    """Skip si sentence-transformers ne peut pas se charger (HF Hub / offline).

    Le fallback shingle_fallback ne donne pas les mêmes garanties sémantiques :
    les assertions "similaire mais réécrit -> sim > 0.5" ne tiennent que sur
    le vrai modèle. On skip explicitement plutôt que d'échouer en local sans réseau.
    """
    from src.services._plagiarism_embeddings import _get_model

    if _get_model() is None:
        pytest.skip(
            "sentence-transformers model unavailable (offline / HF rate limit) — "
            "test sémantique nécessite le vrai modèle"
        )


class TestComputeEmbeddingSimilarity:
    @pytest.mark.asyncio
    async def test_identical_code(self) -> None:
        # Ce test tient même en fallback (shingles identiques -> 1.0).
        code = "def hello():\n    return 'world'"
        sim = await compute_embedding_similarity(code, code)
        assert sim > 0.95

    @pytest.mark.asyncio
    async def test_similar_code(self) -> None:
        _requires_real_embedding_model()
        code_a = "def add(x, y):\n    return x + y"
        code_b = "def sum(a, b):\n    return a + b"
        sim = await compute_embedding_similarity(code_a, code_b)
        assert sim > 0.5

    @pytest.mark.asyncio
    async def test_different_code(self) -> None:
        _requires_real_embedding_model()
        code_a = "for i in range(10):\n    print(i)"
        code_b = "class Database:\n    def __init__(self, host, port):\n        self.connection = connect(host, port)"
        sim = await compute_embedding_similarity(code_a, code_b)
        assert sim < 0.8


# === Tests intégration plagiarism_detector ===


class TestDetectPlagiarism:
    @pytest.mark.asyncio
    async def test_identical_code_flagged(self) -> None:
        payload = PlagiarismPayload(
            submission_id="sub-001",
            challenge_id="chall-001",
            source_code="def hello():\n    return 'world'",
            language="python",
            compare_with=[
                PlagiarismSubmission(
                    submission_id="sub-002",
                    user_id="user-002",
                    source_code="def hello():\n    return 'world'",
                ),
            ],
        )
        result = await detect_plagiarism(payload)

        assert result.submission_id == "sub-001"
        assert result.flagged is True
        assert result.highest_score >= 0.80
        assert len(result.matches) == 1
        assert result.matches[0].is_plagiarism is True

    @pytest.mark.asyncio
    async def test_different_code_not_flagged(self) -> None:
        payload = PlagiarismPayload(
            submission_id="sub-001",
            challenge_id="chall-001",
            source_code="def bubble_sort(arr):\n    for i in range(len(arr)):\n        for j in range(len(arr)-1):\n            if arr[j] > arr[j+1]:\n                arr[j], arr[j+1] = arr[j+1], arr[j]\n    return arr",
            language="python",
            compare_with=[
                PlagiarismSubmission(
                    submission_id="sub-002",
                    user_id="user-002",
                    source_code="class LinkedList:\n    def __init__(self):\n        self.head = None\n    def append(self, val):\n        node = Node(val)\n        if not self.head:\n            self.head = node\n            return\n        current = self.head\n        while current.next:\n            current = current.next\n        current.next = node",
                ),
            ],
        )
        result = await detect_plagiarism(payload)

        assert result.flagged is False
        assert result.highest_score < 0.80

    @pytest.mark.asyncio
    async def test_multiple_comparisons(self) -> None:
        payload = PlagiarismPayload(
            submission_id="sub-001",
            challenge_id="chall-001",
            source_code="x = 1\ny = 2\nprint(x + y)",
            language="python",
            compare_with=[
                PlagiarismSubmission(
                    submission_id="sub-002",
                    user_id="user-002",
                    source_code="a = 1\nb = 2\nprint(a + b)",
                ),
                PlagiarismSubmission(
                    submission_id="sub-003",
                    user_id="user-003",
                    source_code="class Foo:\n    pass",
                ),
            ],
        )
        result = await detect_plagiarism(payload)

        assert len(result.matches) == 2
        # Le premier devrait être plus similaire que le second
        assert result.matches[0].combined_score > result.matches[1].combined_score

    @pytest.mark.asyncio
    async def test_empty_compare_list(self) -> None:
        payload = PlagiarismPayload(
            submission_id="sub-001",
            challenge_id="chall-001",
            source_code="print('hello')",
            language="python",
            compare_with=[],
        )
        result = await detect_plagiarism(payload)

        assert result.flagged is False
        assert result.highest_score == 0.0
        assert len(result.matches) == 0
