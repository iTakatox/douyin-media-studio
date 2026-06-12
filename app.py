import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request
import yaml


APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
INSTALL_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else APP_DIR
WORKSPACE = INSTALL_DIR.parent
DOWNLOADER_DIR = Path(os.environ.get("DOUYIN_DOWNLOADER_DIR", WORKSPACE / "douyin-downloader"))
APP_DATA_DIR = Path(
    os.environ.get(
        "DOUYIN_APP_DATA_DIR",
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DouyinMediaStudio",
    )
)
BASE_CONFIG = DOWNLOADER_DIR / "config.yml"
PYTHON_EXE = DOWNLOADER_DIR / ".venv" / "Scripts" / "python.exe"
DEFAULT_OUTPUT = Path.home() / "Downloads" / "抖音作品"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

app = Flask(__name__, template_folder=str(APP_DIR / "templates"), static_folder=str(APP_DIR / "static"))
jobs = {}
jobs_lock = threading.Lock()
desktop_api = None


def extract_first_url(text):
    match = re.search(r"https?://[^\s\"'<>，。；、）)】]+", text or "")
    return match.group(0).rstrip(".,;:!?，。；：！？") if match else ""


def safe_name(value, fallback="未命名"):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "")).strip(" .")
    return (value[:90] or fallback).strip()


def safe_job(job_id):
    with jobs_lock:
        return dict(jobs.get(job_id, {}))


def update_job(job_id, **updates):
    with jobs_lock:
        jobs.setdefault(job_id, {}).update(updates)


def append_log(job_id, line):
    text = str(line).strip()
    if not text:
        return
    with jobs_lock:
        job = jobs.setdefault(job_id, {})
        job.setdefault("logs", []).append(text)
        job["logs"] = job["logs"][-400:]


def build_config_text(link, raw_dir, options):
    if not BASE_CONFIG.exists():
        raise FileNotFoundError("下载组件未安装完整，请重新安装最新版。")

    config_text = BASE_CONFIG.read_text(encoding="utf-8", errors="replace")
    try:
        source = yaml.safe_load(config_text) or {}
    except yaml.YAMLError:
        source = {"cookies": extract_cookies_from_broken_yaml(config_text)}
    raw_dir.mkdir(parents=True, exist_ok=True)
    source.update(
        {
            "link": [link],
            "path": str(raw_dir) + os.sep,
            "music": False,
            "cover": False,
            "avatar": False,
            "json": False,
            "folderstyle": True,
            "author_dir": "nickname",
            "download_pinned": bool(options.get("include_pinned")),
            "database": True,
            "database_path": str(raw_dir / "dy_downloader.db"),
            "start_time": options.get("start_date", ""),
            "end_time": options.get("end_date", ""),
            "filename_template": "{author}-{title}-{id}",
            "folder_template": "{date}_{id}",
            "mode": ["post"],
        }
    )
    limit = max(0, int(options.get("limit") or 0))
    number = source.get("number") if isinstance(source.get("number"), dict) else {}
    number["post"] = limit
    source["number"] = number

    media_types = []
    if options.get("download_videos", True):
        media_types.append("video")
    if options.get("download_images", True):
        media_types.append("gallery")
    source["media_types"] = media_types
    return yaml.safe_dump(source, allow_unicode=True, sort_keys=False)


def extract_cookies_from_broken_yaml(text):
    cookies = {}
    in_cookies = False
    for line in (text or "").splitlines():
        if line.strip() == "cookies:":
            in_cookies = True
            continue
        if not in_cookies:
            continue
        if line and not line[0].isspace():
            break
        match = re.match(r"^\s{2,}([A-Za-z0-9_-]+):\s*(.*?)\s*$", line)
        if not match:
            continue
        key, raw_value = match.groups()
        try:
            value = yaml.safe_load(raw_value)
        except yaml.YAMLError:
            value = raw_value.strip("\"'")
        if value not in (None, ""):
            cookies[key] = str(value)
    return cookies


def load_database_records(db_path):
    if not db_path.exists():
        return []
    connection = sqlite3.connect(str(db_path))
    try:
        rows = connection.execute(
            """
            SELECT aweme_id, aweme_type, title, author_name, create_time, file_path, metadata
            FROM aweme ORDER BY create_time DESC
            """
        ).fetchall()
    finally:
        connection.close()

    records = []
    for aweme_id, media_type, title, author, create_time, file_path, metadata_text in rows:
        try:
            metadata = json.loads(metadata_text or "{}")
        except json.JSONDecodeError:
            metadata = {}
        stats = metadata.get("statistics") or {}
        records.append(
            {
                "aweme_id": str(aweme_id),
                "media_type": media_type,
                "title": title or "无标题",
                "author": author or "未知博主",
                "create_time": create_time,
                "source_dir": file_path,
                "digg_count": stats.get("digg_count"),
                "comment_count": stats.get("comment_count"),
                "collect_count": stats.get("collect_count"),
                "share_count": stats.get("share_count"),
            }
        )
    return records


