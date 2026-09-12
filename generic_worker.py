import argparse
import csv
import hashlib
import json
import re
import sys
import tempfile
import time
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
        yield info
        return
    for entry in entries:
        if isinstance(entry, dict):
            yield entry


def cache_path(cache_dir, url, platform_id, limit):
    digest = hashlib.sha256(f"{platform_id}\0{limit}\0{url}".encode("utf-8")).hexdigest()
    return Path(cache_dir) / "scan" / f"{digest}.json"


def read_scan_cache(cache_dir, url, platform_id, limit, ttl_seconds):
    if not cache_dir or ttl_seconds <= 0:
        return None
    target = cache_path(cache_dir, url, platform_id, limit)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        age = time.time() - float(payload.get("created_at") or 0)
        if age < 0 or age > ttl_seconds or payload.get("schema") != 1:
            return None
        if not isinstance(payload.get("works"), list):
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None


def write_scan_cache(cache_dir, url, platform_id, limit, author, expected, works):
    if not cache_dir:
        return
    target = cache_path(cache_dir, url, platform_id, limit)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "created_at": time.time(),
        "author": author,
        "expected": expected,
        "works": works,
    }
    # Replace atomically so closing the application during a scan never leaves
    # a malformed cache entry for the next run.
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=target.parent, delete=False, suffix=".tmp"
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        temporary = Path(handle.name)
    temporary.replace(target)


def ydl_options(limit=0, logger=None, cache_dir=None):
    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": False,
    }
    if cache_dir:
        options["cachedir"] = str(Path(cache_dir).resolve())
    if logger:
        options["logger"] = logger
    if limit:
        options["playlistend"] = limit
    return options


def scan(url, limit, cache_dir=None, cache_ttl=600):
    import yt_dlp

    platform_id = detect_platform(url)
    details = platform_details(platform_id)
    cached = read_scan_cache(cache_dir, url, platform_id, limit, cache_ttl)
    if cached:
        works = cached["works"][: limit or None]
        emit("progress", progress=95, count=len(works), message="已使用本地扫描缓存，未重复访问平台")
        emit(
            "result",
            author=cached.get("author") or "未知作者",
            platform=platform_id,
            platform_label=details["label"],
            anonymous=True,
            expected=cached.get("expected", len(works)),
            resolved_url=url,
            works=works,
            cached=True,
        )
        return
    emit("progress", progress=8, message=f"正在匿名解析 {details['label']} 链接...")
    logger = CaptureLogger()
    with yt_dlp.YoutubeDL(ydl_options(limit, logger, cache_dir)) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        reason = logger.last_error or "平台没有返回可下载的公开内容"
        raise RuntimeError(f"{reason}。可能需要登录、切换网络，或该链接类型暂不受支持。")
    works = []
    expected = int(info.get("playlist_count") or info.get("n_entries") or 0)
    for entry in entries_from_info(info):
        works.append(normalize_entry(entry, url, platform_id))
        emit(
            "progress",
            progress=min(94, 12 + int(len(works) / max(1, limit or expected or len(works)) * 82)),
            count=len(works),
            message=f"已读取 {len(works)} 个公开作品",
        )
        if limit and len(works) >= limit:
            break
    if not works:
        raise RuntimeError("没有读取到公开作品；该平台或该页面可能要求登录。")
    author = works[0]["author"] if works else "未知作者"
    write_scan_cache(cache_dir, url, platform_id, limit, author, expected or len(works), works)
    emit(
        "result",
        author=author,
        platform=platform_id,
        platform_label=details["label"],
        anonymous=True,
        expected=expected or len(works),
        resolved_url=url,
        works=works,
    )


def existing_media(author_dir, base_name):
    candidates = []
    for directory in (author_dir / "mp4", author_dir / "图片"):
        if directory.exists():
            candidates.extend(
                str(path)
                for path in directory.iterdir()
                if path.is_file() and path.name.startswith(f"{base_name}_")
            )
    return sorted(candidates)


def existing_text(text_dir, base_name):
    candidates = [
        path for path in text_dir.iterdir()
        if path.is_file() and path.name.startswith(f"{base_name}_正文") and path.suffix.lower() == ".txt"
    ]
    return sorted(candidates)[0] if candidates else None


def comment_records(comments, work):
    records = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        timestamp = int(comment.get("timestamp") or 0)
        records.append({
            "作品ID": str(work.get("aweme_id") or ""),
            "作品标题": work.get("title") or "",
            "层级": "回复" if comment.get("parent") not in {None, "", "root"} else "评论",
            "评论ID": str(comment.get("id") or ""),
            "回复评论ID": "" if comment.get("parent") in {None, "", "root"} else str(comment.get("parent")),
            "用户昵称": comment.get("author") or "",
            "用户ID": str(comment.get("author_id") or ""),
            "评论内容": comment.get("text") or comment.get("html") or "",
            "发布时间": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M") if timestamp else "",
            "点赞": comment.get("like_count") or 0,
        })
    return records


