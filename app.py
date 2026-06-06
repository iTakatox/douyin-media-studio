import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, render_template, request


APP_DIR = Path(__file__).resolve().parent
WORKSPACE = APP_DIR.parent
DOWNLOADER_DIR = WORKSPACE / "douyin-downloader"
BASE_CONFIG = DOWNLOADER_DIR / "config.yml"
PYTHON_EXE = DOWNLOADER_DIR / ".venv" / "Scripts" / "python.exe"
DEFAULT_OUTPUT = WORKSPACE / "downloads"

app = Flask(__name__)
jobs = {}
jobs_lock = threading.Lock()


def extract_first_url(text):
    match = re.search(r"https?://[^\s\"'<>，。；、）)】]+", text or "")
    if not match:
        return ""
    return match.group(0).rstrip(".,;:!?")


def safe_job(job_id):
    with jobs_lock:
        return dict(jobs.get(job_id, {}))


def update_job(job_id, **updates):
    with jobs_lock:
        jobs.setdefault(job_id, {}).update(updates)


def append_log(job_id, line):
    with jobs_lock:
        job = jobs.setdefault(job_id, {})
        job.setdefault("logs", []).append(str(line).rstrip())
        job["logs"] = job["logs"][-500:]


def build_config_text(link, raw_output_dir, include_images):
    if not BASE_CONFIG.exists():
        raise FileNotFoundError(
            "douyin-downloader/config.yml was not found. Run setup.ps1 first."
        )
    raw_output_dir.mkdir(parents=True, exist_ok=True)
    source_lines = BASE_CONFIG.read_text(encoding="utf-8").splitlines()
    lines = []
    i = 0
    while i < len(source_lines):
        line = source_lines[i]
        if line.strip() == "link:":
            lines.append("link:")
            lines.append(f"  - {link}")
            i += 1
            while i < len(source_lines) and source_lines[i].lstrip().startswith("- "):
                i += 1
            continue
        lines.append(line)
        i += 1

    text = "\n".join(lines) + "\n"
    output = str(raw_output_dir) + os.sep
    db_path = str(raw_output_dir / "dy_downloader.db")
    image_value = "true" if include_images else "false"

    replacements = [
        (r"(?m)^path:\s*.*$", f"path: {output}"),
        (r"(?m)^music:\s*.*$", "music: false"),
        (r"(?m)^cover:\s*.*$", f"cover: {image_value}"),
        (r"(?m)^avatar:\s*.*$", f"avatar: {image_value}"),
        (r"(?m)^json:\s*.*$", "json: false"),
        (r"(?m)^download_pinned:\s*.*$", "download_pinned: false"),
        (r"(?m)^database:\s*.*$", "database: true"),
        (r"(?m)^database_path:\s*.*$", f"database_path: {db_path}"),
        (r"(?m)^  post:\s*\d+$", "  post: 0"),
        (r"(?m)^  like:\s*\d+$", "  like: 0"),
        (r"(?m)^  allmix:\s*\d+$", "  allmix: 0"),
        (r"(?m)^  mix:\s*\d+$", "  mix: 0"),
        (r"(?m)^  collect:\s*\d+$", "  collect: 0"),
        (r"(?m)^  collectmix:\s*\d+$", "  collectmix: 0"),
    ]
    for pattern, value in replacements:
        text = re.sub(pattern, lambda _match, replacement=value: replacement, text)
    return text


