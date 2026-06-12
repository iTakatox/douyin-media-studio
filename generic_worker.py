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
    video_dir = author_dir / "mp4"
    video_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_name(f"{date}_{author}_{title}_{item_id}_视频", max_length=170)
    before = {path.resolve() for path in video_dir.iterdir() if path.is_file()}
    ydl.params["outtmpl"] = str(video_dir / f"{filename}.%(ext)s")
    emit("progress", index=index, total=total, progress=int((index - 1) / total * 95), message=f"[{index}/{total}] 正在下载：{title}")
    info = ydl.extract_info(work["source_url"], download=True)
    after = {path.resolve() for path in video_dir.iterdir() if path.is_file()}
    files = [str(path) for path in sorted(after - before)]
    return author_dir, {
        **work,
        "files": files,
        "status": "已下载" if files else "已跳过",
        "downloaded_info": bool(info),
    }


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
            emit("item", completed=index, total=total, message=f"[{index}/{total}] 下载完成")

    for author_dir, rows in rows_by_dir.items():
        csv_path = author_dir / "作品清单.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["平台", "发布日期", "标题", "类型", "点赞", "评论", "分享", "作品ID", "原始链接", "本地文件"])
            for item in rows:
                writer.writerow([
                    item.get("platform_label"), item.get("date"), item.get("title"), item.get("type"),
                    item.get("digg"), item.get("comments"), item.get("shares"), item.get("aweme_id"),
                    item.get("source_url"), " | ".join(item.get("files") or []),
                ])
    output_dir = str(next(iter(rows_by_dir), output_root))
    emit(
        "result",
        progress=100,
        manifest={
            "author": completed[0].get("author") if completed else "",
            "video_count": sum(len(item.get("files") or []) for item in completed),
            "image_count": 0,
            "comment_count": 0,
            "work_count": len(completed),
            "works": completed,
            "output_dir": output_dir,
        },
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
