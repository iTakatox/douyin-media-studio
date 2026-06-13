import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

import yaml

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def emit(event, **payload):
    print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)


async def fetch_reply_page(client, aweme_id, comment_id, cursor, page_size):
    # Reply endpoints trigger anti-bot more often. Use the client's quiet request
    # path so a blocked reply page degrades to an empty result instead of a fatal log.
    if all(hasattr(client, name) for name in ("_default_query", "_request_json", "_normalize_paged_response")):
        params = await client._default_query()
        params.update({
            "item_id": aweme_id,
            "comment_id": comment_id,
            "cursor": cursor,
            "count": page_size,
        })
        raw = await client._request_json(
            "/aweme/v1/web/comment/list/reply/",
            params,
            suppress_error=True,
        )
        return client._normalize_paged_response(raw, item_keys=["comments"])
    return await client.get_aweme_comment_replies(
        aweme_id=aweme_id,
        comment_id=comment_id,
        cursor=cursor,
        count=page_size,
    )


async def fetch_all_replies(client, aweme_id, comment_id, page_size):
    replies = []
    seen = set()
    cursor = 0
    while True:
        page = await fetch_reply_page(client, aweme_id, comment_id, cursor, page_size)
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


async def fetch_comment_page(client, aweme_id, cursor, page_size):
    if all(hasattr(client, name) for name in ("_default_query", "_request_json", "_normalize_paged_response")):
        params = await client._default_query()
        params.update({
            "aweme_id": aweme_id,
            "cursor": cursor,
            "count": page_size,
            "item_type": "0",
            "insert_ids": "",
            "whale_cut_token": "",
            "cut_version": "1",
            "rcFT": "",
        })
        raw = await client._request_json(
            "/aweme/v1/web/comment/list/",
            params,
            suppress_error=True,
        )
        if not raw:
            return {"items": [], "has_more": False, "max_cursor": cursor}, True
        return client._normalize_paged_response(raw, item_keys=["comments"]), False
    page = await client.get_aweme_comments(
        aweme_id,
        cursor=cursor,
        count=page_size,
        include_replies=False,
    )
    return page, False


async def fetch_all_comments(client, aweme_id, include_replies, max_comments, page_size):
    comments = []
    seen = set()
    cursor = 0
    while True:
        page, access_limited = await fetch_comment_page(client, aweme_id, cursor, page_size)
        if access_limited:
            return comments, True
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
                if not comment["_replies"]:
                    comment["_reply_limited"] = True
            comments.append(comment)
            if max_comments and len(comments) >= max_comments:
                return comments[:max_comments], False
        if not page.get("has_more") or not items:
            break
        next_cursor = int(page.get("max_cursor") or 0)
        if next_cursor == cursor:
            break
        cursor = next_cursor
        await asyncio.sleep(0.1)
    return comments, False


def write_pending_csv(output_dir, works):
    target = output_dir / "未完成作品.csv"
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["作品ID", "标题", "发布日期", "原因"])
        for work in works:
            writer.writerow([
                work.get("aweme_id"),
                work.get("title"),
                work.get("date"),
                "一级评论接口触发风控，请稍后重试",
            ])
    return target


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
        completed = 0
        failed_works = []
        consecutive_limited = 0
        for index, work in enumerate(works, start=1):
            aweme_id = str(work.get("aweme_id") or "")
            emit(
                "progress",
                index=index,
                total=total,
                progress=int((index - 1) / max(1, total) * 100),
                message=f"[{index}/{total}] 正在提取评论：{work.get('title') or aweme_id}",
            )
            comments, access_limited = await fetch_all_comments(
                client,
                aweme_id,
                args.include_replies,
                args.max_comments,
                args.page_size,
            )
            if access_limited:
                failed_works.append(work)
                consecutive_limited += 1
                emit(
                    "item",
                    aweme_id=aweme_id,
                    comments=0,
                    replies=0,
                    access_limited=True,
                    message=f"[{index}/{total}] 一级评论访问受限，已加入待重试清单",
                )
                if consecutive_limited >= args.stop_after_limited:
                    failed_works.extend(works[index:])
                    emit(
                        "progress",
                        progress=int(index / max(1, total) * 100),
                        message=f"连续 {consecutive_limited} 个作品受到风控，已自动停止并保留进度",
                    )
                    break
                await asyncio.sleep(1.5)
                continue
            consecutive_limited = 0
            payload = {
                "aweme_id": aweme_id,
                "title": work.get("title") or "",
                "count": len(comments),
                "include_replies": args.include_replies,
                "comments": comments,
            }
            target = output_dir / f"{aweme_id}_comments.json"
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            completed += 1
            reply_count = sum(len(item.get("_replies") or []) for item in comments)
            limited_count = sum(1 for item in comments if item.get("_reply_limited"))
            emit(
                "item",
                aweme_id=aweme_id,
                comments=len(comments),
                replies=reply_count,
                reply_limited=limited_count,
                message=(
                    f"[{index}/{total}] 已提取 {len(comments)} 条评论、{reply_count} 条回复"
                    + (f"；{limited_count} 条评论的回复受平台限制" if limited_count else "")
                ),
            )
        pending_path = write_pending_csv(output_dir, failed_works) if failed_works else ""
        emit(
            "result",
            progress=100,
            completed=completed,
            failed=len(failed_works),
            pending_works=failed_works,
            pending_path=str(pending_path) if pending_path else "",
            stopped_early=bool(failed_works),
            message=(
                f"评论任务结束：完成 {completed} 个，待重试 {len(failed_works)} 个"
                if failed_works
                else f"评论任务完成：共处理 {completed} 个作品"
            ),
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--downloader-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--works", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--include-replies", action="store_true")
    parser.add_argument("--max-comments", type=int, default=0)
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--stop-after-limited", type=int, default=3)
    args = parser.parse_args()
    sys.path.insert(0, str(Path(args.downloader_dir).resolve()))
    args.max_comments = max(0, args.max_comments)
    args.page_size = max(1, min(20, args.page_size))
    args.stop_after_limited = max(1, args.stop_after_limited)
    try:
        asyncio.run(collect(args))
    except Exception as exc:
        emit("error", message=str(exc))
        raise


if __name__ == "__main__":
    main()
