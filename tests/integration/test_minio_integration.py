"""Tests d'intégration MinIO — upload, download, bucket."""

from io import BytesIO

import pytest


TEST_BUCKET = "skilluv-test"


@pytest.fixture(autouse=True)
def setup_test_bucket(minio_client):
    """Crée un bucket de test et le nettoie après."""
    if not minio_client.bucket_exists(TEST_BUCKET):
        minio_client.make_bucket(TEST_BUCKET)
    yield
    # Nettoyer
    objects = minio_client.list_objects(TEST_BUCKET, recursive=True)
    for obj in objects:
        minio_client.remove_object(TEST_BUCKET, obj.object_name)


def test_upload_and_download(minio_client) -> None:
    """Upload un fichier et le relire."""
    key = "test/hello.txt"
    content = b"Hello Skilluv!"

    minio_client.put_object(
        TEST_BUCKET,
        key,
        BytesIO(content),
        length=len(content),
        content_type="text/plain",
    )

    response = minio_client.get_object(TEST_BUCKET, key)
    data = response.read()
    response.close()
    response.release_conn()

    assert data == content


def test_upload_video_file(minio_client) -> None:
    """Simule l'upload d'un fichier vidéo."""
    key = "replays/sub-001.mp4"
    # Fake MP4 header
    content = b"\x00\x00\x00\x1c\x66\x74\x79\x70" + b"\x00" * 100

    minio_client.put_object(
        TEST_BUCKET,
        key,
        BytesIO(content),
        length=len(content),
        content_type="video/mp4",
    )

    stat = minio_client.stat_object(TEST_BUCKET, key)
    assert stat.size == len(content)
    assert stat.content_type == "video/mp4"


def test_list_objects(minio_client) -> None:
    """Lister les objets dans un préfixe."""
    for i in range(3):
        key = f"clips/clip_{i}.mp4"
        content = f"clip_{i}".encode()
        minio_client.put_object(
            TEST_BUCKET,
            key,
            BytesIO(content),
            length=len(content),
        )

    objects = list(minio_client.list_objects(TEST_BUCKET, prefix="clips/"))
    assert len(objects) == 3


def test_object_not_found(minio_client) -> None:
    """Télécharger un objet inexistant lève une erreur."""
    from minio.error import S3Error

    with pytest.raises(S3Error):
        minio_client.get_object(TEST_BUCKET, "nonexistent/file.txt")
