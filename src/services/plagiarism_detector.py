"""Service de détection de plagiat — hybride AST + embeddings.

Pipeline :
1. Normalise le code source (supprime commentaires, whitespace, renomme variables)
2. Calcule similarité AST via tree-sitter (structurelle)
3. Calcule similarité embeddings via sentence-transformers (sémantique)
4. Score combiné : AST_WEIGHT × AST + EMBEDDING_WEIGHT × embedding
5. Flag si score > THRESHOLD
"""

from src.config import settings
from src.models.job_results import PlagiarismMatch, PlagiarismResult
from src.models.queue_messages import PlagiarismPayload, PlagiarismSubmission
from src.services._plagiarism_ast import compute_ast_similarity
from src.services._plagiarism_embeddings import compute_embedding_similarity
from src.utils.logging import get_logger

logger = get_logger("service.plagiarism_detector")


async def detect_plagiarism(payload: PlagiarismPayload) -> PlagiarismResult:
    """Détecte le plagiat entre une soumission et une liste de soumissions à comparer."""
    logger.info(
        "plagiarism_detection_started",
        submission_id=payload.submission_id,
        challenge_id=payload.challenge_id,
        language=payload.language,
        compare_count=len(payload.compare_with),
    )

    matches: list[PlagiarismMatch] = []
    highest_score = 0.0

    for candidate in payload.compare_with:
        match = await _compare_submissions(
            source_code=payload.source_code,
            candidate=candidate,
            language=payload.language,
        )
        matches.append(match)
        if match.combined_score > highest_score:
            highest_score = match.combined_score

    flagged = highest_score >= settings.plagiarism_threshold

    result = PlagiarismResult(
        submission_id=payload.submission_id,
        challenge_id=payload.challenge_id,
        matches=matches,
        highest_score=round(highest_score, 4),
        flagged=flagged,
    )

    logger.info(
        "plagiarism_detection_completed",
        submission_id=payload.submission_id,
        highest_score=highest_score,
        flagged=flagged,
        matches_count=len(matches),
    )

    return result


async def _compare_submissions(
    source_code: str,
    candidate: PlagiarismSubmission,
    language: str,
) -> PlagiarismMatch:
    """Compare deux soumissions avec les deux moteurs."""
    # Moteur 1 : similarité AST (structurelle)
    ast_sim = compute_ast_similarity(source_code, candidate.source_code, language)

    # Moteur 2 : similarité embeddings (sémantique)
    emb_sim = await compute_embedding_similarity(source_code, candidate.source_code)

    # Score combiné pondéré
    combined = (
        settings.plagiarism_ast_weight * ast_sim
        + settings.plagiarism_embedding_weight * emb_sim
    )

    return PlagiarismMatch(
        compared_submission_id=candidate.submission_id,
        compared_user_id=candidate.user_id,
        ast_similarity=round(ast_sim, 4),
        embedding_similarity=round(emb_sim, 4),
        combined_score=round(combined, 4),
        is_plagiarism=combined >= settings.plagiarism_threshold,
    )
