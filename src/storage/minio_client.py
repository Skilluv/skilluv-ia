from io import BytesIO

from minio import Minio

from src.config import settings
from src.exceptions import StorageError
from src.utils.logging import get_logger

logger = get_logger("minio_client")

_client: Minio | None = None


def get_minio() -> Minio:
    """Retourne le client MinIO (singleton)."""
    global _client
    if _client is None:
        _client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    return _client


def ensure_bucket() -> None:
    """Crée le bucket s'il n'existe pas."""
    client = get_minio()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
        logger.info("bucket_created", bucket=settings.minio_bucket)


def upload_file(key: str, data: bytes, content_type: str = "video/mp4") -> str:
    """Upload un fichier dans MinIO. Retourne la clé."""
    client = get_minio()
    try:
        client.put_object(
            bucket_name=settings.minio_bucket,
            object_name=key,
            data=BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        logger.info("file_uploaded", key=key, size_bytes=len(data))
        return key
    except Exception as e:
        raise StorageError(f"Échec upload MinIO: {key}", {"error": str(e)}) from e


def download_file(key: str) -> bytes:
    """Télécharge un fichier depuis MinIO."""
    client = get_minio()
    try:
        response = client.get_object(settings.minio_bucket, key)
        data = response.read()
        response.close()
        response.release_conn()
        return data
    except Exception as e:
        raise StorageError(f"Échec download MinIO: {key}", {"error": str(e)}) from e
