from pydantic import BaseModel, Field


class ChallengeParams(BaseModel):
    """Paramètres de génération d'un challenge reçus via gRPC."""

    skill_domain: str = Field(description="code | design | game | security")
    difficulty: int = Field(ge=1, le=5, description="Niveau de difficulté 1-5")
    duration_minutes: int = Field(ge=5, le=180, description="Durée estimée en minutes")
    mode: str = Field(default="solo", description="solo | team")
    tone: str = Field(default="serious", description="serious | fun | absurd")
    ai_allowed: bool = Field(default=False, description="Usage IA autorisé dans le challenge")
    language: str = Field(default="fr", description="Langue du challenge: fr | en")
    tags: list[str] = Field(default_factory=list, description="Tags thématiques optionnels")
    programming_language: str | None = Field(
        default=None,
        description="Langage de programmation cible (code domain)",
    )


class TestCase(BaseModel):
    """Cas de test pour la vérification automatique."""

    # Empêche pytest de tenter de collecter ce BaseModel comme test class
    # à cause du préfixe "Test" (convention pytest).
    __test__ = False

    input: str
    expected_output: str
    description: str
    is_hidden: bool = Field(default=False, description="Test caché, pas visible par l'utilisateur")


class GeneratedChallenge(BaseModel):
    """Challenge complet généré par l'IA."""

    title: str
    description: str = Field(description="Énoncé complet du challenge en markdown")
    instructions: str = Field(description="Instructions détaillées")
    difficulty: int
    duration_minutes: int
    skill_domain: str
    tone: str
    tags: list[str]
    starter_code: str | None = Field(default=None, description="Code de départ fourni")
    test_cases: list[TestCase]
    evaluation_criteria: str = Field(description="Critères d'évaluation en texte libre")
    fragment_reward: int = Field(description="Fragments attribués = difficulté × durée × complexité")
    ai_allowed: bool
    language: str
