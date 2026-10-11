from __future__ import annotations

import json
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from faster_whisper import WhisperModel

from app.config import DEFAULT_MODEL, ROOT_DIR, detect_device
from app.jobs import delete_job, get_job, list_jobs
from app.pipeline import (
    PipelineError,
    download,
    find_source,
    get_job_dir,
    iter_trim_and_transcribe,
    trim_and_transcribe,
)
from app.schemas import (
    DownloadRequest,
    DownloadResponse,
    JobDetail,
    JobSummary,
    TranscribeRequest,
    TranscribeResponse,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = ROOT_DIR / "static"

# model_size -> WhisperModel
_model_cache: dict[str, WhisperModel] = {}
_device: str = "cpu"
_compute_type: str = "int8"


def _probe_model(model: WhisperModel) -> None:
    """Ensure the model can actually run inference (catches missing CUDA libs)."""
    import numpy as np

    audio = np.zeros(16000, dtype=np.float32)
    segments, _info = model.transcribe(audio, beam_size=1)
    for _ in segments:
        break


def get_model(model_size: str) -> WhisperModel:
    global _device, _compute_type

    if model_size in _model_cache:
        return _model_cache[model_size]

    attempts: list[tuple[str, str]] = [(_device, _compute_type)]
    if _device == "cuda":
        for compute in ("int8", "int8_float32", "float32"):
            if (_device, compute) not in attempts:
                attempts.append((_device, compute))
        attempts.append(("cpu", "int8"))
    elif (_device, _compute_type) != ("cpu", "int8"):
        attempts.append(("cpu", "int8"))

    last_error: Exception | None = None
    for device, compute_type in attempts:
        try:
            logger.info(
                "Loading Whisper model=%s device=%s compute_type=%s",
                model_size,
                device,
                compute_type,
            )
            model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
            )
            _probe_model(model)
            _model_cache[model_size] = model
            _device, _compute_type = device, compute_type
            return model
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Failed loading model=%s on %s/%s: %s",
                model_size,
                device,
                compute_type,
                exc,
            )

    raise RuntimeError(f"Unable to load Whisper model '{model_size}'") from last_error


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _device, _compute_type
    _device, _compute_type = detect_device()
    logger.info("Device=%s compute_type=%s", _device, _compute_type)
    try:
        get_model(DEFAULT_MODEL)
    except Exception:
        logger.exception("Failed to preload default model %s", DEFAULT_MODEL)
    yield
    _model_cache.clear()


app = FastAPI(title="Local Whisper Clip Transcriber", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "device": _device, "compute_type": _compute_type}


@app.post("/api/download", response_model=DownloadResponse)
def download_video(req: DownloadRequest) -> DownloadResponse:
    try:
        result = download(req.url)
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Download failed")
        raise HTTPException(status_code=500, detail=f"Download failed: {exc}") from exc

    return DownloadResponse(
        job_id=result.job_id,
        title=result.title,
        duration_sec=result.duration_sec,
        video_url=f"/api/jobs/{result.job_id}/video",
        url=req.url,
    )


@app.get("/api/jobs", response_model=list[JobSummary])
def jobs_list() -> list[JobSummary]:
    return [JobSummary(**item) for item in list_jobs()]


@app.get("/api/jobs/{job_id}", response_model=JobDetail)
def jobs_get(job_id: str) -> JobDetail:
    try:
        return JobDetail(**get_job(job_id))
    except PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/jobs/{job_id}")
def jobs_delete(job_id: str) -> dict[str, str]:
    try:
        delete_job(job_id)
    except PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted", "job_id": job_id}


@app.get("/api/jobs/{job_id}/video")
def job_video(job_id: str) -> FileResponse:
    try:
        job_dir = get_job_dir(job_id)
        path = find_source(job_dir)
    except PipelineError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    media_type = mimetypes.guess_type(path.name)[0] or "video/mp4"
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="inline",
    )


@app.post("/api/transcribe", response_model=TranscribeResponse)
def transcribe(req: TranscribeRequest) -> TranscribeResponse:
    try:
        model = get_model(req.model)
        result = trim_and_transcribe(
            job_id=req.job_id,
            keep_segments=req.keep_ranges,
            model=model,
            model_name=req.model,
        )
    except PipelineError as exc:
        status = 404 if "not found" in str(exc).lower() or "missing" in str(exc).lower() else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {exc}") from exc

    return TranscribeResponse(
        text=result.text,
        srt=result.srt,
        language=result.language,
        duration_sec=result.duration_sec,
        model=req.model,
    )


@app.post("/api/transcribe/stream")
def transcribe_stream(req: TranscribeRequest) -> StreamingResponse:
    """Stream transcription progress and segments as Server-Sent Events."""

    def event_stream():
        try:
            model = get_model(req.model)
            for event in iter_trim_and_transcribe(
                job_id=req.job_id,
                keep_segments=req.keep_ranges,
                model=model,
                model_name=req.model,
            ):
                if event["type"] == "done":
                    event = {**event, "model": req.model}
                yield f"data: {json.dumps(event)}\n\n"
        except PipelineError as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
        except Exception as exc:
            logger.exception("Streaming transcription failed")
            yield f"data: {json.dumps({'type': 'error', 'detail': f'Transcription failed: {exc}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/")
def index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="UI not found")
    return FileResponse(index_path)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
