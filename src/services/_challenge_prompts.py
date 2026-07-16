"""Prompts spécialisés par domaine pour la génération de challenges.

Chaque domaine (code, design, game, security) a :
- Un contexte métier spécifique
- Des exemples de challenges typiques
- Des critères d'évaluation adaptés
- Des consignes pour les test cases
"""

import json
from functools import lru_cache
from pathlib import Path

from src.models.challenge import ChallengeParams


@lru_cache(maxsize=1)
def _load_orientations_catalog() -> dict:
    path = Path(__file__).resolve().parents[1] / "data" / "orientations_catalog.json"
    if not path.exists():
        return {"orientations": []}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _find_orientation(slug: str) -> dict | None:
    if not slug:
        return None
    for o in _load_orientations_catalog().get("orientations", []):
        if o.get("slug") == slug:
            return o
    return None

# === Guides par domaine ===

DOMAIN_CONTEXTS = {
    "code": {
        "description": "Challenge de programmation avec test cases automatisés",
        "context": """Tu génères des challenges de programmation.

TYPES DE CHALLENGES PAR DIFFICULTE :
- 1/5 : Manipulation de strings, boucles simples, conditions (ex: compter les voyelles, inverser un mot)
- 2/5 : Tableaux, dictionnaires, fonctions récursives simples (ex: tri basique, recherche, validation)
- 3/5 : Algorithmes classiques, structures de données (ex: arbres, graphes simples, programmation dynamique basique)
- 4/5 : Optimisation, algorithmes avancés, design patterns (ex: plus court chemin, parsing, systèmes de cache)
- 5/5 : Architecture complexe, algorithmes de compétition, contraintes strictes (ex: interpréteur, compilateur mini, consensus distribué)

EXIGENCES TEST CASES :
- Chaque test case doit avoir un input et un expected_output EXACTEMENT vérifiables
- Input : toujours une string (sera passée à stdin ou comme argument)
- Expected output : toujours une string (sera comparée à stdout)
- Les tests cachés doivent couvrir : limites (0, négatifs, très grands), edge cases, cas vides, performances""",

        "examples": """EXEMPLES DE BONS CHALLENGES :
- "Le Palindrome Parfait" (diff 1) : vérifier si un mot est un palindrome en ignorant la casse
- "La Tour de Hanoi Optimisée" (diff 3) : résoudre avec le minimum de mouvements et afficher chaque étape
- "Le Routeur de Paquets" (diff 5) : implémenter un routage réseau avec table de routage dynamique""",
    },

    "design": {
        "description": "Challenge de design UI/UX avec critères visuels et d'ergonomie",
        "context": """Tu génères des challenges de design UI/UX.

IMPORTANT : Ces challenges ne sont PAS vérifiables par test cases automatisés classiques.
Les test_cases servent ici de CHECKLIST de critères à évaluer :
- input = "Critère à vérifier"
- expected_output = "Ce qui est attendu (description textuelle)"
- description = "Pourquoi ce critère est important"

TYPES DE CHALLENGES PAR DIFFICULTE :
- 1/5 : Reproduire un composant simple (bouton, carte, formulaire de login)
- 2/5 : Créer une page complète à partir d'un wireframe (landing page, dashboard basique)
- 3/5 : Designer un flow complet (onboarding, checkout, recherche avec filtres)
- 4/5 : Design system partiel (palette, typographie, composants cohérents, responsive)
- 5/5 : Refonte UX complète (audit, proposition, prototypage, accessibilité WCAG AA)

CRITERES D'EVALUATION :
- Hiérarchie visuelle et lisibilité
- Cohérence des espacements et alignements
- Choix typographiques et palette de couleurs
- Responsive design (mobile, tablette, desktop)
- Accessibilité (contraste, taille des cibles tactiles)
- Micro-interactions et feedback utilisateur""",

        "examples": """EXEMPLES DE BONS CHALLENGES :
- "Le Dashboard Météo" (diff 2) : designer un dashboard qui affiche la météo de 5 villes avec graphiques
- "L'Onboarding Parfait" (diff 3) : créer un flow d'inscription en 3 étapes avec progression et validation
- "Le Design System Forge" (diff 5) : créer un mini design system (5 composants, 2 thèmes, responsive)""",
    },

    "game": {
        "description": "Challenge de développement de jeu (mécanique, gameplay, rendu)",
        "context": """Tu génères des challenges de game development.

IMPORTANT : Les test_cases servent de CHECKLIST de gameplay :
- input = "Action ou scénario de jeu"
- expected_output = "Comportement attendu"
- description = "Mécanique de jeu testée"

TYPES DE CHALLENGES PAR DIFFICULTE :
- 1/5 : Mécanique isolée (mouvement joueur, collision basique, score)
- 2/5 : Mini-jeu complet simple (snake, pong, memory, clicker)
- 3/5 : Jeu avec plusieurs mécaniques combinées (platformer basique, tower defense simple, RPG combat)
- 4/5 : Système de jeu avancé (IA ennemie, pathfinding, physique, génération procédurale)
- 5/5 : Jeu complet avec polish (multijoueur local, éditeur de niveaux, shaders, netcode)

ENGINES/FRAMEWORKS POSSIBLES :
- Godot (GDScript ou C#)
- HTML5 Canvas / WebGL
- Pygame
- Love2D (Lua)
- Unity (C#)

CRITERES D'EVALUATION :
- Game feel (réactivité, feedback visuel et sonore)
- Gameplay loop (est-ce fun ?)
- Code propre et extensible
- Performance (60 FPS minimum)""",

        "examples": """EXEMPLES DE BONS CHALLENGES :
- "Space Dodger" (diff 1) : vaisseau qui esquive des astéroïdes avec score et vies
- "Le Donjon Procédural" (diff 3) : générer un donjon aléatoire jouable avec ennemis et trésor
- "L'Arène Multijoueur" (diff 5) : combat local 2 joueurs avec 3 personnages différents""",
    },

    "security": {
        "description": "Challenge de cybersécurité / CTF (vulnérabilités, cryptographie, forensics)",
        "context": """Tu génères des challenges de cybersécurité au format CTF.

IMPORTANT : Le challenge doit toujours avoir un FLAG au format skilluv{...} à trouver.
Les test_cases vérifient si le candidat a trouvé le flag ou les étapes intermédiaires :
- input = "Indice ou fichier fourni"
- expected_output = "Le flag ou la réponse attendue"
- description = "Ce que cette étape valide"

CATEGORIES CTF :
- Cryptographie : chiffrements classiques, RSA, hashing, stéganographie
- Web : injection SQL, XSS, CSRF, authentication bypass, IDOR
- Forensics : analyse de fichiers, récupération de données, analyse réseau (PCAP)
- Reverse engineering : analyse de binaires, désobfuscation, cracking
- Pwn : buffer overflow, format string, exploitation mémoire

TYPES DE CHALLENGES PAR DIFFICULTE :
- 1/5 : Encodage/décodage basique (Base64, ROT13, César)
- 2/5 : Vulnérabilité web simple (injection SQL basique, XSS réfléchi)
- 3/5 : Cryptanalyse ou exploitation web intermédiaire (RSA faible, authentication bypass)
- 4/5 : Reverse engineering, forensics avancé (analyse binaire, PCAP, stéganographie)
- 5/5 : Exploitation mémoire, chaîne de vulnérabilités, cryptographie avancée

REGLES DE SECURITE :
- JAMAIS de vrais exploits utilisables en production
- Le challenge est dans un environnement sandboxé
- Le code malveillant est simulé, pas exécutable
- Enseigner la défense autant que l'attaque""",

        "examples": """EXEMPLES DE BONS CHALLENGES :
- "Le Message Secret" (diff 1) : décoder un message chiffré avec César (flag: skilluv{decoded_message})
- "L'API Vulnérable" (diff 3) : trouver et exploiter une IDOR pour accéder aux données admin
- "Le Binaire Mystérieux" (diff 5) : reverse engineer un binaire obfusqué pour extraire le flag""",
    },
}

