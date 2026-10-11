const urlInput = document.getElementById("url");
const downloadBtn = document.getElementById("download");
const transcribeBtn = document.getElementById("transcribe");
const newJobBtn = document.getElementById("new-job");
const seekStartBtn = document.getElementById("seek-start");
const addSegmentBtn = document.getElementById("add-segment");
const cutPlayheadBtn = document.getElementById("cut-playhead");
const removeSegmentBtn = document.getElementById("remove-segment");
const statusEl = document.getElementById("status");
const preview = document.getElementById("preview");
const player = document.getElementById("player");
const videoTitle = document.getElementById("video-title");
const videoMeta = document.getElementById("video-meta");
const output = document.getElementById("output");
const transcript = document.getElementById("transcript");
const meta = document.getElementById("meta");
const copyBtn = document.getElementById("copy");
const downloadTxtBtn = document.getElementById("download-txt");
const downloadSrtBtn = document.getElementById("download-srt");
const jobListEl = document.getElementById("job-list");
const jobListEmpty = document.getElementById("job-list-empty");
const modelSelect = document.getElementById("model");
const timelineTrack = document.getElementById("timeline-track");
const timelineSegments = document.getElementById("timeline-segments");
const playhead = document.getElementById("playhead");
const labelDuration = document.getElementById("label-duration");
const summaryCount = document.getElementById("summary-count");
const summaryKeep = document.getElementById("summary-keep");

let jobId = null;
let lastSrt = "";
let parts = [];
let duration = 0;
let segments = [{ start: 0, end: 0 }];
let selectedIndex = 0;
let drag = null;

function setStatus(message, kind = "") {
  statusEl.textContent = message;
  statusEl.className = `status${kind ? ` ${kind}` : ""}`;
}

function formatClock(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0;
  const total = Math.floor(seconds);
  const ms = Math.round((seconds - total) * 1000);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const base =
    hours > 0
      ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
      : `${minutes}:${String(secs).padStart(2, "0")}`;
  return ms > 0 ? `${base}.${String(ms).padStart(3, "0")}` : base;
}

function parseClock(value) {
  if (value == null || value === "") return null;
  if (typeof value === "number") return value;
  const text = String(value).trim();
  if (!text) return null;
  if (!text.includes(":")) {
    const n = Number(text);
    return Number.isFinite(n) ? n : null;
  }
  const bits = text.split(":").map(Number);
  if (bits.some((n) => !Number.isFinite(n))) return null;
  if (bits.length === 2) return bits[0] * 60 + bits[1];
  if (bits.length === 3) return bits[0] * 3600 + bits[1] * 60 + bits[2];
  return null;
}

