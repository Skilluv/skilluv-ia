"""Tests des enrichissements v2 du prompt generate_challenge.

Vérifie que orientation_slug / is_training / project_id sont bien consommés
par le prompt system, sans casser le comportement par défaut (backward compat).
"""

from __future__ import annotations

import pytest

from src.models.challenge import ChallengeParams
from src.services._challenge_cache import _build_cache_key
from src.services._challenge_prompts import (
    _effective_difficulty,
    _find_orientation,
    _load_orientations_catalog,
    build_system_prompt,
    build_user_prompt,
)


# =========================================================================
# Chargement catalogue
# =========================================================================


class TestFindOrientation:
    def test_empty_slug_returns_none(self):
        assert _find_orientation("") is None

    def test_unknown_slug_returns_none(self):
        assert _find_orientation("does-not-exist") is None

    def test_known_slug_returns_orientation(self):
        o = _find_orientation("dev-backend")
        assert o is not None
        assert "critical_skills" in o
        assert isinstance(o["critical_skills"], list)


# =========================================================================
# Difficulté effective (is_training)
# =========================================================================


class TestEffectiveDifficulty:
    def test_training_lowers_by_one(self):
        p = ChallengeParams(
            skill_domain="code", difficulty=3, duration_minutes=30, is_training=True,
        )
        assert _effective_difficulty(p) == 2

    def test_training_floors_at_1(self):
        p = ChallengeParams(
            skill_domain="code", difficulty=1, duration_minutes=30, is_training=True,
        )
        assert _effective_difficulty(p) == 1

    def test_non_training_returns_original(self):
        p = ChallengeParams(
            skill_domain="code", difficulty=4, duration_minutes=30, is_training=False,
        )
        assert _effective_difficulty(p) == 4


# =========================================================================
# Enrichissement du prompt system
# =========================================================================


class TestPromptOrientation:
    def test_no_orientation_prompt_stays_clean(self):
        p = ChallengeParams(
            skill_domain="code", difficulty=2, duration_minutes=30,
        )
        prompt = build_system_prompt(p)
        assert "ORIENTATION MÉTIER" not in prompt

    def test_orientation_injects_label_and_critical_skills(self):
        p = ChallengeParams(
            skill_domain="code", difficulty=3, duration_minutes=45,
            orientation_slug="dev-backend",
        )
        prompt = build_system_prompt(p)
        assert "ORIENTATION MÉTIER" in prompt
        assert "dev-backend" in prompt
        # Skills critiques de dev-backend présents (voir orientations_catalog.json)
        for skill in ["python", "sql", "rest-api"]:
            assert skill in prompt, f"skill {skill} manquant dans le prompt"

    def test_orientation_english_uses_english_label(self):
        p = ChallengeParams(
            skill_domain="security", difficulty=3, duration_minutes=60,
            orientation_slug="pentester-web", language="en",
        )
        prompt = build_system_prompt(p)
        assert "Web Penetration Tester" in prompt

    def test_unknown_orientation_ignored_silently(self):
        p = ChallengeParams(
            skill_domain="code", difficulty=2, duration_minutes=30,
            orientation_slug="nonexistent-slug",
        )
        prompt = build_system_prompt(p)
        assert "ORIENTATION MÉTIER" not in prompt
        assert "nonexistent-slug" not in prompt


class TestPromptTraining:
    def test_training_flag_adds_pedagogic_block(self):
        p = ChallengeParams(
            skill_domain="code", difficulty=3, duration_minutes=30, is_training=True,
        )
        prompt = build_system_prompt(p)
        assert "MODE ENTRAÎNEMENT" in prompt
        assert "apprentissage" in prompt.lower()

    def test_no_training_no_block(self):
        p = ChallengeParams(
            skill_domain="code", difficulty=3, duration_minutes=30, is_training=False,
        )
        prompt = build_system_prompt(p)
        assert "MODE ENTRAÎNEMENT" not in prompt

    def test_training_lowers_difficulty_line(self):
        p = ChallengeParams(
            skill_domain="code", difficulty=3, duration_minutes=30, is_training=True,
        )
        prompt = build_system_prompt(p)
        # La ligne "Difficulté 2/5" doit apparaître (3 - 1 = 2), pas "3/5"
        assert "Difficulté 2/5" in prompt
        assert "Difficulté 3/5" not in prompt


class TestPromptProjectId:
    def test_project_id_injects_context_block(self):
        p = ChallengeParams(
            skill_domain="code", difficulty=2, duration_minutes=30,
            project_id="proj-abc-123",
        )
        prompt = build_system_prompt(p)
        assert "CONTEXTE PROJET OSS" in prompt
        assert "proj-abc-123" in prompt

    def test_no_project_no_block(self):
        p = ChallengeParams(skill_domain="code", difficulty=2, duration_minutes=30)
        prompt = build_system_prompt(p)
        assert "CONTEXTE PROJET OSS" not in prompt


class TestPromptCombination:
    def test_all_three_fields_appear_together(self):
        p = ChallengeParams(
            skill_domain="code", difficulty=4, duration_minutes=60,
            orientation_slug="dev-backend",
            is_training=True,
            project_id="proj-42",
        )
        prompt = build_system_prompt(p)
        assert "ORIENTATION MÉTIER" in prompt
        assert "MODE ENTRAÎNEMENT" in prompt
        assert "CONTEXTE PROJET OSS" in prompt
        # difficulté effective = 3 (4 - 1)
        assert "Difficulté 3/5" in prompt


# =========================================================================
# Cache key inclut les nouveaux champs
# =========================================================================


class TestCacheKeyIncludesV2Fields:
    def _base(self, **overrides):
        base = dict(skill_domain="code", difficulty=3, duration_minutes=30)
        base.update(overrides)
        return ChallengeParams(**base)

    def test_orientation_slug_changes_key(self):
        k1 = _build_cache_key(self._base(orientation_slug=""))
        k2 = _build_cache_key(self._base(orientation_slug="dev-backend"))
        assert k1 != k2

    def test_is_training_changes_key(self):
        k1 = _build_cache_key(self._base(is_training=False))
        k2 = _build_cache_key(self._base(is_training=True))
        assert k1 != k2

    def test_project_id_changes_key(self):
        k1 = _build_cache_key(self._base(project_id=""))
        k2 = _build_cache_key(self._base(project_id="proj-1"))
        assert k1 != k2

    def test_identical_params_same_key(self):
        p1 = self._base(orientation_slug="dev-backend", is_training=True, project_id="p")
        p2 = self._base(orientation_slug="dev-backend", is_training=True, project_id="p")
        assert _build_cache_key(p1) == _build_cache_key(p2)
