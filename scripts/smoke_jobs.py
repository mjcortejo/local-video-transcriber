import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/api/jobs") as r:
    jobs = json.loads(r.read().decode())
print("existing", len(jobs), [j["title"] for j in jobs[:3]])

payload = json.dumps({"url": "https://www.youtube.com/watch?v=jNQXAC9IVRw"}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/download",
    data=payload,
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=180) as r:
    downloaded = json.loads(r.read().decode())
print("downloaded", downloaded["job_id"], downloaded["title"])

with urllib.request.urlopen("http://127.0.0.1:8000/api/jobs") as r:
    jobs = json.loads(r.read().decode())
assert any(j["job_id"] == downloaded["job_id"] for j in jobs)

with urllib.request.urlopen(
    f"http://127.0.0.1:8000/api/jobs/{downloaded['job_id']}"
) as r:
    detail = json.loads(r.read().decode())
print("detail title", detail["title"], "url", detail.get("url"))
assert detail["video_url"]
print("ok")