function formatWhen(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function downloadBlob(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function readError(response) {
  const data = await response.json().catch(() => ({}));
  const detail = data.detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
  }
  return detail || `Request failed (${response.status})`;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function pct(seconds) {
  if (!duration) return 0;
  return (seconds / duration) * 100;
}

function timeFromClientX(clientX) {
  const rect = timelineTrack.getBoundingClientRect();
  if (!rect.width || !duration) return 0;
  return clamp((clientX - rect.left) / rect.width, 0, 1) * duration;
}

function sortSegments() {
  const selected = segments[selectedIndex];
  segments.sort((a, b) => a.start - b.start);
  selectedIndex = Math.max(
    0,
    segments.findIndex((seg) => seg === selected)
  );
}

function normalizeSegments() {
  if (!duration) return;
  const minLen = 0.1;
  segments = segments
    .map((seg) => ({
      start: clamp(seg.start, 0, Math.max(0, duration - minLen)),
      end: clamp(seg.end, minLen, duration),
    }))
    .map((seg) =>
      seg.end <= seg.start ? { start: seg.start, end: seg.start + minLen } : seg
    );

  sortSegments();

  for (let i = 1; i < segments.length; i++) {
    if (segments[i].start < segments[i - 1].end) {
      segments[i].start = segments[i - 1].end;
      if (segments[i].end - segments[i].start < minLen) {
        segments[i].end = Math.min(duration, segments[i].start + minLen);
      }
    }
  }

  segments = segments.filter((seg) => seg.end - seg.start >= minLen * 0.99);
  if (!segments.length) segments = [{ start: 0, end: duration }];
  selectedIndex = clamp(selectedIndex, 0, segments.length - 1);
}

function renderTimeline() {
  normalizeSegments();
  timelineSegments.innerHTML = "";
  labelDuration.textContent = formatClock(duration);
  summaryCount.textContent = String(segments.length);
  summaryKeep.textContent = segments
    .map((seg) => `${formatClock(seg.start)}-${formatClock(seg.end)}`)
    .join(" · ");

  segments.forEach((seg, index) => {
    const block = document.createElement("div");
    block.className = `keep-block${index === selectedIndex ? " selected" : ""}`;
    block.style.left = `${pct(seg.start)}%`;
    block.style.width = `${pct(seg.end - seg.start)}%`;
    block.dataset.index = String(index);
    block.title = `${formatClock(seg.start)} - ${formatClock(seg.end)}`;
    block.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      selectedIndex = index;
      renderTimeline();
      beginDrag("move", event, index);
    });

    const startHandle = document.createElement("button");
    startHandle.type = "button";
    startHandle.className = "timeline-handle";
    startHandle.style.left = "0";
    startHandle.setAttribute("aria-label", `Segment ${index + 1} start`);
    startHandle.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      selectedIndex = index;
      beginDrag("start", event, index);
    });

    const endHandle = document.createElement("button");
    endHandle.type = "button";
    endHandle.className = "timeline-handle";
    endHandle.style.left = "100%";
    endHandle.setAttribute("aria-label", `Segment ${index + 1} end`);
    endHandle.addEventListener("pointerdown", (event) => {
      event.stopPropagation();
      selectedIndex = index;
      beginDrag("end", event, index);
    });

    block.append(startHandle, endHandle);
    timelineSegments.appendChild(block);
  });

  if (Number.isFinite(player.currentTime) && duration) {
    playhead.style.left = `${pct(player.currentTime)}%`;
  }
}

function setSegmentsFromJob(data) {
  if (Array.isArray(data.last_segments) && data.last_segments.length) {
    segments = data.last_segments
      .map((seg) => ({
        start: parseClock(seg.start) ?? 0,
        end: parseClock(seg.end) ?? 0,
      }))
      .filter((seg) => seg.end > seg.start);
  } else {
    const start = parseClock(data.last_start) ?? 0;
    const end = parseClock(data.last_end);
    const exStart = parseClock(data.last_exclude_start);
    const exEnd = parseClock(data.last_exclude_end);
    if (end != null && exStart != null && exEnd != null && start < exStart && exEnd < end) {
      segments = [
        { start, end: exStart },
        { start: exEnd, end },
      ];
    } else {
      segments = [{ start, end: end != null ? end : duration || 0 }];
    }
  }
  selectedIndex = 0;
  renderTimeline();
}

function findGap(minLen = 1) {
  const ordered = [...segments].sort((a, b) => a.start - b.start);
  if (!ordered.length) return { start: 0, end: Math.min(duration, minLen) };
  if (ordered[0].start >= minLen) {
    return { start: 0, end: Math.min(ordered[0].start, minLen) };
  }
  for (let i = 0; i < ordered.length - 1; i++) {
    const gap = ordered[i + 1].start - ordered[i].end;
    if (gap >= minLen) {
      return {
        start: ordered[i].end,
        end: ordered[i].end + Math.min(gap, Math.max(minLen, gap * 0.5)),
      };
    }
  }
  const last = ordered[ordered.length - 1];
  if (duration - last.end >= minLen) {
    return {
      start: last.end,
      end: Math.min(duration, last.end + Math.max(minLen, (duration - last.end) * 0.5)),
    };
  }
  return null;
}

function addSegment() {
  const gap = findGap(Math.min(2, Math.max(0.5, duration * 0.08)));
  if (!gap) {
    setStatus("No free space for another keep block. Shrink existing ones first.", "error");
    return;
  }
  segments.push(gap);
  selectedIndex = segments.length - 1;
  renderTimeline();
  setStatus("Added keep block. Drag handles to reshape it.", "ok");
}

