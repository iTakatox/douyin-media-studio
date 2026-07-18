import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from platforms import detect_platform, platform_details

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def emit(event, **payload):
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


class CaptureLogger:
    def __init__(self):
        self.last_error = ""

    def debug(self, _message):
        pass

    def warning(self, _message):
        pass

    def error(self, message):
        self.last_error = re.sub(r"^ERROR:\s*", "", str(message or "")).strip()


def safe_name(value, fallback="未命名", max_length=80):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or ""))
    value = re.sub(r"\s+", " ", value).strip(" ._")
    return value[:max_length].rstrip(" ._") or fallback


def unique_destination(path):
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成唯一文件名：{path.name}")


def timestamp_value(info):
    return int(info.get("timestamp") or info.get("release_timestamp") or 0)


def normalize_entry(info, fallback_url, platform_id):
    timestamp = timestamp_value(info)
    uploader = info.get("uploader") or info.get("channel") or info.get("creator") or "未知作者"
    item_id = str(info.get("id") or info.get("display_id") or fallback_url)
    webpage_url = info.get("webpage_url") or info.get("original_url") or info.get("url") or fallback_url
    return {
        "aweme_id": item_id,
        "author": uploader,
        "title": info.get("title") or info.get("description") or "无标题",
        "create_time": timestamp,
        "date": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M") if timestamp else "",
        "date_file": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d") if timestamp else "未知日期",
        "media_type": "video",
        "type": "视频",
        "digg": info.get("like_count"),
        "comments": info.get("comment_count"),
        "collects": None,
        "shares": info.get("repost_count"),
        "status": "待下载",
        "platform": platform_id,
        "platform_label": platform_details(platform_id)["label"],
        "source_url": webpage_url,
    }


def entries_from_info(info):
    entries = info.get("entries")
    if entries is None:
        return [info]
    return [entry for entry in entries if isinstance(entry, dict)]


def ydl_options(limit=0, logger=None):
    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": False,
    }
    if logger:
        options["logger"] = logger
    if limit:
        options["playlistend"] = limit
    return options


def scan(url, limit):
    import yt_dlp

    platform_id = detect_platform(url)
    details = platform_details(platform_id)
    emit("progress", progress=8, message=f"正在匿名解析 {details['label']} 链接...")
    logger = CaptureLogger()
    with yt_dlp.YoutubeDL(ydl_options(limit, logger)) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        reason = logger.last_error or "平台没有返回可下载的公开内容"
        raise RuntimeError(f"{reason}。可能需要登录、切换网络，或该链接类型暂不受支持。")
    raw_entries = entries_from_info(info)
    works = []
    for entry in raw_entries[: limit or None]:
        works.append(normalize_entry(entry, url, platform_id))
        emit(
            "progress",
            progress=min(94, 12 + int(len(works) / max(1, min(len(raw_entries), limit or len(raw_entries))) * 82)),
            count=len(works),
            message=f"已读取 {len(works)} 个公开作品",
        )
    if not works:
        raise RuntimeError("没有读取到公开作品；该平台或该页面可能要求登录。")
    author = works[0]["author"] if works else "未知作者"
    emit(
        "result",
        author=author,
        platform=platform_id,
        platform_label=details["label"],
        anonymous=True,
        expected=len(raw_entries),
        resolved_url=url,
        works=works,
    )


def download_one(ydl, work, output_root, index, total):
    platform_id = work.get("platform") or detect_platform(work.get("source_url") or "")
    platform_label = platform_details(platform_id)["label"]
    author = safe_name(work.get("author"), "未知作者", 40)
    title = safe_name(work.get("title"), "无标题", 60)
    item_id = safe_name(work.get("aweme_id"), "未知编号", 32)
    date = work.get("date_file") or (work.get("date") or "")[:10] or "未知日期"
    author_dir = output_root / platform_label / author
    incoming_dir = author_dir / "_下载中"
    video_dir = author_dir / "mp4"
    image_dir = author_dir / "图片"
    text_dir = author_dir / "文本"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    base_name = safe_name(f"{date}_{author}_{title}_{item_id}", max_length=160)
    before = {path.resolve() for path in incoming_dir.iterdir() if path.is_file()}
    ydl.params["outtmpl"] = str(incoming_dir / f"{base_name}.%(ext)s")
    emit("progress", index=index, total=total, progress=int((index - 1) / total * 95), message=f"[{index}/{total}] 正在下载：{title}")
    info = ydl.extract_info(work["source_url"], download=True)
    after = {path.resolve() for path in video_dir.iterdir() if path.is_file()}
    after = {path.resolve() for path in incoming_dir.iterdir() if path.is_file()}
    downloaded = [Path(path) for path in sorted(after - before)]
    files = []
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
    video_exts = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
    for source in downloaded:
        suffix = source.suffix.lower()
        if suffix in image_exts:
            destination = unique_destination(image_dir / f"{base_name}_图片{suffix}")
        elif suffix in video_exts:
            destination = unique_destination(video_dir / f"{base_name}_视频{suffix}")
        else:
            destination = unique_destination(author_dir / source.name)
        source.replace(destination)
        files.append(str(destination))
    text_path = unique_destination(text_dir / f"{base_name}_正文.txt")
    body = work.get("title") or ""
    if info and isinstance(info, dict):
        body = info.get("description") or info.get("title") or body
    text_path.write_text(
        "\n".join([
            f"平台：{platform_label}",
            f"作者：{work.get('author') or author}",
            f"发布日期：{work.get('date') or ''}",
            f"作品ID：{work.get('aweme_id') or ''}",
            f"原始链接：{work.get('source_url') or ''}",
            "",
            body,
        ]),
        encoding="utf-8",
    )
    files.append(str(text_path))
    return author_dir, {
        **work,
        "files": files,
        "status": "已下载" if downloaded else "已保存文本",
        "downloaded_info": bool(info),
    }


