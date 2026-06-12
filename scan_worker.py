import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def emit(event, **payload):
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


def media_type(item):
    image_post = item.get("image_post_info")
    if isinstance(image_post, dict) and (image_post.get("images") or image_post.get("image_list")):
        return "gallery"
    if item.get("images") or item.get("image_list"):
        return "gallery"
    if item.get("aweme_type") in {2, 68, 150} and not item.get("video"):
        return "gallery"
    return "video"


def normalize_item(item, fallback_author):
    author = item.get("author") or {}
    stats = item.get("statistics") or {}
    timestamp = int(item.get("create_time") or 0)
    return {
        "aweme_id": str(item.get("aweme_id") or ""),
        "author": author.get("nickname") or fallback_author or "未知博主",
        "title": (item.get("desc") or "无标题").strip(),
        "create_time": timestamp,
        "date": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M") if timestamp else "",
        "date_file": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d") if timestamp else "未知日期",
        "media_type": media_type(item),
        "type": "图文" if media_type(item) == "gallery" else "视频",
        "digg": stats.get("digg_count"),
        "comments": stats.get("comment_count"),
        "collects": stats.get("collect_count"),
        "shares": stats.get("share_count"),
        "is_pinned": bool(item.get("is_top") or item.get("is_pinned")),
        "platform": "douyin",
        "platform_label": "抖音",
        "source_url": (
            f"https://www.douyin.com/note/{item.get('aweme_id')}"
            if media_type(item) == "gallery"
            else f"https://www.douyin.com/video/{item.get('aweme_id')}"
        ),
    }


def include_work(work, args):
    day = (work.get("date") or "")[:10]
    if not args.include_pinned and work.get("is_pinned"):
        return False
    if args.start_date and day and day < args.start_date:
        return False
    if args.end_date and day and day > args.end_date:
        return False
    if work.get("media_type") == "video" and not args.videos:
        return False
    if work.get("media_type") == "gallery" and not args.images:
        return False
    return True


async def scan(config_path, raw_url, args):
    from config.config_loader import ConfigLoader
    from core.api_client import DouyinAPIClient
    from core.url_parser import URLParser
    from utils.validators import is_short_url, normalize_short_url

    config = ConfigLoader(config_path).config
    cookies = config.get("cookies") or {}
    if not cookies:
        raise RuntimeError("尚未保存登录信息，请先登录抖音。")

    async with DouyinAPIClient(cookies, config.get("proxy")) as client:
        url = raw_url
        if is_short_url(url):
            emit("progress", progress=5, message="正在解析分享短链接...")
            url = await client.resolve_short_url(normalize_short_url(url))
            if not url:
                raise RuntimeError("短链接解析失败，请确认链接仍然有效。")

        parsed = URLParser.parse(url)
        if not parsed or parsed.get("type") != "user" or not parsed.get("sec_uid"):
            raise RuntimeError("该链接不是抖音个人主页链接。")

        sec_uid = parsed["sec_uid"]
        emit("progress", progress=10, message="正在读取博主资料...")
        user = await client.get_user_info(sec_uid) or {}
        author = user.get("nickname") or "未知博主"
        expected = int(user.get("aweme_count") or 0)
        emit("profile", author=author, expected=expected, resolved_url=url)

        cursor = 0
        works = []
        seen = set()
        page = 0
        while True:
            page += 1
            response = await client.get_user_post(sec_uid, cursor, 20)
            items = response.get("items") or []
            if not items:
                break
            for item in items:
                normalized = normalize_item(item, author)
                aweme_id = normalized["aweme_id"]
                if aweme_id and aweme_id not in seen and include_work(normalized, args):
                    seen.add(aweme_id)
                    works.append(normalized)
                    if args.limit and len(works) >= args.limit:
                        break

            denominator = args.limit or expected or (len(works) + 20)
            progress = min(94, 12 + int(82 * len(works) / max(1, denominator)))
            emit(
                "progress",
                progress=progress,
                count=len(works),
                message=f"已读取 {len(works)} 个作品",
            )
            if (args.limit and len(works) >= args.limit) or not response.get("has_more"):
                break
            next_cursor = int(response.get("max_cursor") or response.get("cursor") or 0)
            if next_cursor == cursor:
                break
            cursor = next_cursor

        works.sort(key=lambda item: item.get("create_time") or 0, reverse=True)
        emit(
            "result",
            author=author,
            expected=expected,
            resolved_url=url,
            works=works,
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloader-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--include-pinned", action="store_true")
    parser.add_argument("--videos", action="store_true")
    parser.add_argument("--images", action="store_true")
    parser.add_argument("--start-date", default="")
    parser.add_argument("--end-date", default="")
    args = parser.parse_args()

    downloader_dir = Path(args.downloader_dir).resolve()
    sys.path.insert(0, str(downloader_dir))
    try:
        args.limit = max(0, args.limit)
        asyncio.run(scan(args.config, args.url, args))
    except Exception as exc:
        emit("error", message=str(exc))
        raise


if __name__ == "__main__":
    main()
