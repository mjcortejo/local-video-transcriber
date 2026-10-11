# Local Video Transcriber

Local web app that downloads a YouTube or Facebook video, trims it with ffmpeg, and transcribes the clip with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/download.html) installed and available on your `PATH`
- Enough disk/RAM for the Whisper model you choose (`tiny` / `base` / `small` / `medium`)

## Setup

```powershell
cd E:\Whisper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

### One-command (Windows + psmux)

```powershell
.\run.ps1
```

Or double-click / run `run.cmd`.

This will:
1. Install [psmux](https://github.com/psmux/psmux) via `winget` if needed (`winget install psmux`)
2. Create/update the Python venv and dependencies
3. Start a psmux session named `whisper` with:
   - **top pane**: FastAPI/uvicorn (backend + web UI)
   - **bottom pane**: health check, opens the browser, status tips
4. Attach you to that session

Useful psmux controls:
- Switch panes: `Ctrl+b` then arrow keys
- Detach (leave running): `Ctrl+b` then `d`
- Reattach later: `psmux attach -t whisper`
- Stop everything: `psmux kill-session -t whisper`

### Manual

```powershell
uvicorn app.main:app --reload --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Usage

1. Paste a YouTube or Facebook video URL and click **Download**
2. Drag Twitch-style purple **keep blocks** on the timeline
3. Cut multiple gaps with **Cut at playhead** or **Add keep block** (only purple ranges are transcribed)
4. Pick a Whisper model size (default `base`) and click **Transcribe clip**
5. Watch the transcript stream live as Whisper emits segments, then copy or download `.txt` / `.srt`
6. Reopen any project later from the **Projects** sidebar

## Notes

- Projects persist under `data/jobs/<job_id>/` (`meta.json`, source video, optional transcript).
- GPU is used automatically when CUDA **and** the matching cuBLAS runtime are available; otherwise the app falls back to CPU (`int8`).
- Some Facebook (and occasionally YouTube) videos require login cookies. If download fails with an auth/age-gate error, export cookies for yt-dlp and we can add cookie support later.
- Environment overrides:
  - `WHISPER_MODEL` — default model size
  - `DATA_DIR` — where job files are stored