function cutAtPlayhead() {
  const t = player.currentTime || 0;
  const gap = 0.35;
  const index = segments.findIndex((seg) => t > seg.start + gap && t < seg.end - gap);
  if (index < 0) {
    setStatus("Move the playhead inside a keep block to cut a gap there.", "error");
    return;
  }
  const seg = segments[index];
  const left = { start: seg.start, end: Math.max(seg.start + 0.1, t - gap / 2) };
  const right = { start: Math.min(seg.end - 0.1, t + gap / 2), end: seg.end };
  if (left.end - left.start < 0.1 || right.end - right.start < 0.1) {
    setStatus("Not enough room to cut here. Widen the block or move playhead.", "error");
    return;
  }
  segments.splice(index, 1, left, right);
  selectedIndex = index + 1;
  renderTimeline();
  setStatus("Cut gap at playhead. Drag the new handles to refine.", "ok");
}

function removeSelectedSegment() {
  if (segments.length <= 1) {
    setStatus("Keep at least one segment.", "error");
    return;
  }
  segments.splice(selectedIndex, 1);
  selectedIndex = clamp(selectedIndex, 0, segments.length - 1);
  renderTimeline();
  setStatus("Removed keep block.", "ok");
}

function beginDrag(kind, event, index) {
  event.preventDefault();
  const seg = segments[index];
  drag = {
    kind,
    index,
    originX: event.clientX,
    originStart: seg.start,
    originEnd: seg.end,
  };
  document.body.style.cursor = kind === "move" ? "grabbing" : "ew-resize";
}

function neighbors(index) {
  const prevEnd = index > 0 ? segments[index - 1].end : 0;
  const nextStart = index < segments.length - 1 ? segments[index + 1].start : duration;
  return { prevEnd, nextStart };
}

function onPointerMove(event) {
  if (!drag || !duration) return;
  const t = timeFromClientX(event.clientX);
  const minLen = 0.1;
  const seg = segments[drag.index];
  const { prevEnd, nextStart } = neighbors(drag.index);

  if (drag.kind === "start") {
    seg.start = clamp(t, prevEnd, seg.end - minLen);
  } else if (drag.kind === "end") {
    seg.end = clamp(t, seg.start + minLen, nextStart);
  } else if (drag.kind === "move") {
    const delta = timeFromClientX(event.clientX) - timeFromClientX(drag.originX);
    // recompute from origin using pixel delta for stability
    const rect = timelineTrack.getBoundingClientRect();
    const deltaSec = ((event.clientX - drag.originX) / rect.width) * duration;
    const len = drag.originEnd - drag.originStart;
    let start = drag.originStart + deltaSec;
    start = clamp(start, prevEnd, nextStart - len);
    seg.start = start;
    seg.end = start + len;
  } else if (drag.kind === "seek") {
    player.currentTime = t;
  }
  renderTimeline();
}

function endDrag() {
  if (!drag) return;
  drag = null;
  document.body.style.cursor = "";
  renderTimeline();
}

function renderLiveTranscript() {
  transcript.value = parts.join(" ").replace(/\s+/g, " ").trim();
  transcript.scrollTop = transcript.scrollHeight;
}

function resetWorkspace({ keepUrl = false } = {}) {
  jobId = null;
  lastSrt = "";
  parts = [];
  duration = 0;
  segments = [{ start: 0, end: 0 }];
  selectedIndex = 0;
  if (!keepUrl) urlInput.value = "";
  modelSelect.value = "base";
  preview.hidden = true;
  output.hidden = true;
  transcript.value = "";
  meta.textContent = "";
  videoTitle.textContent = "Preview";
  videoMeta.textContent = "";
  player.removeAttribute("src");
  player.load();
  highlightActiveJob(null);
  renderTimeline();
}

function highlightActiveJob(id) {
  for (const item of jobListEl.querySelectorAll(".job-item")) {
    item.classList.toggle("active", item.dataset.jobId === id);
  }
}