def load_manifest_records(raw_dir):
    manifest_path = raw_dir / "download_manifest.jsonl"
    if not manifest_path.exists():
        return []
    records = []
    for line in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        file_paths = item.get("file_paths") or []
        source_dir = ""
        if file_paths:
            source_dir = str((raw_dir / file_paths[0]).resolve().parent)
        records.append(
            {
                "aweme_id": str(item.get("aweme_id") or ""),
                "media_type": item.get("media_type") or "video",
                "title": item.get("desc") or "Untitled",
                "author": item.get("author_name") or "Unknown author",
                "create_time": item.get("publish_timestamp"),
                "source_dir": source_dir,
                "digg_count": None,
                "comment_count": None,
                "collect_count": None,
                "share_count": None,
            }
        )
    return records


def unique_destination(path):
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成唯一文件名：{path.name}")


def find_record_files(raw_dir, record):
    source_dir = Path(record.get("source_dir") or "")
    if source_dir.exists():
        return [path for path in source_dir.iterdir() if path.is_file()]
    aweme_id = record["aweme_id"]
    return [path for path in raw_dir.rglob(f"*{aweme_id}*") if path.is_file()]


def organize_outputs(raw_dir, selected_dir, options):
    records = load_database_records(raw_dir / "dy_downloader.db")
    if not records:
        records = load_manifest_records(raw_dir)
    if not records:
        return {"author": "", "video_count": 0, "image_count": 0, "works": [], "output_dir": ""}

    author = safe_name(records[0]["author"], "未知博主")
    author_dir = selected_dir / author
    video_dir = author_dir / f"{author}-视频"
    image_dir = author_dir / f"{author}-图文"
    author_dir.mkdir(parents=True, exist_ok=True)
    if options.get("download_videos", True):
        video_dir.mkdir(exist_ok=True)
    if options.get("download_images", True):
        image_dir.mkdir(exist_ok=True)

    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    works = []
    video_count = 0
    image_count = 0

    for record in records:
        copied = []
        title = safe_name(record["title"], "无标题")
        base_name = safe_name(f"{author}-{title}-{record['aweme_id']}")
        files = find_record_files(raw_dir, record)
        if record["media_type"] == "video" and options.get("download_videos", True):
            videos = [path for path in files if path.suffix.lower() == ".mp4" and "_live_" not in path.stem]
            for index, source in enumerate(videos, start=1):
                suffix = "" if len(videos) == 1 else f"-{index}"
                destination = unique_destination(video_dir / f"{base_name}{suffix}.mp4")
                shutil.move(str(source), str(destination))
                copied.append(str(destination))
                video_count += 1
        elif record["media_type"] == "gallery" and options.get("download_images", True):
            images = [path for path in files if path.suffix.lower() in image_exts]
            for index, source in enumerate(images, start=1):
                destination = unique_destination(image_dir / f"{base_name}-{index}{source.suffix.lower()}")
                shutil.move(str(source), str(destination))
                copied.append(str(destination))
                image_count += 1
            live_videos = [path for path in files if path.suffix.lower() == ".mp4"]
            for index, source in enumerate(live_videos, start=1):
                destination = unique_destination(image_dir / f"{base_name}-实况-{index}.mp4")
                shutil.move(str(source), str(destination))
                copied.append(str(destination))

        publish_date = ""
        if record.get("create_time"):
            publish_date = datetime.fromtimestamp(record["create_time"]).strftime("%Y-%m-%d %H:%M")
        works.append(
            {
                "date": publish_date,
                "title": record["title"],
                "type": "视频" if record["media_type"] == "video" else "图文",
                "digg": record.get("digg_count"),
                "comments": record.get("comment_count"),
                "collects": record.get("collect_count"),
                "shares": record.get("share_count"),
                "aweme_id": record["aweme_id"],
                "files": copied,
                "status": "已下载" if copied else "已跳过",
            }
        )

    csv_path = author_dir / "作品清单.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["发布日期", "标题", "类型", "点赞", "评论", "收藏", "分享", "作品ID", "本地文件"])
        for item in works:
            writer.writerow(
                [
                    item["date"],
                    item["title"],
                    item["type"],
                    item["digg"],
                    item["comments"],
                    item["collects"],
                    item["shares"],
                    item["aweme_id"],
                    " | ".join(item["files"]),
                ]
            )

    return {
        "author": author,
        "video_count": video_count,
        "image_count": image_count,
        "work_count": len(works),
        "works": works,
        "output_dir": str(author_dir),
        "csv_path": str(csv_path),
    }