# === Guides par ton ===

TONE_GUIDES = {
    "serious": (
        "Ton professionnel et technique. "
        "Le challenge doit ressembler à un vrai problème d'entreprise ou un exercice académique. "
        "Contexte réaliste, énoncé précis, langage formel."
    ),
    "fun": (
        "Ton décontracté et motivant. "
        "Le challenge doit donner envie de coder avec des métaphores créatives et un scénario engageant. "
        "Utilise l'humour léger, des personnages, des situations du quotidien revisitées."
    ),
    "absurd": (
        "Ton absurde et décalé. "
        "Le challenge doit être drôle et surprenant tout en restant techniquement rigoureux. "
        "Scénarios improbables, personnages loufoques, contraintes absurdes mais le code doit être sérieux. "
        "Exemples : 'Un pingouin comptable doit trier ses poissons par fraîcheur', "
        "'Un robot existentialiste qui doit calculer le sens de la vie'."
    ),
}

# === Niveaux de difficulté ===

DIFFICULTY_DESCRIPTIONS = {
    1: "débutant — concepts de base, syntaxe fondamentale, problèmes directs",
    2: "intermédiaire facile — combine 2-3 concepts, logique simple",
    3: "intermédiaire — patterns courants, algorithmes classiques, réflexion requise",
    4: "avancé — optimisation, edge cases nombreux, architecture",
    5: "expert — algorithmes complexes, contraintes strictes, créativité technique",
}


def _effective_difficulty(params: ChallengeParams) -> int:
    """Difficulté effective après application de is_training (baisse d'1 cran).

    On garde `params.difficulty` intact pour le stockage / matching, mais le
    prompt raisonne sur une version potentiellement adoucie.
    """
    if params.is_training and params.difficulty > 1:
        return params.difficulty - 1
    return params.difficulty


