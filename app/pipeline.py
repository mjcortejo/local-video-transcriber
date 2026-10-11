from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from faster_whisper import WhisperModel

from app.config import JOBS_DIR

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Raised when a pipeline stage fails."""


@dataclass
class DownloadResult:
    job_id: str
    job_dir: Path
    source_path: Path
    title: str | None
    duration_sec: float | None


@dataclass
class TranscriptResult:
    text: str
    srt: str
    language: str | None
    duration_sec: float


def create_job_dir() -> Path:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    job_dir = JOBS_DIR / str(uuid.uuid4())
    job_dir.mkdir(parents=True, exist_ok=False)
    return job_dir


def cleanup_job_dir(job_dir: Path) -> None:
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)


def get_job_dir(job_id: str) -> Path:
    if "/" in job_id or "\\" in job_id or ".." in job_id:
        raise PipelineError("Invalid job id")
    job_dir = JOBS_DIR / job_id
    if not job_dir.is_dir():
        raise PipelineError("Job not found")
    return job_dir


def find_source(job_dir: Path) -> Path:
    preferred = job_dir / "source.mp4"
    if preferred.exists():
        return preferred
    candidates = sorted(job_dir.glob("source.*"))
    if not candidates:
        raise PipelineError("Downloaded video missing for this job")
    return candidates[0]


def download(url: str, job_dir: Path | None = None) -> DownloadResult:
    """Download a single video into a job dir and return metadata."""
    if job_dir is None:
        job_dir = create_job_dir()
    job_id = job_dir.name

    outtmpl = str(job_dir / "source.%(ext)s")
    opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }

    title: str | None = None
    duration_sec: float | None = None

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise PipelineError("Download failed: no media info returned")
            title = info.get("title")
            duration = info.get("duration")
            if duration is not None:
                duration_sec = float(duration)
            path = Path(ydl.prepare_filename(info))
            if path.suffix != ".mp4":
                merged = job_dir / "source.mp4"
                if merged.exists():
                    path = merged
    except yt_dlp.utils.DownloadError as exc:
        cleanup_job_dir(job_dir)
        raise PipelineError(f"Download failed: {exc}") from exc
    except Exception as exc:
        cleanup_job_dir(job_dir)
        raise PipelineError(f"Download failed: {exc}") from exc

    if not path.exists():
        try:
            path = find_source(job_dir)
        except PipelineError:
            cleanup_job_dir(job_dir)
            raise PipelineError("Download failed: output file missing") from None

    from app.jobs import update_meta

    update_meta(
        job_dir,
        job_id=job_id,
        url=url,
        title=title,
        duration_sec=duration_sec,
        has_transcript=False,
    )

    return DownloadResult(
        job_id=job_id,
        job_dir=job_dir,
        source_path=path,
        title=title,
        duration_sec=duration_sec,
    )


def _run_ffmpeg(args: list[str]) -> None:
    cmd = ["ffmpeg", "-y", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PipelineError(
            "ffmpeg not found. Install ffmpeg and ensure it is on your PATH."
        ) from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown ffmpeg error").strip()
        raise PipelineError(f"ffmpeg failed: {detail[-2000:]}")


def format_ts(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    millis = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _extract_wav(
    input_path: Path,
    output_path: Path,
    start_sec: float,
    end_sec: float,
) -> None:
    if end_sec <= start_sec:
        raise PipelineError("Each clip segment must have end > start")
    _run_ffmpeg(
        [
            "-ss",
            format_ts(start_sec),
            "-to",
            format_ts(end_sec),
            "-i",
            str(input_path),
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_path),
        ]
    )


def build_clip_audio(
    input_path: Path,
    job_dir: Path,
    keep_segments: list[tuple[float, float]],
) -> Path:
    """Build 16 kHz mono WAV for Whisper from one or more keep segments."""
    if not keep_segments:
        raise PipelineError("At least one keep segment is required")

    ordered = sorted(keep_segments, key=lambda item: item[0])
    for start_sec, end_sec in ordered:
        if end_sec <= start_sec:
            raise PipelineError("Each keep segment must have end > start")
    for index in range(1, len(ordered)):
        if ordered[index][0] < ordered[index - 1][1]:
            raise PipelineError("Keep segments must not overlap")

    clip_wav = job_dir / "clip.wav"
    if len(ordered) == 1:
        start_sec, end_sec = ordered[0]
        _extract_wav(input_path, clip_wav, start_sec, end_sec)
        return clip_wav

    part_paths: list[Path] = []
    for index, (start_sec, end_sec) in enumerate(ordered, start=1):
        part = job_dir / f"part{index}.wav"
        _extract_wav(input_path, part, start_sec, end_sec)
        part_paths.append(part)

    logger.info("Concatenating %d keep segments", len(part_paths))
    args: list[str] = []
    for path in part_paths:
        args.extend(["-i", str(path)])
    labels = "".join(f"[{i}:a]" for i in range(len(part_paths)))
    args.extend(
        [
            "-filter_complex",
            f"{labels}concat=n={len(part_paths)}:v=0:a=1[a]",
            "-map",
            "[a]",
            str(clip_wav),
        ]
    )
    _run_ffmpeg(args)
    return clip_wav


def trim(input_path: Path, job_dir: Path, start_sec: float, end_sec: float) -> Path:
    """Backward-compatible wrapper: trim [start, end] to WAV."""
    return build_clip_audio(input_path, job_dir, [(start_sec, end_sec)])


def _format_srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    millis = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def segments_to_srt(segments: list) -> str:
    lines: list[str] = []
    for index, segment in enumerate(segments, start=1):
        start = _format_srt_timestamp(segment.start)
        end = _format_srt_timestamp(segment.end)
        text = segment.text.strip()
        lines.append(str(index))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + ("\n" if segments else "")


def load_wav_f32(audio_path: Path):
    """Load 16-bit mono WAV as float32 PCM for faster-whisper.

    Passing a numpy array avoids PyAV decode paths that break on newer `av`
    builds (common on Python 3.14 wheels).
    """
    import wave

    import numpy as np

    with wave.open(str(audio_path), "rb") as wf:
        if wf.getnchannels() != 1:
            raise PipelineError("Expected mono WAV for transcription")
        if wf.getsampwidth() != 2:
            raise PipelineError("Expected 16-bit WAV for transcription")
        frames = wf.readframes(wf.getnframes())

    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(audio_path: Path, model: WhisperModel) -> TranscriptResult:
    audio = load_wav_f32(audio_path)
    segments_iter, info = model.transcribe(audio, beam_size=5)
    segments = list(segments_iter)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    srt = segments_to_srt(segments)
    return TranscriptResult(
        text=text,
        srt=srt,
        language=getattr(info, "language", None),
        duration_sec=float(getattr(info, "duration", 0.0) or 0.0),
    )


def iter_trim_and_transcribe(
    job_id: str,
    keep_segments: list[tuple[float, float]],
    model: WhisperModel,
    *,
    model_name: str | None = None,
):
    """Yield status/info/segment/done events while trimming and transcribing."""
    from app.jobs import save_transcript, update_meta

    job_dir = get_job_dir(job_id)
    source = find_source(job_dir)
    ordered = sorted(keep_segments, key=lambda item: item[0])

    if len(ordered) == 1:
        yield {"type": "status", "stage": "trimming", "message": "Trimming clip..."}
    else:
        yield {
            "type": "status",
            "stage": "trimming",
            "message": f"Building clip from {len(ordered)} keep segments...",
        }

    logger.info("Building clip job %s segments=%s", job_id, ordered)
    audio_path = build_clip_audio(source, job_dir, ordered)

    yield {
        "type": "status",
        "stage": "transcribing",
        "message": "Transcribing... segments will appear live.",
    }
    logger.info("Transcribing %s", audio_path)
    audio = load_wav_f32(audio_path)
    segments_iter, info = model.transcribe(audio, beam_size=5)

    language = getattr(info, "language", None)
    duration_sec = float(getattr(info, "duration", 0.0) or 0.0)
    yield {
        "type": "info",
        "language": language,
        "duration_sec": duration_sec,
    }

    asr_segments = []
    for index, segment in enumerate(segments_iter, start=1):
        text = segment.text.strip()
        asr_segments.append(segment)
        yield {
            "type": "segment",
            "index": index,
            "start": float(segment.start),
            "end": float(segment.end),
            "text": text,
        }

    full_text = " ".join(seg.text.strip() for seg in asr_segments).strip()
    srt = segments_to_srt(asr_segments)
    save_transcript(job_dir, full_text, srt)
    serialized = [
        {"start": format_ts(start), "end": format_ts(end)} for start, end in ordered
    ]
    update_meta(
        job_dir,
        has_transcript=bool(full_text),
        language=language,
        clip_duration_sec=duration_sec,
        last_segments=serialized,
        last_start=serialized[0]["start"],
        last_end=serialized[-1]["end"],
        last_model=model_name,
    )
    yield {
        "type": "done",
        "text": full_text,
        "srt": srt,
        "language": language,
        "duration_sec": duration_sec,
    }


def trim_and_transcribe(
    job_id: str,
    keep_segments: list[tuple[float, float]],
    model: WhisperModel,
    *,
    model_name: str | None = None,
) -> TranscriptResult:
    final: TranscriptResult | None = None
    for event in iter_trim_and_transcribe(
        job_id,
        keep_segments,
        model,
        model_name=model_name,
    ):
        if event["type"] == "done":
            final = TranscriptResult(
                text=event["text"],
                srt=event["srt"],
                language=event.get("language"),
                duration_sec=float(event.get("duration_sec") or 0.0),
            )
    if final is None:
        raise PipelineError("Transcription produced no result")
    return final