def unique_destination(path):
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 2
    while True:
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def collect_outputs(raw_output_dir, output_dir):
    mp4_dir = output_dir / "mp4"
    images_dir = output_dir / "images"
    mp4_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    image_exts = {".jpg", ".jpeg", ".png", ".webp"}
    mp4_count = 0
    image_count = 0
    mp4_bytes = 0
    image_bytes = 0

    for file in raw_output_dir.rglob("*"):
        if not file.is_file():
            continue
        if file.suffix.lower() == ".mp4":
            dest = unique_destination(mp4_dir / file.name)
            shutil.copy2(file, dest)
            mp4_count += 1
            mp4_bytes += dest.stat().st_size
        elif file.suffix.lower() in image_exts:
            dest = unique_destination(images_dir / file.name)
            shutil.copy2(file, dest)
            image_count += 1
            image_bytes += dest.stat().st_size

    manifest = {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_raw_dir": str(raw_output_dir),
        "mp4_count": mp4_count,
        "image_count": image_count,
        "mp4_bytes": mp4_bytes,
        "image_bytes": image_bytes,
    }
    with (output_dir / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


def run_download(job_id, link, output_dir_text, include_images):
    try:
        output_dir = Path(output_dir_text).expanduser()
        if not output_dir.is_absolute():
            output_dir = WORKSPACE / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        raw_output_dir = output_dir / "_raw"
        run_dir = APP_DIR / "runs" / job_id
        run_dir.mkdir(parents=True, exist_ok=True)
        config_path = run_dir / "config.yml"
        config_path.write_text(
            build_config_text(link, raw_output_dir, include_images),
            encoding="utf-8",
        )

        update_job(job_id, status="running", output_dir=str(output_dir))
        append_log(job_id, f"Output directory: {output_dir}")
        append_log(job_id, "Download started. Complete browser login/verification if prompted.")

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        if not PYTHON_EXE.exists():
            raise FileNotFoundError(
                "douyin-downloader virtual environment was not found. Run setup.ps1 first."
            )
        process = subprocess.Popen(
            [str(PYTHON_EXE), "run.py", "-c", str(config_path)],
            cwd=str(DOWNLOADER_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        update_job(job_id, pid=process.pid)

        assert process.stdout is not None
        for line in process.stdout:
            append_log(job_id, line)

        return_code = process.wait()
        append_log(job_id, f"Download process exited with code: {return_code}")

        manifest = collect_outputs(raw_output_dir, output_dir)
        status = "done" if return_code == 0 and manifest["mp4_count"] > 0 else "failed"
        update_job(job_id, status=status, manifest=manifest)
        append_log(job_id, f"Collected: {manifest['mp4_count']} mp4, {manifest['image_count']} images.")
        if manifest["mp4_count"] == 0:
            append_log(job_id, "No mp4 files were collected. Check Douyin login cookies or link visibility.")
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc))
        append_log(job_id, f"Error: {exc}")


@app.route("/")
def index():
    return render_template("index.html", default_output=str(DEFAULT_OUTPUT))


@app.route("/api/start", methods=["POST"])
def start():
    data = request.get_json(force=True)
    raw_link = (data.get("link") or "").strip()
    link = extract_first_url(raw_link)
    output_dir = (data.get("output_dir") or str(DEFAULT_OUTPUT)).strip()
    include_images = bool(data.get("include_images", True))

    if not link.startswith(("http://", "https://")):
        return jsonify({"error": "No valid URL was found in the pasted text."}), 400
    if not output_dir:
        return jsonify({"error": "Please enter an output directory."}), 400

    job_id = uuid.uuid4().hex[:12]
    update_job(job_id, status="queued", logs=[], output_dir=output_dir)
    thread = threading.Thread(
        target=run_download,
        args=(job_id, link, output_dir, include_images),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id})


@app.route("/api/extract-link", methods=["POST"])
def extract_link():
    data = request.get_json(force=True)
    link = extract_first_url(data.get("text") or "")
    if not link:
        return jsonify({"error": "No valid URL found."}), 400
    return jsonify({"link": link})


@app.route("/api/login-cookies", methods=["POST"])
def login_cookies():
    if not PYTHON_EXE.exists():
        return jsonify({"error": "Downloader environment not found. Run setup.ps1 first."}), 500
    command = (
        "$env:PYTHONIOENCODING='utf-8'; "
        "$env:PYTHONUTF8='1'; "
        ".\\.venv\\Scripts\\python.exe -m tools.cookie_fetcher --config config.yml"
    )
    subprocess.Popen(
        [
            "powershell",
            "-NoExit",
            "-Command",
            command,
        ],
        cwd=str(DOWNLOADER_DIR),
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
    )
    return jsonify({"ok": True, "message": "Douyin login window opened."})


@app.route("/api/status/<job_id>")
def status(job_id):
    job = safe_job(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:5055")).start()
    app.run(host="127.0.0.1", port=5055, debug=False)
