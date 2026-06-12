import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

import yaml
from flask import Flask, jsonify, render_template, request


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
SCAN_WORKER = APP_DIR / "scan_worker.py"
DEFAULT_OUTPUT = Path.home() / "Downloads" / "抖音作品"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

app = Flask(__name__, template_folder=str(APP_DIR / "templates"), static_folder=str(APP_DIR / "static"))
jobs = {}
jobs_lock = threading.Lock()
desktop_api = None


def extract_first_url(text):
    match = re.search(r"https?://[^\s\"'<>，。；、）)】]+", text or "")
    return match.group(0).rstrip(".,;:!?，。；：！？") if match else ""


def safe_name(value, fallback="未命名", max_length=80):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" ._")
    return (value[:max_length].rstrip(" ._") or fallback)


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
        job["logs"] = job["logs"][-500:]


def read_base_config():
    if not BASE_CONFIG.exists():
        raise FileNotFoundError("下载组件未安装完整，请重新安装最新版。")
    text = BASE_CONFIG.read_text(encoding="utf-8", errors="replace")
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return {"cookies": extract_cookies_from_broken_yaml(text)}


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


def build_config_text(links, raw_dir, options):
    source = read_base_config()
    raw_dir.mkdir(parents=True, exist_ok=True)
    source.update(
        {
            "link": list(links),
            "path": str(raw_dir) + os.sep,
            "music": False,
            "cover": False,
            "avatar": False,
            "json": False,
            "folderstyle": True,
            "author_dir": "nickname",
            "download_pinned": True,
            "database": True,
            "database_path": str(raw_dir / "dy_downloader.db"),
            "start_time": "",
            "end_time": "",
            "filename_template": "{date}_{author}_{title}_{id}_{type}",
            "folder_template": "{date}_{id}",
            "mode": ["post"],
            "media_types": ["video", "gallery"],
        }
    )
    return yaml.safe_dump(source, allow_unicode=True, sort_keys=False)


def scan_filter(works, options):
    start = options.get("start_date") or ""
    end = options.get("end_date") or ""
    include_pinned = bool(options.get("include_pinned"))
    videos = bool(options.get("download_videos", True))
    images = bool(options.get("download_images", True))
    filtered = []
    for work in works:
        day = (work.get("date") or "")[:10]
        if start and day and day < start:
            continue
        if end and day and day > end:
            continue
        if not include_pinned and work.get("is_pinned"):
            continue
        if work.get("media_type") == "video" and not videos:
            continue
        if work.get("media_type") == "gallery" and not images:
            continue
        filtered.append(work)
    return filtered


def run_scan(job_id, link, options):
    try:
        if not PYTHON_EXE.exists() or not SCAN_WORKER.exists():
            raise FileNotFoundError("扫描组件未安装完整，请重新安装最新版。")
        update_job(job_id, status="scanning", progress=2)
        append_log(job_id, "开始读取博主主页...")
        env = os.environ.copy()
        env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        command = [
            str(PYTHON_EXE),
            str(SCAN_WORKER),
            "--downloader-dir",
            str(DOWNLOADER_DIR),
            "--config",
            str(BASE_CONFIG),
            "--url",
            link,
            "--limit",
            str(max(0, int(options.get("limit") or 0))),
        ]
        if options.get("include_pinned"):
            command.append("--include-pinned")
        if options.get("download_videos", True):
            command.append("--videos")
        if options.get("download_images", True):
            command.append("--images")
        if options.get("start_date"):
            command.extend(["--start-date", str(options["start_date"])])
        if options.get("end_date"):
            command.extend(["--end-date", str(options["end_date"])])
        process = subprocess.Popen(
            command,
            cwd=str(DOWNLOADER_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
        update_job(job_id, pid=process.pid)
        result = None
        assert process.stdout is not None
        for line in process.stdout:
            text = line.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                append_log(job_id, text)
                continue
            event_type = event.get("event")
            if event_type == "progress":
                update_job(job_id, progress=event.get("progress", 10), scanned=event.get("count", 0))
                append_log(job_id, event.get("message", "正在读取作品..."))
            elif event_type == "profile":
                update_job(job_id, author=event.get("author"), expected=event.get("expected", 0))
            elif event_type == "result":
                result = event
            elif event_type == "error":
                append_log(job_id, event.get("message", "扫描失败"))

        return_code = process.wait()
        if return_code != 0 or not result:
            raise RuntimeError("没有读取到作品。请确认已登录、链接可访问，并重试。")
        works = result.get("works") or []
        update_job(
            job_id,
            status="ready",
            progress=100,
            author=result.get("author") or "未知博主",
            expected=result.get("expected", 0),
            works=works,
            work_count=len(works),
            resolved_url=result.get("resolved_url") or link,
        )
        append_log(job_id, f"扫描完成，共读取 {len(works)} 个可选作品。")
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc))
        append_log(job_id, f"扫描失败：{exc}")


