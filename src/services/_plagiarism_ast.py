"""Moteur AST de détection de plagiat via tree-sitter.

Approche :
1. Parse le code source en AST
2. Normalise l'AST (supprime noms de variables, commentaires, littéraux string)
3. Sérialise l'AST normalisé en string
4. Compare les deux strings normalisées via ratio de Levenshtein simplifié

Supporte les langages avec grammaires tree-sitter disponibles.
Fallback sur comparaison textuelle normalisée pour les langages non supportés.
"""

import hashlib
import re

from src.utils.logging import get_logger

logger = get_logger("plagiarism.ast")

# Mapping langage → nom du package tree-sitter
_LANGUAGE_MAP: dict[str, str] = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "rust": "rust",
    "go": "go",
    "ruby": "ruby",
    "php": "php",
}

# Cache des parsers tree-sitter par langage
_parsers: dict[str, object] = {}


def _get_parser(language: str):
    """Retourne un parser tree-sitter pour le langage donné, ou None si non disponible."""
    if language not in _LANGUAGE_MAP:
        return None

    if language in _parsers:
        return _parsers[language]

    try:
        import tree_sitter
        import importlib

        # tree-sitter >= 0.24 : les langages sont des packages séparés
        lang_module = importlib.import_module(f"tree_sitter_{_LANGUAGE_MAP[language]}")
        lang = tree_sitter.Language(lang_module.language())
        parser = tree_sitter.Parser(lang)
        _parsers[language] = parser
        return parser
    except (ImportError, Exception) as e:
        logger.debug("tree_sitter_unavailable", language=language, error=str(e))
        _parsers[language] = None
        return None


def _extract_ast_structure(node, depth: int = 0) -> list[str]:
    """Extrait la structure de l'AST en ignorant les valeurs concrètes.

    Garde : types de noeuds, profondeur, structure de contrôle
    Ignore : identifiants, littéraux, commentaires
    """
    # Types à ignorer complètement
    ignore_types = {"comment", "line_comment", "block_comment", "string", "string_literal"}
    if node.type in ignore_types:
        return []

    # Types dont on garde le type mais pas la valeur
    leaf_replace_types = {"identifier", "number", "integer", "float", "true", "false", "none"}

    tokens: list[str] = []

    if node.child_count == 0:
        # Feuille
        if node.type in leaf_replace_types:
            tokens.append(f"{depth}:VAR")
        else:
            tokens.append(f"{depth}:{node.type}")
    else:
        # Noeud interne : garde le type structurel
        tokens.append(f"{depth}:{node.type}(")
        for child in node.children:
            tokens.extend(_extract_ast_structure(child, depth + 1))
        tokens.append(f"{depth}:)")

    return tokens


def _normalize_text(code: str) -> str:
    """Normalisation textuelle fallback quand tree-sitter n'est pas disponible.

    - Supprime commentaires (// et /* */ et #)
    - Supprime strings
    - Normalise whitespace
    - Remplace identifiants par des tokens génériques
    """
    # Supprimer commentaires multi-lignes
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    # Supprimer commentaires single-line
    code = re.sub(r"(//|#).*$", "", code, flags=re.MULTILINE)
    # Supprimer strings
    code = re.sub(r'"[^"]*"', '"STR"', code)
    code = re.sub(r"'[^']*'", "'STR'", code)
    # Normaliser whitespace
    code = re.sub(r"\s+", " ", code).strip()
    return code


def _sequence_similarity(seq_a: list[str], seq_b: list[str]) -> float:
    """Calcule la similarité entre deux séquences de tokens AST.

    Utilise le ratio de tokens communs (Jaccard sur bigrammes)
    plutôt que Levenshtein complet (trop lent pour de gros ASTs).
    """
    if not seq_a and not seq_b:
        return 1.0
    if not seq_a or not seq_b:
        return 0.0

    # Bigrammes pour capturer l'ordre structurel
    bigrams_a = set(zip(seq_a, seq_a[1:]))
    bigrams_b = set(zip(seq_b, seq_b[1:]))

    if not bigrams_a and not bigrams_b:
        # Séquences de 1 token chacune
        return 1.0 if seq_a == seq_b else 0.0

    intersection = bigrams_a & bigrams_b
    union = bigrams_a | bigrams_b

    return len(intersection) / len(union) if union else 0.0


def _text_similarity(text_a: str, text_b: str) -> float:
    """Similarité textuelle via hash de n-grammes (fallback)."""
    if not text_a and not text_b:
        return 1.0
    if not text_a or not text_b:
        return 0.0

    # Tokens par mots/symboles
    tokens_a = text_a.split()
    tokens_b = text_b.split()

    bigrams_a = set(zip(tokens_a, tokens_a[1:]))
    bigrams_b = set(zip(tokens_b, tokens_b[1:]))

    if not bigrams_a and not bigrams_b:
        return 1.0 if tokens_a == tokens_b else 0.0

    intersection = bigrams_a & bigrams_b
    union = bigrams_a | bigrams_b

    return len(intersection) / len(union) if union else 0.0


def compute_ast_similarity(code_a: str, code_b: str, language: str) -> float:
    """Calcule la similarité structurelle entre deux codes sources.

    Utilise tree-sitter si disponible, sinon fallback sur normalisation textuelle.
    """
    parser = _get_parser(language)

    if parser is not None:
        try:
            tree_a = parser.parse(code_a.encode())
            tree_b = parser.parse(code_b.encode())

            tokens_a = _extract_ast_structure(tree_a.root_node)
            tokens_b = _extract_ast_structure(tree_b.root_node)

            similarity = _sequence_similarity(tokens_a, tokens_b)
            logger.debug(
                "ast_comparison_done",
                language=language,
                method="tree_sitter",
                tokens_a=len(tokens_a),
                tokens_b=len(tokens_b),
                similarity=similarity,
            )
            return similarity

        except Exception as e:
            logger.warning("tree_sitter_parse_failed", language=language, error=str(e))
            # Fallback
            pass

    # Fallback : normalisation textuelle
    norm_a = _normalize_text(code_a)
    norm_b = _normalize_text(code_b)
    similarity = _text_similarity(norm_a, norm_b)

    logger.debug(
        "ast_comparison_done",
        language=language,
        method="text_fallback",
        similarity=similarity,
    )
    return similarity
