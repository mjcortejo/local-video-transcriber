import json
import urllib.request
import wave
from pathlib import Path

BASE = "http://127.0.0.1:8000"

# Find an existing job or download one
with urllib.request.urlopen(f"{BASE}/api/jobs") as r:
    jobs = json.loads(r.read().decode())

if jobs:
    job_id = jobs[0]["job_id"]
    print("using existing", job_id, jobs[0]["title"])
else:
    payload = json.dumps({"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"}).encode()
    req = urllib.request.Request(
        f"{BASE}/api/download",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        job_id = json.loads(r.read().decode())["job_id"]
    print("downloaded", job_id)

# Keep 0-12s, exclude middle 4-8s => ~8s audio
payload = json.dumps(
    {
        "job_id": job_id,
        "start": 0,
        "end": 12,
        "exclude_start": 4,
        "exclude_end": 8,
        "model": "tiny",
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
                    if ev["type"] in {"status", "info", "done"}:
                        print(ev["type"], ev.get("message") or ev.get("duration_sec") or "")

assert "done" in events, events
wav = Path("data/jobs") / job_id / "clip.wav"
assert wav.exists(), wav
with wave.open(str(wav), "rb") as wf:
    seconds = wf.getnframes() / float(wf.getframerate())
print("clip_wav_seconds", round(seconds, 2))
assert 6.5 <= seconds <= 9.5, seconds
print("exclude_ok")
