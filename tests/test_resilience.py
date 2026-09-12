import asyncio
import contextlib
import io
import json
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

from generic_worker import download, read_scan_cache, save_comment_payload, write_scan_cache
from resilience import CooperativePacer


class ResilienceTests(unittest.TestCase):
    def test_scan_cache_is_scoped_to_requested_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            write_scan_cache(directory, "https://example.test/user", "generic", 1, "作者", 4, [{"aweme_id": "1"}])
            self.assertIsNotNone(read_scan_cache(directory, "https://example.test/user", "generic", 1, 60))
            self.assertIsNone(read_scan_cache(directory, "https://example.test/user", "generic", 0, 60))

    def test_pacer_recovers_only_to_its_baseline(self):
        async def exercise():
            pacer = CooperativePacer(min_interval=0.5, max_interval=2.0)
            pacer.slow_down()
            self.assertGreater(pacer.min_interval, 0.5)
            for _ in range(20):
                pacer.recover()
            self.assertEqual(pacer.min_interval, 0.5)
            started = time.monotonic()
            await pacer.wait()
            await pacer.wait()
            self.assertGreaterEqual(time.monotonic() - started, 0.5)

        asyncio.run(exercise())

    def test_comment_payload_keeps_comment_and_reply_structure(self):
        with tempfile.TemporaryDirectory() as directory:
            work = {
                "aweme_id": "note-1",
                "title": "公开笔记",
                "platform_label": "小红书",
                "source_url": "https://www.xiaohongshu.com/explore/note-1",
            }
            path, records, status = save_comment_payload(
                Path(directory), "note-1", work,
                {"comments": [
                    {"id": "c1", "author": "甲", "text": "评论", "timestamp": 1},
                    {"id": "c2", "author": "乙", "text": "回复", "parent": "c1", "timestamp": 2},
                ]},
                0,
            )
            self.assertEqual(status, "已提取")
            self.assertEqual(len(records), 2)
            self.assertEqual(records[1]["层级"], "回复")
            self.assertEqual(json.loads(Path(path).read_text(encoding="utf-8"))["comments"][0]["id"], "c1")

    def test_download_writes_article_and_comment_exports(self):
        class FakeYoutubeDL:
            def __init__(self, options):
                self.params = dict(options)

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def extract_info(self, _url, download=False):
                if download:
                    target = Path(self.params["outtmpl"].replace("%(ext)s", "mp4"))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"test-media")
                return {
                    "title": "微博正文标题",
                    "description": "这是完整的微博正文。",
                    "comments": [
                        {"id": "c1", "author": "甲", "text": "第一条", "timestamp": 1},
                        {"id": "c2", "author": "乙", "text": "回复", "parent": "c1", "timestamp": 2},
                    ],
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            works_path = root / "works.json"
            works_path.write_text(json.dumps([{
                "aweme_id": "weibo-1", "author": "作者", "title": "微博正文标题",
                "date_file": "2026-09-12", "platform": "weibo", "platform_label": "微博",
                "source_url": "https://weibo.com/detail/weibo-1", "type": "视频",
            }], ensure_ascii=False), encoding="utf-8")
            previous = sys.modules.get("yt_dlp")
            sys.modules["yt_dlp"] = types.SimpleNamespace(YoutubeDL=FakeYoutubeDL)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    download(works_path, root / "output", include_comments=True)
            finally:
                if previous is None:
                    del sys.modules["yt_dlp"]
                else:
                    sys.modules["yt_dlp"] = previous
            author_dir = root / "output" / "微博" / "作者"
            self.assertIn("完整的微博正文", next((author_dir / "文本").glob("*.txt")).read_text(encoding="utf-8"))
            self.assertEqual(len((author_dir / "评论" / "全部评论.csv").read_bytes().decode("utf-8-sig").splitlines()[1:]), 2)
            state = json.loads((author_dir / "任务状态.json").read_text(encoding="utf-8"))
            self.assertEqual(state["comment_count"], 2)


if __name__ == "__main__":
    unittest.main()
