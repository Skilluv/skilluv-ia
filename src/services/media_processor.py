"""Service de traitement média — replays et clips via ffmpeg.

Replays :
- Reconstitue les frames d'édition à partir des events horodatés
- Rend chaque frame en image PNG (code coloré sur fond sombre, style terminal)
- Encode en vidéo accélérée (timelapse) avec barre de stats et progression
- Upload vers MinIO : skilluv-media/replays/{submission_id}.mp4

Clips :
- Télécharge le replay source depuis MinIO
- Extrait un segment de 30 secondes
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
REPLAY_SPEEDUP = 10  # 10x accéléré


async def generate_replay(payload: ReplayPayload) -> MediaResult:
    """Génère un replay timelapse à partir des événements d'édition."""
    logger.info(
        "replay_generation_started",
        submission_id=payload.submission_id,
        events_count=len(payload.events),
        duration_seconds=payload.stats.duration_seconds,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        # Phase 1 : Rendre les frames en images PNG
        frames_dir = os.path.join(tmpdir, "frames")
        os.makedirs(frames_dir)

        stats_text = _format_stats_text(payload.stats)
        num_frames = _render_visual_frames(payload.events, frames_dir, stats_text)

        if num_frames == 0:
            raise ProcessingError(
                "Aucun événement à rendre",
                {"submission_id": payload.submission_id},
            )

        # Phase 2 : Encoder les images PNG en vidéo MP4
        output_path = os.path.join(tmpdir, "replay.mp4")
        target_duration = max(5, payload.stats.duration_seconds // REPLAY_SPEEDUP)
        input_fps = max(1, num_frames // target_duration)

        await _encode_png_sequence(frames_dir, output_path, input_fps)

        # Phase 3 : Upload vers MinIO
        minio_key = f"replays/{payload.submission_id}.mp4"
        with open(output_path, "rb") as f:
            video_data = f.read()

        upload_file(minio_key, video_data, content_type="video/mp4")

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
        num_frames=num_frames,
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


def _render_visual_frames(
    events: list[dict], frames_dir: str, stats_text: str
) -> int:
    """Rend les événements d'édition en images PNG via le frame renderer.

    Fallback sur les frames texte si Pillow n'est pas disponible.
    """
    try:
        from src.services._frame_renderer import render_frames_to_dir

        return render_frames_to_dir(events, frames_dir, stats_text=stats_text)
    except ImportError:
        logger.warning("pillow_not_available_using_text_frames")
        return _generate_text_frames(events, frames_dir)


def _generate_text_frames(events: list[dict], frames_dir: str) -> int:
    """Fallback : génère des fichiers texte quand Pillow n'est pas disponible."""
    code_state = ""
    frame_count = 0

    for event in events:
        event_type = event.get("type", "")
        content = event.get("content", "")

        if event_type == "insert":
            code_state += content
        elif event_type == "delete":
            delete_count = event.get("count", len(content))
            code_state = code_state[:-delete_count] if delete_count else code_state
        elif event_type == "replace":
            code_state = content
        elif event_type == "snapshot":
            code_state = content

        frame_path = os.path.join(frames_dir, f"frame_{frame_count:06d}.txt")
        with open(frame_path, "w", encoding="utf-8") as f:
            f.write(code_state)
        frame_count += 1

    return frame_count


def _format_stats_text(stats) -> str:
    """Formate les statistiques de soumission pour l'overlay."""
    duration_min = stats.duration_seconds // 60
    duration_sec = stats.duration_seconds % 60
    return (
        f"Duration: {duration_min}m{duration_sec:02d}s  |  "
        f"Keystrokes: {stats.keystrokes}  |  "
        f"Tests: {stats.tests_passed}/{stats.tests_total}  |  "
        f"Fragments: +{stats.fragments_earned}"
    )


async def _encode_png_sequence(
    frames_dir: str, output_path: str, input_fps: int
) -> None:
    """Encode une séquence d'images PNG en vidéo MP4 via ffmpeg."""
    # Déterminer le pattern des frames
    frame_files = sorted(f for f in os.listdir(frames_dir) if f.startswith("frame_"))
    if not frame_files:
        raise ProcessingError("Aucune frame à encoder", {"frames_dir": frames_dir})

    # Déterminer l'extension (.png ou .txt)
    ext = os.path.splitext(frame_files[0])[1]

    if ext == ".png":
        # Encoder la séquence PNG directement
        input_pattern = os.path.join(frames_dir, "frame_%06d.png")
        try:
            process = (
                ffmpeg
                .input(input_pattern, framerate=input_fps)
                .output(
                    output_path,
                    vcodec="libx264",
                    pix_fmt="yuv420p",
                    r=VIDEO_FPS,
                    preset="fast",
                    crf=23,
                    movflags="+faststart",
                )
                .overwrite_output()
            )
            await _run_ffmpeg(process)
        except ProcessingError:
            raise
    else:
        # Fallback : frames texte, générer une vidéo avec fond coloré
        num_frames = len(frame_files)
        target_duration = max(5, num_frames // max(input_fps, 1))

        process = (
            ffmpeg
            .input(
                f"color=c=0x1c1917:s={VIDEO_WIDTH}x{VIDEO_HEIGHT}:d={target_duration}",
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
                t=target_duration,
            )
            .overwrite_output()
        )
        await _run_ffmpeg(process)


async def _extract_clip_segment(
    source_path: str, output_path: str, start_seconds: int, duration_seconds: int
) -> None:
    """Extrait un segment vidéo avec ffmpeg."""
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
    await _run_ffmpeg(process)


async def _run_ffmpeg(process) -> None:
    """Exécute un pipeline ffmpeg en async."""
    try:
        cmd = process.compile()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise ProcessingError(
                "ffmpeg process failed",
                {"stderr": stderr.decode()[-500:], "return_code": proc.returncode},
            )
    except ProcessingError:
        raise
    except Exception as e:
        raise ProcessingError(f"ffmpeg execution error: {e}", {"error": str(e)}) from e