def load_database_records(db_path):
    if not db_path.exists():
        return []
    connection = sqlite3.connect(str(db_path))
    try:
        rows = connection.execute(
            "SELECT aweme_id, aweme_type, title, author_name, create_time, file_path, metadata "
            "FROM aweme ORDER BY create_time DESC"
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
    return [path for path in raw_dir.rglob(f"*{record['aweme_id']}*") if path.is_file()]


def output_base_name(record):
    timestamp = int(record.get("create_time") or 0)
    date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d") if timestamp else "未知日期"
    author = safe_name(record.get("author"), "未知博主", 24)
    title = safe_name(record.get("title"), "无标题", 48)
    work_id = safe_name(record.get("aweme_id"), "未知编号", 24)
    mode = "图文" if record.get("media_type") == "gallery" else "视频"
    return f"{date}_{author}_{title}_{work_id}_{mode}"


def organize_outputs(raw_dir, selected_dir, options):
    records = load_database_records(raw_dir / "dy_downloader.db")
    if not records:
        return {"author": "", "video_count": 0, "image_count": 0, "works": [], "output_dir": ""}
    author = safe_name(records[0]["author"], "未知博主", 40)
    author_dir = selected_dir / author
    video_dir = author_dir / "mp4"
    image_dir = author_dir / "图片"
    author_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(exist_ok=True)
    image_dir.mkdir(exist_ok=True)
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
    works = []
    video_count = 0
    image_count = 0
    for record in records:
        copied = []
        base_name = output_base_name(record)
        files = find_record_files(raw_dir, record)
        if record["media_type"] == "video":
            for index, source in enumerate([p for p in files if p.suffix.lower() == ".mp4"], start=1):
                suffix = "" if index == 1 else f"_{index}"
                destination = unique_destination(video_dir / f"{base_name}{suffix}.mp4")
                shutil.move(str(source), str(destination))
                copied.append(str(destination))
                video_count += 1
        else:
            images = [path for path in files if path.suffix.lower() in image_exts]
            for index, source in enumerate(images, start=1):
                destination = unique_destination(image_dir / f"{base_name}_{index}{source.suffix.lower()}")
                shutil.move(str(source), str(destination))
                copied.append(str(destination))
                image_count += 1
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
                    item["date"], item["title"], item["type"], item["digg"], item["comments"],
                    item["collects"], item["shares"], item["aweme_id"], " | ".join(item["files"]),
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


def run_download(job_id, selected_works, output_dir_text, options):
    run_dir = APP_DATA_DIR / "runs" / job_id
    raw_dir = run_dir / "download"
    try:
        selected_dir = Path(output_dir_text).expanduser().resolve()
        selected_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        if not PYTHON_EXE.exists():
            raise FileNotFoundError("下载组件未安装完整，请重新安装最新版。")
        total = len(selected_works)
        update_job(job_id, status="running", progress=1, total=total, completed=0, output_dir=str(selected_dir))
        env = os.environ.copy()
        env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"})
        for index, work in enumerate(selected_works, start=1):
            aweme_id = str(work.get("aweme_id") or "")
            media_type = work.get("media_type") or "video"
            work_url = f"https://www.douyin.com/{'note' if media_type == 'gallery' else 'video'}/{aweme_id}"
            config_path = run_dir / f"config-{index}.yml"
            config_path.write_text(build_config_text([work_url], raw_dir, options), encoding="utf-8")
            append_log(job_id, f"[{index}/{total}] 正在下载：{work.get('title') or aweme_id}")
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
            update_job(job_id, pid=process.pid)
            assert process.stdout is not None
            for line in process.stdout:
                append_log(job_id, line)
            return_code = process.wait()
            if return_code != 0:
                append_log(job_id, f"[{index}/{total}] 下载失败，继续处理下一项。")
            completed = index
            update_job(
                job_id,
                completed=completed,
                progress=min(92, int(completed / total * 92)),
                current_title=work.get("title") or aweme_id,
            )
        update_job(job_id, progress=95)
        append_log(job_id, "下载完成，正在整理文件并生成作品清单...")
        manifest = organize_outputs(raw_dir, selected_dir, options)
        if not manifest["works"]:
            raise RuntimeError("所选作品没有下载成功，请查看运行日志。")
        update_job(job_id, status="done", progress=100, manifest=manifest, works=manifest["works"])
        append_log(job_id, f"整理完成：{manifest['video_count']} 个视频，{manifest['image_count']} 张图片。")
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc))
        append_log(job_id, f"失败：{exc}")
    finally:
        if raw_dir.exists() and safe_job(job_id).get("status") == "done":
            shutil.rmtree(raw_dir, ignore_errors=True)


@app.route("/")
def index():
    return render_template("index.html", default_output=str(DEFAULT_OUTPUT))


@app.route("/api/scan", methods=["POST"])
def scan():
    data = request.get_json(force=True)
    link = extract_first_url(data.get("link") or "")
    options = data.get("options") or {}
    if not link:
        return jsonify({"error": "没有找到有效的抖音链接。"}), 400
    job_id = uuid.uuid4().hex[:12]
    update_job(job_id, kind="scan", status="queued", progress=1, logs=[], works=[])
    threading.Thread(target=run_scan, args=(job_id, link, options), daemon=True).start()
    return jsonify({"job_id": job_id, "link": link})


@app.route("/api/start", methods=["POST"])
def start():
    data = request.get_json(force=True)
    output_dir = (data.get("output_dir") or str(DEFAULT_OUTPUT)).strip()
    options = data.get("options") or {}
    selected_works = data.get("selected_works") or []
    if not output_dir:
        return jsonify({"error": "请选择保存位置。"}), 400
    if not selected_works:
        return jsonify({"error": "请先扫描并至少选择一个作品。"}), 400
    job_id = uuid.uuid4().hex[:12]
    update_job(job_id, kind="download", status="queued", progress=1, logs=[], works=[])
    threading.Thread(
        target=run_download,
        args=(job_id, selected_works, output_dir, options),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


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
    return jsonify({"ok": True, "message": "登录窗口已在应用内打开。"})


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
