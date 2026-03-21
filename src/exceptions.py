class SkilluvAIError(Exception):
    """Classe de base pour toutes les exceptions skilluv-ai."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(SkilluvAIError):
    """Payload invalide reçu via gRPC ou Redis Queue."""


class ExternalServiceError(SkilluvAIError):
    """Erreur lors d'un appel à un service externe (Claude API)."""


class ProcessingError(SkilluvAIError):
    """Erreur lors du traitement d'un job (ffmpeg, tree-sitter, embeddings)."""


class StorageError(SkilluvAIError):
    """Erreur lors d'une opération MinIO (upload/download)."""
