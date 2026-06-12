import argparse
import asyncio
import json
import sys
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def emit(event, **payload):
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


async def fetch_all_replies(client, aweme_id, comment_id, page_size):
    replies = []
    seen = set()
    cursor = 0
    while True:
        page = await client.get_aweme_comment_replies(
            aweme_id=aweme_id,
            comment_id=comment_id,
            cursor=cursor,
            count=page_size,
        )
        items = page.get("items") or []
        for reply in items:
            reply_id = str(reply.get("cid") or reply.get("comment_id") or "")
            if reply_id and reply_id not in seen:
                seen.add(reply_id)
                replies.append(reply)
        if not page.get("has_more"):
            break
        next_cursor = int(page.get("max_cursor") or 0)
        if next_cursor == cursor:
            break
        cursor = next_cursor
        await asyncio.sleep(0.08)
    return replies


async def fetch_all_comments(client, aweme_id, include_replies, max_comments, page_size):
    comments = []
    seen = set()
    cursor = 0
    while True:
        page = await client.get_aweme_comments(
            aweme_id,
            cursor=cursor,
            count=page_size,
            include_replies=False,
        )
        items = page.get("items") or []
        for comment in items:
            comment_id = str(comment.get("cid") or comment.get("comment_id") or "")
            if comment_id and comment_id in seen:
                continue
            if comment_id:
                seen.add(comment_id)
            if include_replies and comment_id and int(comment.get("reply_comment_total") or 0) > 0:
                comment["_replies"] = await fetch_all_replies(
                    client, aweme_id, comment_id, page_size
                )
            comments.append(comment)
            if max_comments and len(comments) >= max_comments:
                return comments[:max_comments]
        if not page.get("has_more") or not items:
            break
        next_cursor = int(page.get("max_cursor") or 0)
        if next_cursor == cursor:
            break
        cursor = next_cursor
        await asyncio.sleep(0.1)
    return comments


async def collect(args):
    from core.api_client import DouyinAPIClient

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    cookies = config.get("cookies") or {}
    if not cookies:
        raise RuntimeError("尚未保存登录信息，请先登录抖音。")
    works = json.loads(Path(args.works).read_text(encoding="utf-8"))
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    async with DouyinAPIClient(cookies, config.get("proxy")) as client:
        total = len(works)
        for index, work in enumerate(works, start=1):
            aweme_id = str(work.get("aweme_id") or "")
            emit(
                "progress",
                index=index,
                total=total,
                progress=int((index - 1) / max(1, total) * 100),
                message=f"[{index}/{total}] 正在提取评论：{work.get('title') or aweme_id}",
            )
            comments = await fetch_all_comments(
                client,
                aweme_id,
                args.include_replies,
                args.max_comments,
                args.page_size,
            )
            payload = {
                "aweme_id": aweme_id,
                "title": work.get("title") or "",
                "count": len(comments),
                "include_replies": args.include_replies,
                "comments": comments,
            }
            target = output_dir / f"{aweme_id}_comments.json"
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            reply_count = sum(len(item.get("_replies") or []) for item in comments)
            emit(
                "item",
                aweme_id=aweme_id,
                comments=len(comments),
                replies=reply_count,
                message=f"[{index}/{total}] 已提取 {len(comments)} 条评论、{reply_count} 条回复",
            )
        emit("result", progress=100)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloader-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--works", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--max-comments", type=int, default=0)
    parser.add_argument("--page-size", type=int, default=20)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.downloader_dir).resolve()))
    args.max_comments = max(0, args.max_comments)
    args.page_size = max(1, min(20, args.page_size))
    try:
        asyncio.run(collect(args))
    except Exception as exc:
        emit("error", message=str(exc))
        raise


if __name__ == "__main__":
    main()
