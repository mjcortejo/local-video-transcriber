from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import JOBS_DIR
from app.pipeline import PipelineError, cleanup_job_dir, find_source, get_job_dir

META_NAME = "meta.json"
TRANSCRIPT_TXT = "transcript.txt"
TRANSCRIPT_SRT = "transcript.srt"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def meta_path(job_dir: Path) -> Path:
    return job_dir / META_NAME


def read_meta(job_dir: Path) -> dict[str, Any] | None:
    path = meta_path(job_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_meta(job_dir: Path, data: dict[str, Any]) -> dict[str, Any]:
    payload = {**data, "updated_at": _now_iso()}
    meta_path(job_dir).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


def update_meta(job_dir: Path, **fields: Any) -> dict[str, Any]:
    current = read_meta(job_dir) or {
        "job_id": job_dir.name,
        "created_at": _now_iso(),
    }
    current.update(fields)
    return write_meta(job_dir, current)


def save_transcript(job_dir: Path, text: str, srt: str) -> None:
    (job_dir / TRANSCRIPT_TXT).write_text(text or "", encoding="utf-8")
    (job_dir / TRANSCRIPT_SRT).write_text(srt or "", encoding="utf-8")


def load_transcript(job_dir: Path) -> tuple[str, str]:
    txt_path = job_dir / TRANSCRIPT_TXT
    srt_path = job_dir / TRANSCRIPT_SRT
    text = txt_path.read_text(encoding="utf-8") if txt_path.exists() else ""
    srt = srt_path.read_text(encoding="utf-8") if srt_path.exists() else ""
    return text, srt


def _has_source(job_dir: Path) -> bool:
    try:
        find_source(job_dir)
        return True
    except PipelineError:
        return False


def _job_summary(job_dir: Path) -> dict[str, Any] | None:
    if not job_dir.is_dir() or not _has_source(job_dir):
        return None

    meta = read_meta(job_dir) or {}
    created = meta.get("created_at")
    if not created:
        created = datetime.fromtimestamp(
            job_dir.stat().st_mtime, tz=timezone.utc
        ).isoformat()

    text, _srt = load_transcript(job_dir)
    has_transcript = bool(text.strip()) or bool(meta.get("has_transcript"))

    return {
        "job_id": job_dir.name,
        "url": meta.get("url"),
        "title": meta.get("title") or "Untitled video",
        "duration_sec": meta.get("duration_sec"),
        "created_at": created,
        "updated_at": meta.get("updated_at") or created,
        "last_start": meta.get("last_start"),
        "last_end": meta.get("last_end"),
        "last_segments": meta.get("last_segments"),
        "last_model": meta.get("last_model"),
        "has_transcript": has_transcript,
        "video_url": f"/api/jobs/{job_dir.name}/video",
    }


def list_jobs() -> list[dict[str, Any]]:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs: list[dict[str, Any]] = []
    for path in JOBS_DIR.iterdir():
        if not path.is_dir():
            continue
        summary = _job_summary(path)
        if summary:
            jobs.append(summary)
    jobs.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return jobs


def get_job(job_id: str) -> dict[str, Any]:
    job_dir = get_job_dir(job_id)
    summary = _job_summary(job_dir)
    if summary is None:
        raise PipelineError("Job not found or video missing")

    text, srt = load_transcript(job_dir)
    meta = read_meta(job_dir) or {}
    return {
        **summary,
        "language": meta.get("language"),
        "transcript_text": text,
        "transcript_srt": srt,
        "clip_duration_sec": meta.get("clip_duration_sec"),
    }


def delete_job(job_id: str) -> None:
    job_dir = get_job_dir(job_id)
    cleanup_job_dir(job_dir)
