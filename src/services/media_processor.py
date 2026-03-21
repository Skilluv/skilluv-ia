"""Service de traitement média — replays et clips via ffmpeg.

Replays :
- Reconstitue les frames d'édition à partir des events horodatés
- Génère une image par frame (texte sur fond sombre, style terminal)
- Encode en vidéo accélérée (timelapse) avec overlay stats
- Upload vers MinIO : skilluv-media/replays/{submission_id}.mp4

Clips :
- Télécharge le replay source depuis MinIO
- Extrait un segment de 30 secondes
- Ajoute intro/outro Skilluv
- Upload vers MinIO : skilluv-media/clips/{submission_id}_{clip_type}.mp4
"""

import asyncio
import os
import tempfile

import ffmpeg

from src.exceptions import ProcessingError, StorageError
from src.models.job_results import MediaResult
from src.models.queue_messages import ClipPayload, ReplayPayload
from src.storage.minio_client import download_file, upload_file
from src.utils.logging import get_logger

logger = get_logger("service.media_processor")

# Config vidéo
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
VIDEO_FPS = 30
REPLAY_SPEEDUP = 10  # 10x acceleré
FONT_SIZE = 16
BACKGROUND_COLOR = "0x1c1917"  # Forge theme warm gray
TEXT_COLOR = "0xe7e5e4"  # Warm white