def run_download(job_id, link, output_dir_text, options):
    run_dir = APP_DATA_DIR / "runs" / job_id
    raw_dir = run_dir / "download"
    try:
        selected_dir = Path(output_dir_text).expanduser().resolve()
        selected_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        config_path = run_dir / "config.yml"
        config_path.write_text(build_config_text(link, raw_dir, options), encoding="utf-8")

        update_job(job_id, status="running", progress=8, output_dir=str(selected_dir))
        append_log(job_id, "正在读取博主主页和作品列表...")
        if not PYTHON_EXE.exists():
            raise FileNotFoundError("下载组件未安装完整，请重新安装最新版。")

        env = os.environ.copy()
        env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        process = subprocess.Popen(
            [str(PYTHON_EXE), "run.py", "-c", str(config_path)],
            cwd=str(DOWNLOADER_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
        update_job(job_id, pid=process.pid, progress=16)
        assert process.stdout is not None
        for line in process.stdout:
            append_log(job_id, line)
            job = safe_job(job_id)
            update_job(job_id, progress=min(86, int(job.get("progress", 16)) + 1))

        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"下载组件返回错误代码 {return_code}，请查看运行日志。")

        update_job(job_id, progress=90)
        append_log(job_id, "下载完成，正在整理视频、图文和作品表格...")
        manifest = organize_outputs(raw_dir, selected_dir, options)
        if not manifest["works"]:
            recent_logs = safe_job(job_id).get("logs", [])[-6:]
            detail = " | ".join(line for line in recent_logs if line)
            raise RuntimeError(
                "没有读取到作品。请重新登录后确认主页在登录窗口中可正常打开。"
                + (f" 最近日志：{detail}" if detail else "")
            )

        update_job(job_id, status="done", progress=100, manifest=manifest, works=manifest["works"])
        append_log(job_id, f"整理完成：{manifest['video_count']} 个视频，{manifest['image_count']} 张图文图片。")
        append_log(job_id, f"保存位置：{manifest['output_dir']}")
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc))
        append_log(job_id, f"失败：{exc}")
    finally:
        if raw_dir.exists() and safe_job(job_id).get("status") == "done":
            shutil.rmtree(raw_dir, ignore_errors=True)


@app.route("/")
def index():
    return render_template("index.html", default_output=str(DEFAULT_OUTPUT))


@app.route("/api/start", methods=["POST"])
def start():
    data = request.get_json(force=True)
    link = extract_first_url(data.get("link") or "")
    output_dir = (data.get("output_dir") or str(DEFAULT_OUTPUT)).strip()
    options = data.get("options") or {}
    if not link:
        return jsonify({"error": "没有找到有效的抖音链接。"}), 400
    if not output_dir:
        return jsonify({"error": "请选择保存位置。"}), 400
    if not options.get("download_videos", True) and not options.get("download_images", True):
        return jsonify({"error": "至少选择“视频”或“图文”中的一项。"}), 400

    job_id = uuid.uuid4().hex[:12]
    update_job(job_id, status="queued", progress=2, logs=[], output_dir=output_dir, works=[])
    threading.Thread(
        target=run_download,
        args=(job_id, link, output_dir, options),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id, "link": link})


@app.route("/api/status/<job_id>")
def status(job_id):
    job = safe_job(job_id)
    return jsonify(job) if job else (jsonify({"error": "任务不存在。"}), 404)


@app.route("/api/select-folder", methods=["POST"])
def select_folder():
    current = (request.get_json(silent=True) or {}).get("current") or str(DEFAULT_OUTPUT)
    if desktop_api:
        selected = desktop_api.choose_folder(current)
        return jsonify({"path": selected or current})
    return jsonify({"path": current})


@app.route("/api/open-folder", methods=["POST"])
def open_folder():
    path = (request.get_json(force=True).get("path") or "").strip()
    if not path:
        return jsonify({"error": "目录为空。"}), 400
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    os.startfile(str(target))
    return jsonify({"ok": True})


@app.route("/api/login", methods=["POST"])
def login():
    if not desktop_api:
        return jsonify({"error": "登录功能仅在桌面程序中可用。"}), 400
    threading.Thread(target=desktop_api.open_login, daemon=True).start()
    return jsonify({"ok": True, "message": "登录窗口已在应用内打开。登录完成后点击“我已登录”。"})


@app.route("/api/login/complete", methods=["POST"])
def login_complete():
    if not desktop_api:
        return jsonify({"error": "登录功能仅在桌面程序中可用。"}), 400
    count = desktop_api.save_login_cookies()
    return jsonify({"ok": True, "message": f"登录信息已保存（{count} 项 Cookie）。"})


def register_desktop_api(api):
    global desktop_api
    desktop_api = api


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=False)
