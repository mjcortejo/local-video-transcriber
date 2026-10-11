import json
import urllib.request
import wave
from pathlib import Path

BASE = "http://127.0.0.1:8000"

payload = json.dumps({"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"}).encode()
req = urllib.request.Request(
    f"{BASE}/api/download",
    data=payload,
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=180) as r:
    job = json.loads(r.read().decode())
job_id = job["job_id"]
print("job", job_id)

# Keep 0-3, 6-9, 12-15 => ~9 seconds
payload = json.dumps(
    {
        "job_id": job_id,
        "model": "tiny",
        "segments": [
            {"start": 0, "end": 3},
            {"start": 6, "end": 9},
            {"start": 12, "end": 15},
        ],
    }
).encode()
req = urllib.request.Request(
    f"{BASE}/api/transcribe/stream",
    data=payload,
    headers={"Content-Type": "application/json"},
)

events = []
with urllib.request.urlopen(req, timeout=180) as resp:
    buf = b""
    while True:
        chunk = resp.read(128)
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            part, buf = buf.split(b"\n\n", 1)
            for line in part.split(b"\n"):
                if line.startswith(b"data:"):
                    ev = json.loads(line[5:].decode().strip())
                    events.append(ev["type"])
                    if ev["type"] in {"status", "info", "done", "error"}:
                        print(ev["type"], ev.get("message") or ev.get("detail") or ev.get("duration_sec"))

assert "done" in events, events
wav = Path("data/jobs") / job_id / "clip.wav"
with wave.open(str(wav), "rb") as wf:
    seconds = wf.getnframes() / float(wf.getframerate())
print("clip_wav_seconds", round(seconds, 2))
assert 8.0 <= seconds <= 10.0, seconds
print("multi_ok")