function applyJob(data) {
  jobId = data.job_id;
  urlInput.value = data.url || "";
  videoTitle.textContent = data.title || "Preview";
  const durLabel =
    data.duration_sec != null ? ` · ${formatClock(Number(data.duration_sec))}` : "";
  videoMeta.textContent = `Drag purple keep blocks. Cut multiple gaps with Add / Cut at playhead${durLabel}`;
  player.src = data.video_url;
  if (data.duration_sec != null) duration = Number(data.duration_sec);
  if (data.last_model) modelSelect.value = data.last_model;
  setSegmentsFromJob(data);

  const text = data.transcript_text || "";
  lastSrt = data.transcript_srt || "";
  if (text) {
    transcript.value = text;
    const lang = data.language ? ` · language: ${data.language}` : "";
    const clip =
      data.clip_duration_sec != null
        ? ` · clip: ${Number(data.clip_duration_sec).toFixed(1)}s`
        : "";
    meta.textContent = `Saved transcript${lang}${clip}`;
    output.hidden = false;
  } else {
    transcript.value = "";
    meta.textContent = "";
    output.hidden = true;
  }

  preview.hidden = false;
  highlightActiveJob(jobId);
}

async function refreshJobs() {
  const response = await fetch("/api/jobs");
  if (!response.ok) throw new Error(await readError(response));
  const jobs = await response.json();

  jobListEl.innerHTML = "";
  jobListEmpty.hidden = jobs.length > 0;

  for (const job of jobs) {
    const li = document.createElement("li");
    li.className = "job-item";
    li.dataset.jobId = job.job_id;
    if (job.job_id === jobId) li.classList.add("active");

    const openBtn = document.createElement("button");
    openBtn.type = "button";
    openBtn.className = "job-item-main";
    openBtn.innerHTML = `
      <span class="job-item-title"></span>
      <span class="job-item-meta"></span>
      ${job.has_transcript ? '<span class="job-item-badge">Has transcript</span>' : ""}
    `;
    openBtn.querySelector(".job-item-title").textContent = job.title || "Untitled video";
    const when = formatWhen(job.updated_at || job.created_at);
    const dur =
      job.duration_sec != null ? formatClock(Number(job.duration_sec)) : "video";
    openBtn.querySelector(".job-item-meta").textContent = [dur, when]
      .filter(Boolean)
      .join(" · ");
    openBtn.addEventListener("click", () => openJob(job.job_id));

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "secondary job-delete";
    delBtn.title = "Delete project";
    delBtn.textContent = "×";
    delBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteJob(job.job_id, job.title);
    });

    li.append(openBtn, delBtn);
    jobListEl.appendChild(li);
  }
}

async function openJob(id) {
  setStatus("Loading project...");
  try {
    const response = await fetch(`/api/jobs/${id}`);
    if (!response.ok) throw new Error(await readError(response));
    applyJob(await response.json());
    setStatus("Project loaded. Adjust keep blocks or re-transcribe.", "ok");
  } catch (err) {
    setStatus(err.message || "Could not open project.", "error");
    await refreshJobs().catch(() => {});
  }
}

async function deleteJob(id, title) {
  const label = title || "this project";
  if (!window.confirm(`Delete ${label}? This removes the downloaded video.`)) {
    return;
  }
  try {
    const response = await fetch(`/api/jobs/${id}`, { method: "DELETE" });
    if (!response.ok) throw new Error(await readError(response));
    if (jobId === id) resetWorkspace();
    await refreshJobs();
    setStatus("Project deleted.", "ok");
  } catch (err) {
    setStatus(err.message || "Delete failed.", "error");
  }
}

async function consumeSse(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      for (const line of chunk.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        onEvent(JSON.parse(payload));
      }
    }
  }
}

timelineTrack.addEventListener("pointerdown", (event) => {
  if (event.target.closest(".keep-block") || event.target.closest(".timeline-handle")) {
    return;
  }
  beginDrag("seek", event, selectedIndex);
  onPointerMove(event);
});
window.addEventListener("pointermove", onPointerMove);
window.addEventListener("pointerup", endDrag);
window.addEventListener("pointercancel", endDrag);

player.addEventListener("timeupdate", () => {
  if (duration) playhead.style.left = `${pct(player.currentTime)}%`;
});

player.addEventListener("loadedmetadata", () => {
  duration = player.duration || duration || 0;
  if (!segments.length || (segments.length === 1 && segments[0].end === 0)) {
    segments = [{ start: 0, end: duration }];
  }
  renderTimeline();
});

addSegmentBtn.addEventListener("click", addSegment);
cutPlayheadBtn.addEventListener("click", cutAtPlayhead);
removeSegmentBtn.addEventListener("click", removeSelectedSegment);

