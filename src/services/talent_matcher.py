"""Service de matching talent ↔ entreprise.

Pipeline :
1. Filtrer les candidats par critères stricts (éliminatoires)
2. Scorer chaque candidat restant par pertinence (pondéré)
3. Trier par score décroissant
4. Retourner les talents matchés avec les critères qui ont matché
"""

from src.models.job_results import MatchedTalent, TalentMatchResult
from src.models.queue_messages import MatchCriteria, TalentMatchPayload, TalentSnapshot
from src.utils.logging import get_logger

logger = get_logger("service.talent_matcher")

# Hiérarchie des titres pour comparaison
_TITLE_HIERARCHY = {
    "Apprenti": 0,
    "Artisan": 1,
    "Maître": 2,
    "Légende": 3,
}


async def match_talents(payload: TalentMatchPayload) -> TalentMatchResult:
    """Match des talents avec les critères d'une entreprise."""
    logger.info(
        "talent_matching_started",
        enterprise_id=payload.enterprise_id,
        candidates_count=len(payload.candidates),
    )

    # Phase 1 : filtrage strict
    filtered = [c for c in payload.candidates if _passes_filters(c, payload.criteria)]

    # Phase 2 : scoring
    scored: list[MatchedTalent] = []
    for candidate in filtered:
        score, matching_criteria = _compute_relevance(candidate, payload.criteria)
        scored.append(MatchedTalent(
            user_id=candidate.user_id,
            username=candidate.username,
            relevance_score=round(score, 4),
            matching_criteria=matching_criteria,
        ))

    # Phase 3 : tri décroissant
    scored.sort(key=lambda t: t.relevance_score, reverse=True)

    result = TalentMatchResult(
        enterprise_id=payload.enterprise_id,
        matched_talents=scored,
        total_candidates=len(payload.candidates),
        total_matched=len(scored),
    )

    logger.info(
        "talent_matching_completed",
        enterprise_id=payload.enterprise_id,
        total_candidates=len(payload.candidates),
        total_matched=len(scored),
    )

    return result


def _passes_filters(candidate: TalentSnapshot, criteria: MatchCriteria) -> bool:
    """Vérifie si un candidat passe les filtres éliminatoires."""
    # Filtre domaine de compétence
    if criteria.skill_domains:
        if not any(d in candidate.skill_domains for d in criteria.skill_domains):
            return False

    # Filtre fragments minimum
    if criteria.min_fragments > 0:
        if candidate.total_fragments < criteria.min_fragments:
            return False

    # Filtre titre minimum
    if criteria.min_title:
        candidate_rank = _TITLE_HIERARCHY.get(candidate.title, -1)
        required_rank = _TITLE_HIERARCHY.get(criteria.min_title, 0)
        if candidate_rank < required_rank:
            return False

    # Filtre pays
    if criteria.country:
        if candidate.country != criteria.country:
            return False

    return True


def _compute_relevance(
    candidate: TalentSnapshot, criteria: MatchCriteria
) -> tuple[float, list[str]]:
    """Calcule un score de pertinence pondéré et les critères matchés.

    Score sur 100, réparti :
    - Domaines matchés : 25 points
    - Fragments : 25 points (normalisé sur max attendu)
    - Titre : 20 points
    - Langages : 15 points
    - Trust score : 15 points
    """
    score = 0.0
    matching: list[str] = []

    # Domaines matchés (25 pts)
    if criteria.skill_domains:
        matched_domains = [d for d in criteria.skill_domains if d in candidate.skill_domains]
        domain_ratio = len(matched_domains) / len(criteria.skill_domains)
        score += 25.0 * domain_ratio
        if matched_domains:
            matching.append(f"domains: {', '.join(matched_domains)}")
    else:
        score += 25.0  # Pas de critère = score max

    # Fragments (25 pts) — normalisé, plafonné à 10K
    fragment_cap = max(criteria.min_fragments * 2, 5000)
    fragment_score = min(candidate.total_fragments / fragment_cap, 1.0)
    score += 25.0 * fragment_score
    if candidate.total_fragments >= criteria.min_fragments:
        matching.append(f"fragments: {candidate.total_fragments}")

    # Titre (20 pts)
    title_rank = _TITLE_HIERARCHY.get(candidate.title, 0)
    title_score = title_rank / 3.0  # max = Légende = 3
    score += 20.0 * title_score
    matching.append(f"title: {candidate.title}")

    # Langages (15 pts)
    if criteria.languages:
        matched_langs = [l for l in criteria.languages if l in candidate.top_languages]
        lang_ratio = len(matched_langs) / len(criteria.languages)
        score += 15.0 * lang_ratio
        if matched_langs:
            matching.append(f"languages: {', '.join(matched_langs)}")
    else:
        score += 15.0

    # Trust score (15 pts)
    score += 15.0 * candidate.trust_score
    if candidate.trust_score >= 0.7:
        matching.append(f"trust: {candidate.trust_score:.0%}")

    return score, matching
