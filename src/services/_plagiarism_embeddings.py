"""Moteur d'embeddings de détection de plagiat via sentence-transformers.

Approche :
1. Encode les deux codes sources en vecteurs denses (384 dimensions)
2. Calcule la similarité cosinus entre les deux vecteurs
3. Retourne un score entre 0 (différent) et 1 (identique)

Utilise all-MiniLM-L6-v2 (~100MB, tourne sur CPU en <50ms).
Le modèle est chargé une seule fois (singleton).
"""

import numpy as np

from src.exceptions import ProcessingError
from src.utils.logging import get_logger

logger = get_logger("plagiarism.embeddings")

_model = None
_model_load_attempted = False


def _get_model():
    """Charge le modèle sentence-transformers (singleton, lazy loading)."""
    global _model, _model_load_attempted

    if _model is not None:
        return _model

    if _model_load_attempted:
        return None

    _model_load_attempted = True

    try:
        from sentence_transformers import SentenceTransformer

        logger.info("loading_embedding_model", model="all-MiniLM-L6-v2")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("embedding_model_loaded")
        return _model
    except ImportError:
        logger.warning("sentence_transformers_not_installed")
        return None
    except Exception as e:
        logger.error("embedding_model_load_failed", error=str(e))
        return None


def _cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Calcule la similarité cosinus entre deux vecteurs."""
    dot = np.dot(vec_a, vec_b)
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _simple_text_hash_similarity(text_a: str, text_b: str) -> float:
    """Fallback basique quand sentence-transformers n'est pas disponible.

    Utilise les character n-grams (shingles) pour une approximation rapide.
    """
    n = 3  # character trigrams

    if len(text_a) < n and len(text_b) < n:
        return 1.0 if text_a == text_b else 0.0

    shingles_a = set(text_a[i : i + n] for i in range(len(text_a) - n + 1))
    shingles_b = set(text_b[i : i + n] for i in range(len(text_b) - n + 1))

    if not shingles_a and not shingles_b:
        return 1.0

    intersection = shingles_a & shingles_b
    union = shingles_a | shingles_b

    return len(intersection) / len(union) if union else 0.0


async def compute_embedding_similarity(code_a: str, code_b: str) -> float:
    """Calcule la similarité sémantique entre deux codes via embeddings.

    Utilise sentence-transformers si disponible, sinon fallback sur character shingles.
    """
    model = _get_model()

    if model is not None:
        try:
            # Encode les deux codes en une seule passe (batch)
            embeddings = model.encode([code_a, code_b], convert_to_numpy=True)
            similarity = _cosine_similarity(embeddings[0], embeddings[1])

            logger.debug(
                "embedding_comparison_done",
                method="sentence_transformers",
                similarity=similarity,
            )
            return max(0.0, min(1.0, similarity))  # Clamp [0, 1]

        except Exception as e:
            logger.warning("embedding_computation_failed", error=str(e))
            # Fallback

    # Fallback : character shingles
    similarity = _simple_text_hash_similarity(code_a, code_b)
    logger.debug(
        "embedding_comparison_done",
        method="shingle_fallback",
        similarity=similarity,
    )
    return similarity
