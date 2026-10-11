from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT_DIR / "data"))
JOBS_DIR = DATA_DIR / "jobs"

DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "base")
ALLOWED_MODELS = ("tiny", "base", "small", "medium")

ALLOWED_HOST_FRAGMENTS = (
    "youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "facebook.com",
    "fb.watch",
    "fb.com",
    "m.facebook.com",
)


def _pick_compute_type(device: str) -> str:
    """Pick the best supported compute type for the device."""
    import ctranslate2

    supported = set(ctranslate2.get_supported_compute_types(device))
    for candidate in ("float16", "int8_float16", "int8", "int8_float32", "float32"):
        if candidate in supported:
            return candidate
    return "default"


def _cuda_libs_available() -> bool:
    """Best-effort check that CUDA runtime libs are loadable on this machine."""
    import sys

    if sys.platform != "win32":
        return True
    try:
        import ctypes

        for name in ("cublas64_12.dll", "cublas64_11.dll", "cublas64_10.dll"):
            try:
                ctypes.WinDLL(name)
                return True
            except OSError:
                continue
    except Exception:
        return False
    return False


def detect_device() -> tuple[str, str]:
    """Return (device, compute_type) for faster-whisper."""
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0 and _cuda_libs_available():
            return "cuda", _pick_compute_type("cuda")
    except Exception:
        pass

    try:
        return "cpu", _pick_compute_type("cpu")
    except Exception:
        return "cpu", "int8"