seekStartBtn.addEventListener("click", () => {
  const seg = segments[selectedIndex] || segments[0];
  player.currentTime = seg.start;
  player.play().catch(() => {});
});

newJobBtn.addEventListener("click", () => {
  resetWorkspace();
  setStatus("Ready for a new URL.");
  urlInput.focus();
});

downloadBtn.addEventListener("click", async () => {
  const url = urlInput.value.trim();
  if (!url) {
    setStatus("Paste a YouTube or Facebook URL first.", "error");
    return;
  }

  downloadBtn.disabled = true;
  transcribeBtn.disabled = true;
  preview.hidden = true;
  output.hidden = true;
  player.removeAttribute("src");
  player.load();
  jobId = null;
  setStatus("Downloading video...");

  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    if (!response.ok) throw new Error(await readError(response));

    const data = await response.json();
    applyJob({
      ...data,
      last_segments: [
        {
          start: "0:00",
          end:
            data.duration_sec != null
              ? formatClock(Number(data.duration_sec))
              : "0:00",
        },
      ],
      transcript_text: "",
      transcript_srt: "",
    });
    await refreshJobs();
    setStatus("Downloaded. Drag blocks, or Cut at playhead for multiple gaps.", "ok");
  } catch (err) {
    setStatus(err.message || "Download failed.", "error");
  } finally {
    downloadBtn.disabled = false;
    transcribeBtn.disabled = false;
  }
});

transcribeBtn.addEventListener("click", async () => {
  if (!jobId) {
    setStatus("Download a video first.", "error");
    return;
  }
  normalizeSegments();
  if (!segments.length) {
    setStatus("Add at least one keep block.", "error");
    return;
  }

  downloadBtn.disabled = true;
  transcribeBtn.disabled = true;
  parts = [];
  lastSrt = "";
  transcript.value = "";
  meta.textContent = "";
  output.hidden = false;
  setStatus("Starting...");

  try {
    const response = await fetch("/api/transcribe/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId,
        model: modelSelect.value,
        segments: segments.map((seg) => ({ start: seg.start, end: seg.end })),
      }),
    });
    if (!response.ok) throw new Error(await readError(response));

    let finished = false;
    await consumeSse(response, (event) => {
      if (event.type === "status") {
        setStatus(event.message || event.stage || "Working...");
        return;
      }
      if (event.type === "info") {
        const lang = event.language ? ` · language: ${event.language}` : "";
        meta.textContent = `Live transcript${lang} · clip: ${Number(
          event.duration_sec || 0
        ).toFixed(1)}s`;
        return;
      }
      if (event.type === "segment") {
        if (event.text) parts.push(event.text);
        renderLiveTranscript();
        setStatus(`Transcribing... segment ${event.index}`);
        return;
      }
      if (event.type === "done") {
        finished = true;
        transcript.value = event.text || parts.join(" ");
        lastSrt = event.srt || "";
        const lang = event.language ? ` · language: ${event.language}` : "";
        meta.textContent = `Model: ${event.model} · clip: ${Number(
          event.duration_sec || 0
        ).toFixed(1)}s${lang}`;
        setStatus("Done.", "ok");
        refreshJobs().catch(() => {});
        return;
      }
      if (event.type === "error") {
        throw new Error(event.detail || "Transcription failed.");
      }
    });

    if (!finished) {
      throw new Error("Stream ended before transcription finished.");
    }
  } catch (err) {
    setStatus(err.message || "Transcription failed.", "error");
  } finally {
    downloadBtn.disabled = false;
    transcribeBtn.disabled = false;
  }
});

copyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(transcript.value);
    setStatus("Copied transcript.", "ok");
  } catch {
    setStatus("Could not copy to clipboard.", "error");
  }
});

downloadTxtBtn.addEventListener("click", () => {
  downloadBlob("transcript.txt", transcript.value, "text/plain;charset=utf-8");
});

downloadSrtBtn.addEventListener("click", () => {
  downloadBlob("transcript.srt", lastSrt, "application/x-subrip;charset=utf-8");
});

refreshJobs()
  .then(() => setStatus("Ready."))
  .catch((err) => setStatus(err.message || "Could not load projects.", "error"));
