from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import ALLOWED_HOST_FRAGMENTS, ALLOWED_MODELS, DEFAULT_MODEL


def parse_timestamp(value: str | float | int) -> float:
    """Parse HH:MM:SS, MM:SS, or seconds into float seconds."""
    if isinstance(value, (int, float)):
        if value < 0:
            raise ValueError("Timestamp must be non-negative")
        return float(value)

    text = str(value).strip()
    if not text:
        raise ValueError("Timestamp is required")

    if ":" not in text:
        seconds = float(text)
        if seconds < 0:
            raise ValueError("Timestamp must be non-negative")
        return seconds

    parts = text.split(":")
    if len(parts) not in (2, 3):
        raise ValueError("Use HH:MM:SS, MM:SS, or seconds")

    try:
        numbers = [float(p) for p in parts]
    except ValueError as exc:
        raise ValueError("Invalid timestamp format") from exc

    if len(numbers) == 2:
        minutes, seconds = numbers
        total = minutes * 60 + seconds
    else:
        hours, minutes, seconds = numbers
        total = hours * 3600 + minutes * 60 + seconds

    if total < 0:
        raise ValueError("Timestamp must be non-negative")
    return total


def validate_media_url(value: str) -> str:
    url = value.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    lowered = url.lower()
    if not any(fragment in lowered for fragment in ALLOWED_HOST_FRAGMENTS):
        raise ValueError("Only YouTube and Facebook URLs are supported")
    return url


class DownloadRequest(BaseModel):
    url: str = Field(..., min_length=1)

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str) -> str:
        return validate_media_url(value)


class DownloadResponse(BaseModel):
    job_id: str
    title: str | None = None
    duration_sec: float | None = None
    video_url: str
    url: str | None = None


class ClipSegment(BaseModel):
    start: str | float
    end: str | float

    @model_validator(mode="after")
    def validate_bounds(self) -> ClipSegment:
        start_sec = parse_timestamp(self.start)
        end_sec = parse_timestamp(self.end)
        if end_sec <= start_sec:
            raise ValueError("Each segment end must be greater than start")
        object.__setattr__(self, "start_sec", start_sec)
        object.__setattr__(self, "end_sec", end_sec)
        return self

    @property
    def start_seconds(self) -> float:
        return float(getattr(self, "start_sec"))

    @property
    def end_seconds(self) -> float:
        return float(getattr(self, "end_sec"))


class JobSummary(BaseModel):
    job_id: str
    url: str | None = None
    title: str
    duration_sec: float | None = None
    created_at: str
    updated_at: str
    last_start: str | None = None
    last_end: str | None = None
    last_segments: list[dict[str, Any]] | None = None
    last_model: str | None = None
    has_transcript: bool = False
    video_url: str


class JobDetail(JobSummary):
    language: str | None = None
    transcript_text: str = ""
    transcript_srt: str = ""
    clip_duration_sec: float | None = None


class TranscribeRequest(BaseModel):
    job_id: str = Field(..., min_length=1)
    segments: list[ClipSegment] = Field(..., min_length=1)
    model: Literal["tiny", "base", "small", "medium"] = DEFAULT_MODEL  # type: ignore[assignment]

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if value not in ALLOWED_MODELS:
            raise ValueError(f"Model must be one of: {', '.join(ALLOWED_MODELS)}")
        return value

    @model_validator(mode="after")
    def validate_segments(self) -> TranscribeRequest:
        parsed = sorted(
            [(seg.start_seconds, seg.end_seconds) for seg in self.segments],
            key=lambda item: item[0],
        )
        for index in range(1, len(parsed)):
            prev_end = parsed[index - 1][1]
            cur_start = parsed[index][0]
            if cur_start < prev_end:
                raise ValueError("Keep segments must not overlap")
        object.__setattr__(self, "keep_segments", parsed)
        return self

    @property
    def keep_ranges(self) -> list[tuple[float, float]]:
        return list(getattr(self, "keep_segments"))


class TranscribeResponse(BaseModel):
    text: str
    srt: str
    language: str | None = None
    duration_sec: float
    model: str
