"""Embeddings sémantiques pour le talent matcher — Phase 5.4.

Approche :
- Compose une "phrase" descriptive du besoin de l'entreprise et du profil du talent
- Encode les deux avec sentence-transformers (all-MiniLM-L6-v2, déjà utilisé pour
  la détection de plagiat, donc pas de dépendance supplémentaire)
- Similarité cosinus → score sémantique [0, 1]

Fallback shingles si sentence-transformers indisponible. Cache pour éviter
re-encodage inutile.
"""

from __future__ import annotations

import numpy as np

from src.utils.logging import get_logger

logger = get_logger("service.matcher_embeddings")

_model = None
_model_load_attempted = False
_encode_cache: dict[str, np.ndarray] = {}


def _get_model():
    global _model, _model_load_attempted
    if _model is not None:
        return _model
    if _model_load_attempted:
        return None
    _model_load_attempted = True
    try:
        from sentence_transformers import SentenceTransformer

        logger.info("loading_matcher_embedding_model", model="all-MiniLM-L6-v2")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        return _model
    except ImportError:
        logger.warning("sentence_transformers_not_installed_matcher_fallback")
        return None
    except Exception as e:
        logger.error("matcher_embedding_model_load_failed", error=str(e))
        return None


def _encode(text: str) -> np.ndarray | None:
    text = text.strip()
    if not text:
        return None
    if text in _encode_cache:
        return _encode_cache[text]
    model = _get_model()
    if model is None:
        return None
    vec = model.encode(text, convert_to_numpy=True)
    # Cap cache size to prevent unbounded growth on long-running workers.
    if len(_encode_cache) < 5000:
        _encode_cache[text] = vec
    return vec


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _shingle_sim(a: str, b: str, n: int = 3) -> float:
    """Fallback : trigram-set Jaccard."""
    if not a or not b:
        return 0.0
    A = {a[i : i + n] for i in range(len(a) - n + 1)}
    B = {b[i : i + n] for i in range(len(b) - n + 1)}
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def semantic_similarity(job_text: str, profile_text: str) -> float:
    """Retourne un score [0, 1] entre la description du poste et du profil."""
    va = _encode(job_text)
    vb = _encode(profile_text)
    if va is not None and vb is not None:
        s = _cosine(va, vb)
        return max(0.0, min(1.0, (s + 1.0) / 2.0))  # cosine ∈ [-1,1] → [0,1]
    return _shingle_sim(job_text.lower(), profile_text.lower())


def build_job_text(
    skill_domains: list[str],
    languages: list[str],
    min_title: str | None,
    country: str | None,
    extra_description: str | None = None,
) -> str:
    parts = []
    if skill_domains:
        parts.append(f"Domaines de compétence recherchés : {', '.join(skill_domains)}.")
    if languages:
        parts.append(f"Langages / technologies : {', '.join(languages)}.")
    if min_title:
        parts.append(f"Niveau minimum requis : {min_title}.")
    if country:
        parts.append(f"Localisation cible : {country}.")
    if extra_description:
        parts.append(extra_description.strip())
    return " ".join(parts)


def build_profile_text(
    skill_domains: list[str],
    top_languages: list[str],
    title: str,
    country: str | None,
    bio: str | None = None,
) -> str:
    parts = [
        f"Talent {title}.",
        f"Domaines : {', '.join(skill_domains) if skill_domains else 'n/a'}.",
        f"Langages : {', '.join(top_languages) if top_languages else 'n/a'}.",
    ]
    if country:
        parts.append(f"Pays : {country}.")
    if bio:
        parts.append(bio.strip())
    return " ".join(parts)