def save_comment_payload(comment_dir, base_name, work, info, max_comments):
    comment_dir.mkdir(parents=True, exist_ok=True)
    available = isinstance(info, dict) and "comments" in info
    comments = list(info.get("comments") or []) if available else []
    if max_comments:
        comments = comments[:max_comments]
    records = comment_records(comments, work)
    status = "已提取" if records else ("未返回评论" if available else "当前解析器未提供评论")
    target = unique_destination(comment_dir / f"{base_name}_评论.json")
    target.write_text(
        json.dumps({
            "platform": work.get("platform_label"),
            "work_id": work.get("aweme_id"),
            "title": work.get("title"),
            "source_url": work.get("source_url"),
            "retrieved_at": datetime.now().isoformat(timespec="seconds"),
            "source": "yt-dlp",
            "status": status,
            "comments": comments,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(target), records, status


def download_one(ydl, work, output_root, index, total, include_comments=False, max_comments=0):
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
    comment_dir = author_dir / "评论"
    incoming_dir.mkdir(parents=True, exist_ok=True)
    video_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    base_name = safe_name(f"{date}_{author}_{title}_{item_id}", max_length=160)
    existing = existing_media(author_dir, base_name)
    if existing:
        emit("progress", index=index, total=total, progress=int((index - 1) / total * 95), message=f"[{index}/{total}] 已存在，跳过媒体下载：{title}")
        info = ydl.extract_info(work["source_url"], download=False) if include_comments else None
        downloaded = []
    else:
        before = {path.resolve() for path in incoming_dir.iterdir() if path.is_file()}
        ydl.params["outtmpl"] = str(incoming_dir / f"{base_name}.%(ext)s")
        emit("progress", index=index, total=total, progress=int((index - 1) / total * 95), message=f"[{index}/{total}] 正在下载：{title}")
        info = ydl.extract_info(work["source_url"], download=True)
        after = {path.resolve() for path in incoming_dir.iterdir() if path.is_file()}
        downloaded = [Path(path) for path in sorted(after - before)]
    files = list(existing)
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
    text_path = existing_text(text_dir, base_name)
    if not text_path:
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
    comment_file = ""
    records = []
    comment_status = "未请求"
    if include_comments:
        comment_file, records, comment_status = save_comment_payload(
            comment_dir, base_name, work, info, max_comments
        )
        files.append(comment_file)
        emit(
            "progress", index=index, total=total, progress=int(index / total * 95),
            message=f"[{index}/{total}] 评论：{comment_status}（{len(records)} 条）",
        )
    return author_dir, {
        **work,
        "files": files,
        "status": "已下载" if downloaded else ("已存在" if existing else "已保存文本"),
        "downloaded_info": bool(info),
        "comment_requested": include_comments,
        "comment_file": comment_file,
        "saved_comments": len(records),
        "comment_status": comment_status,
        "_comment_records": records,
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


def write_manifest(author_dir, rows, all_comment_records=None):
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
    all_comment_records = all_comment_records or []
    comment_csv_path = ""
    if any(item.get("comment_requested") for item in rows):
        comment_dir = author_dir / "评论"
        comment_dir.mkdir(parents=True, exist_ok=True)
        comment_csv = comment_dir / "全部评论.csv"
        with comment_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            fields = [
                "作品ID", "作品标题", "层级", "评论ID", "回复评论ID", "用户昵称",
                "用户ID", "评论内容", "发布时间", "点赞",
            ]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(all_comment_records)
        comment_csv_path = str(comment_csv)
    video_count, image_count = manifest_counts(rows)
    manifest = {
        "author": rows[0].get("author") if rows else "",
        "video_count": video_count,
        "image_count": image_count,
        "comment_count": len(all_comment_records),
        "work_count": len(rows),
        "works": rows,
        "output_dir": str(author_dir),
        "csv_path": str(csv_path),
        "comment_csv_path": comment_csv_path,
        "state_path": str(author_dir / "任务状态.json"),
    }
    Path(manifest["state_path"]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def download(works_path, output_path, cache_dir=None, include_comments=False, max_comments=0):
    import yt_dlp

    works = json.loads(Path(works_path).read_text(encoding="utf-8"))
    output_root = Path(output_path).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    rows_by_dir = {}
    comments_by_dir = {}
    completed = []
    options = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "continuedl": True,
        "retries": 2,
        "fragment_retries": 2,
        "file_access_retries": 3,
        "socket_timeout": 20,
        "concurrent_fragment_downloads": 2,
        # Prefer a ready-to-save file so a fresh installation does not require FFmpeg.
        "format": "best[ext=mp4]/best",
        # This is a documented yt-dlp feature. It only uses comments that the
        # platform extractor exposes; access controls are never bypassed.
        "getcomments": include_comments,
    }
    if cache_dir:
        options["cachedir"] = str(Path(cache_dir).resolve())
    with yt_dlp.YoutubeDL(options) as ydl:
        total = len(works)
        for index, work in enumerate(works, start=1):
            author_dir, row = download_one(
                ydl, work, output_root, index, total, include_comments, max_comments
            )
            records = row.pop("_comment_records", [])
            rows_by_dir.setdefault(author_dir, []).append(row)
            comments_by_dir.setdefault(author_dir, []).extend(records)
            completed.append(row)
            manifest = write_manifest(author_dir, rows_by_dir[author_dir], comments_by_dir[author_dir])
            manifest["works"] = completed
            emit("item", completed=index, total=total, row=row, manifest=manifest, message=f"[{index}/{total}] 已实时保存")
    output_dir = str(next(iter(rows_by_dir), output_root))
    final_rows = completed
    final_manifest = write_manifest(
        Path(output_dir), final_rows,
        [record for records in comments_by_dir.values() for record in records],
    ) if final_rows else {
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
    parser.add_argument("--cache-dir", default="")
    parser.add_argument("--cache-ttl", type=int, default=600)
    parser.add_argument("--comments", action="store_true")
    parser.add_argument("--max-comments", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.mode == "scan":
            scan(args.url, max(0, args.limit), args.cache_dir, max(0, args.cache_ttl))
        else:
            download(
                args.works, args.output, args.cache_dir,
                args.comments, max(0, args.max_comments),
            )
    except Exception as exc:
        emit("error", message=str(exc))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