def manifest_counts(rows):
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
    video_exts = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
    video_count = 0
    image_count = 0
    for row in rows:
        for file_name in row.get("files") or []:
            suffix = Path(file_name).suffix.lower()
            if suffix in video_exts:
                video_count += 1
            elif suffix in image_exts:
                image_count += 1
    return video_count, image_count


def write_manifest(author_dir, rows):
    csv_path = author_dir / "作品清单.csv"
    try:
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["平台", "发布日期", "标题", "类型", "点赞", "评论", "分享", "作品ID", "原始链接", "本地文件", "状态"])
            for item in rows:
                writer.writerow([
                    item.get("platform_label"), item.get("date"), item.get("title"), item.get("type"),
                    item.get("digg"), item.get("comments"), item.get("shares"), item.get("aweme_id"),
                    item.get("source_url"), " | ".join(item.get("files") or []), item.get("status"),
                ])
    except PermissionError:
        csv_path = unique_destination(csv_path)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["平台", "发布日期", "标题", "类型", "点赞", "评论", "分享", "作品ID", "原始链接", "本地文件", "状态"])
            for item in rows:
                writer.writerow([
                    item.get("platform_label"), item.get("date"), item.get("title"), item.get("type"),
                    item.get("digg"), item.get("comments"), item.get("shares"), item.get("aweme_id"),
                    item.get("source_url"), " | ".join(item.get("files") or []), item.get("status"),
                ])
    video_count, image_count = manifest_counts(rows)
    manifest = {
        "author": rows[0].get("author") if rows else "",
        "video_count": video_count,
        "image_count": image_count,
        "comment_count": 0,
        "work_count": len(rows),
        "works": rows,
        "output_dir": str(author_dir),
        "csv_path": str(csv_path),
        "state_path": str(author_dir / "任务状态.json"),
    }
    Path(manifest["state_path"]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def download(works_path, output_path):
    import yt_dlp

    works = json.loads(Path(works_path).read_text(encoding="utf-8"))
    output_root = Path(output_path).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    rows_by_dir = {}
    completed = []
    options = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "restrictfilenames": False,
        "windowsfilenames": True,
        # Prefer a ready-to-save file so a fresh installation does not require FFmpeg.
        "format": "best[ext=mp4]/best",
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        total = len(works)
        for index, work in enumerate(works, start=1):
            author_dir, row = download_one(ydl, work, output_root, index, total)
            rows_by_dir.setdefault(author_dir, []).append(row)
            completed.append(row)
            manifest = write_manifest(author_dir, rows_by_dir[author_dir])
            manifest["works"] = completed
            emit("item", completed=index, total=total, row=row, manifest=manifest, message=f"[{index}/{total}] 已实时保存")
    output_dir = str(next(iter(rows_by_dir), output_root))
    final_rows = completed
    final_manifest = write_manifest(Path(output_dir), final_rows) if final_rows else {
        "author": "",
        "video_count": 0,
        "image_count": 0,
        "comment_count": 0,
        "work_count": 0,
        "works": [],
        "output_dir": output_dir,
    }
    emit(
        "result",
        progress=100,
        manifest=final_manifest,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("scan", "download"))
    parser.add_argument("--url")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--works")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        if args.mode == "scan":
            scan(args.url, max(0, args.limit))
        else:
            download(args.works, args.output)
    except Exception as exc:
        emit("error", message=str(exc))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