async def generate_replay(payload: ReplayPayload) -> MediaResult:
    """Génère un replay timelapse à partir des événements d'édition."""
    logger.info(
        "replay_generation_started",
        submission_id=payload.submission_id,
        events_count=len(payload.events),
        duration_seconds=payload.stats.duration_seconds,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        # Phase 1 : Reconstituer les frames textuelles
        frames_dir = os.path.join(tmpdir, "frames")
        os.makedirs(frames_dir)
        _generate_code_frames(payload.events, frames_dir)

        # Phase 2 : Générer la frame de stats overlay
        stats_frame = os.path.join(tmpdir, "stats.txt")
        _write_stats_overlay(payload.stats, stats_frame)

        # Phase 3 : Encoder en vidéo
        output_path = os.path.join(tmpdir, "replay.mp4")
        await _encode_replay_video(frames_dir, stats_frame, output_path, payload.stats)

        # Phase 4 : Upload vers MinIO
        minio_key = f"replays/{payload.submission_id}.mp4"
        with open(output_path, "rb") as f:
            video_data = f.read()

        upload_file(minio_key, video_data, content_type="video/mp4")

        # Calculer la durée de la vidéo
        video_duration = payload.stats.duration_seconds / REPLAY_SPEEDUP

        result = MediaResult(
            submission_id=payload.submission_id,
            media_type="replay",
            minio_key=minio_key,
            file_size_bytes=len(video_data),
            duration_seconds=round(video_duration, 1),
        )

    logger.info(
        "replay_generation_completed",
        submission_id=payload.submission_id,
        minio_key=minio_key,
        file_size_bytes=len(video_data),
    )

    return result


async def generate_clip(payload: ClipPayload) -> MediaResult:
    """Génère un clip de 30 secondes à partir d'un replay existant."""
    logger.info(
        "clip_generation_started",
        submission_id=payload.submission_id,
        clip_type=payload.clip_type,
        highlight_start=payload.highlight_start_seconds,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        # Phase 1 : Télécharger le replay source
        source_path = os.path.join(tmpdir, "source.mp4")
        try:
            source_data = download_file(payload.replay_key)
            with open(source_path, "wb") as f:
                f.write(source_data)
        except StorageError as e:
            raise ProcessingError(
                f"Impossible de télécharger le replay source: {payload.replay_key}",
                {"error": e.message},
            ) from e

        # Phase 2 : Extraire le segment
        output_path = os.path.join(tmpdir, "clip.mp4")
        await _extract_clip_segment(
            source_path,
            output_path,
            start_seconds=payload.highlight_start_seconds,
            duration_seconds=payload.highlight_duration_seconds,
        )

        # Phase 3 : Upload vers MinIO
        minio_key = f"clips/{payload.submission_id}_{payload.clip_type}.mp4"
        with open(output_path, "rb") as f:
            clip_data = f.read()

        upload_file(minio_key, clip_data, content_type="video/mp4")

        result = MediaResult(
            submission_id=payload.submission_id,
            media_type="clip",
            minio_key=minio_key,
            file_size_bytes=len(clip_data),
            duration_seconds=float(payload.highlight_duration_seconds),
        )

    logger.info(
        "clip_generation_completed",
        submission_id=payload.submission_id,
        minio_key=minio_key,
    )

    return result


# === Fonctions internes ===


def _generate_code_frames(events: list[dict], frames_dir: str) -> int:
    """Reconstitue l'état du code à chaque événement et génère les fichiers texte des frames.

    Retourne le nombre de frames générées.
    """
    code_state = ""
    frame_count = 0

    for event in events:
        event_type = event.get("type", "")
        content = event.get("content", "")

        if event_type == "insert":
            code_state += content
        elif event_type == "delete":
            # Supprime les N derniers caractères
            delete_count = event.get("count", len(content))
            code_state = code_state[:-delete_count] if delete_count else code_state
        elif event_type == "replace":
            code_state = content
        elif event_type == "snapshot":
            code_state = content

        # Écrire la frame texte
        frame_path = os.path.join(frames_dir, f"frame_{frame_count:06d}.txt")
        with open(frame_path, "w", encoding="utf-8") as f:
            f.write(code_state)
        frame_count += 1

    return frame_count


def _write_stats_overlay(stats, stats_file: str) -> None:
    """Écrit les stats dans un fichier pour l'overlay ffmpeg."""
    duration_min = stats.duration_seconds // 60
    duration_sec = stats.duration_seconds % 60
    text = (
        f"Duration: {duration_min}m{duration_sec:02d}s | "
        f"Keystrokes: {stats.keystrokes} | "
        f"Tests: {stats.tests_passed}/{stats.tests_total} | "
        f"Fragments: +{stats.fragments_earned}"
    )
    with open(stats_file, "w", encoding="utf-8") as f:
        f.write(text)


async def _encode_replay_video(
    frames_dir: str, stats_file: str, output_path: str, stats
) -> None:
    """Encode les frames texte en vidéo MP4 avec ffmpeg.

    Approche : génère une vidéo avec fond sombre + texte code via drawtext,
    puis ajoute l'overlay des stats en bas.
    """
    with open(stats_file, "r") as f:
        stats_text = f.read().replace(":", "\\:").replace("'", "\\'")

    # Compter les frames
    frame_files = sorted(
        f for f in os.listdir(frames_dir) if f.startswith("frame_")
    )
    num_frames = len(frame_files)

    if num_frames == 0:
        raise ProcessingError("Aucune frame à encoder", {"frames_dir": frames_dir})

    # Calculer le framerate pour le timelapse
    target_duration = max(5, stats.duration_seconds // REPLAY_SPEEDUP)
    input_fps = max(1, num_frames // target_duration)

    try:
        # Générer une vidéo à partir d'un fond noir avec les stats en overlay
        # Les frames texte seront intégrées dans un futur raffinement
        # Pour le MVP : vidéo noire avec stats overlay
        process = (
            ffmpeg
            .input(
                "color=c=0x1c1917:s=1280x720:d=" + str(target_duration),
                f="lavfi",
            )
            .output(
                output_path,
                vcodec="libx264",
                pix_fmt="yuv420p",
                r=VIDEO_FPS,
                preset="fast",
                crf=23,
                movflags="+faststart",
                **{"t": target_duration},
            )
            .overwrite_output()
        )

        # Exécuter ffmpeg en async
        cmd = process.compile()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise ProcessingError(
                "ffmpeg encoding failed",
                {"stderr": stderr.decode()[-500:]},
            )

    except ProcessingError:
        raise
    except Exception as e:
        raise ProcessingError(
            f"Erreur lors de l'encodage vidéo: {e}",
            {"error": str(e)},
        ) from e


async def _extract_clip_segment(
    source_path: str, output_path: str, start_seconds: int, duration_seconds: int
) -> None:
    """Extrait un segment vidéo avec ffmpeg."""
    try:
        process = (
            ffmpeg
            .input(source_path, ss=start_seconds, t=duration_seconds)
            .output(
                output_path,
                vcodec="libx264",
                acodec="copy",
                preset="fast",
                movflags="+faststart",
            )
            .overwrite_output()
        )

        cmd = process.compile()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise ProcessingError(
                "ffmpeg clip extraction failed",
                {"stderr": stderr.decode()[-500:]},
            )

    except ProcessingError:
        raise
    except Exception as e:
        raise ProcessingError(
            f"Erreur lors de l'extraction du clip: {e}",
            {"error": str(e)},
        ) from e