def _orientation_hint(params: ChallengeParams, lang_prefix: str) -> str:
    """Ajoute un rappel orientation métier au prompt (skills à privilégier)."""
    orientation = _find_orientation(params.orientation_slug)
    if orientation is None:
        return ""
    label_key = "label_fr" if lang_prefix == "français" else "label_en"
    label = orientation.get(label_key, orientation["slug"])
    critical = orientation.get("critical_skills", [])
    nice = orientation.get("nice_to_have_skills", [])
    lines = [
        f"ORIENTATION MÉTIER CIBLÉE : {label} ({params.orientation_slug})",
        "Le challenge doit préférentiellement mobiliser les skills critiques de "
        f"cette orientation : {', '.join(critical) or '—'}.",
    ]
    if nice:
        lines.append(f"Bonus si le challenge sollicite : {', '.join(nice)}.")
    lines.append(
        "Reste dans le domaine demandé — l'orientation n'est qu'un biais de "
        "contexte, pas un changement de skill_domain."
    )
    return "\n".join(lines)


def _training_hint() -> str:
    return (
        "MODE ENTRAÎNEMENT :\n"
        "- Ajoute plus d'exemples concrets dans description/instructions.\n"
        "- Guide davantage le candidat (indices structurés, pseudocode partiel "
        "accepté dans starter_code).\n"
        "- Les test_cases visibles servent d'exemples pédagogiques : commente-les "
        "richement dans le champ description.\n"
        "- L'objectif est l'apprentissage, pas le filtrage."
    )


def _project_hint(params: ChallengeParams) -> str:
    if not params.project_id:
        return ""
    return (
        f"CONTEXTE PROJET OSS : ce challenge est lié au projet Skilluv "
        f"`{params.project_id}`. Ancre l'énoncé dans un problème réaliste "
        f"qui pourrait émerger de la maintenance ou de l'évolution de ce "
        f"projet. Reste générique dans la solution (le candidat ne doit pas "
        f"connaître le projet précis pour réussir)."
    )


def build_system_prompt(params: ChallengeParams) -> str:
    """Construit le prompt système complet pour la génération de challenges."""
    lang = "français" if params.language == "fr" else "English"
    domain = DOMAIN_CONTEXTS.get(params.skill_domain, DOMAIN_CONTEXTS["code"])
    tone = TONE_GUIDES.get(params.tone, TONE_GUIDES["serious"])
    effective_diff = _effective_difficulty(params)
    difficulty_desc = DIFFICULTY_DESCRIPTIONS.get(effective_diff, "intermédiaire")

    min_visible = 3
    min_hidden = 2 if effective_diff <= 3 else 4

    orientation_block = _orientation_hint(params, lang)
    training_block = _training_hint() if params.is_training else ""
    project_block = _project_hint(params)

    prompt = f"""Tu es le générateur de challenges de Skilluv, une plateforme gamifiée panafricaine où les talents prouvent leurs compétences par la pratique.

REGLES ABSOLUES :
- Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant ou après
- Langue du contenu : {lang}
- Le challenge doit être réalisable dans le temps imparti ({params.duration_minutes} minutes)
- Difficulté {effective_diff}/5 : {difficulty_desc}
- Mode : {params.mode}
- IA autorisée pour le candidat : {"oui" if params.ai_allowed else "non — le challenge doit tester des compétences que l'IA ne peut pas résoudre trivialement"}

DOMAINE : {domain["description"]}

{domain["context"]}

{domain["examples"]}

TON : {tone}

{orientation_block}

{training_block}

{project_block}

{f"Langage de programmation imposé : {params.programming_language}" if params.programming_language else "Le candidat choisit son langage de programmation." if params.skill_domain == "code" else ""}
{f"Tags thématiques à intégrer : {', '.join(params.tags)}" if params.tags else ""}

FORMAT JSON ATTENDU :
{{
  "title": "Titre court et accrocheur (max 60 caractères)",
  "description": "Énoncé complet en markdown. Contexte, problème, exemples concrets.",
  "instructions": "Instructions pas-à-pas détaillées pour réaliser le challenge.",
  "starter_code": "Code de départ fourni au candidat (ou null si aucun)",
  "test_cases": [
    {{
      "input": "entrée du test",
      "expected_output": "sortie attendue exacte",
      "description": "Ce que ce test vérifie",
      "is_hidden": false
    }}
  ],
  "evaluation_criteria": "Critères d'évaluation détaillés et mesurables",
  "tags": ["tag1", "tag2", "tag3"]
}}

EXIGENCES TEST CASES :
- Minimum {min_visible} tests visibles + {min_hidden} tests cachés
- Les tests visibles montrent le fonctionnement attendu
- Les tests cachés couvrent les edge cases, limites et performances
- Chaque test doit être vérifiable de manière déterministe"""

    return prompt


def build_user_prompt(params: ChallengeParams) -> str:
    """Construit le prompt utilisateur."""
    lang = "français" if params.language == "fr" else "English"
    parts = [
        f"Génère un challenge {params.skill_domain}",
        f"de difficulté {params.difficulty}/5",
        f"réalisable en {params.duration_minutes} minutes",
        f"ton {params.tone}",
        f"mode {params.mode}",
        f"en {lang}",
    ]
    if params.programming_language:
        parts.append(f"en {params.programming_language}")
    if params.tags:
        parts.append(f"thèmes: {', '.join(params.tags)}")

    return ", ".join(parts) + "."
