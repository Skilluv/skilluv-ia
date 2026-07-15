"""Tests des embeddings sémantiques du matcher — Phase 5.4.

Le shingles fallback est déterministe et suffit à valider le contrat sans
avoir besoin de charger sentence-transformers dans le CI.
"""

from src.services._matcher_embeddings import (
    _shingle_sim,
    build_job_text,
    build_profile_text,
    semantic_similarity,
)


def test_shingle_sim_identical_is_one():
    assert _shingle_sim("hello world", "hello world") == 1.0


def test_shingle_sim_disjoint_is_zero():
    assert _shingle_sim("abcd", "xyzt") == 0.0


def test_shingle_sim_partial_between_zero_and_one():
    s = _shingle_sim("python developer", "python engineer")
    assert 0 < s < 1


def test_semantic_similarity_higher_on_related_texts():
    job = build_job_text(
        skill_domains=["code"],
        languages=["python", "django"],
        min_title="Artisan",
        country="FR",
        extra_description="Développeur backend Python senior",
    )
    good = build_profile_text(
        skill_domains=["code"],
        top_languages=["python", "django"],
        title="Artisan",
        country="FR",
        bio="Backend Python 5 ans expérience Django",
    )
    bad = build_profile_text(
        skill_domains=["design"],
        top_languages=["figma"],
        title="Apprenti",
        country="US",
        bio="UI designer starting out",
    )
    s_good = semantic_similarity(job, good)
    s_bad = semantic_similarity(job, bad)
    assert s_good > s_bad


def test_semantic_similarity_bounded():
    s = semantic_similarity("abc", "abc")
    assert 0.0 <= s <= 1.0
