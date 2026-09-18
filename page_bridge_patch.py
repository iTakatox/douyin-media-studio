"""Desktop bridge for the maintained Douyin downloader API."""

import asyncio
import inspect
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


class PageBridgeError(RuntimeError):
    def __init__(self, code, message):
        self.page_bridge_code = code
        super().__init__(message)


class PageBridgeResult:
    def __init__(self, status, text):
        self.http_status = int(status or 0)
        self.text = str(text or "")
        try:
            self.body = json.loads(self.text) if self.text else None
        except json.JSONDecodeError:
            self.body = None


class LocalPageBridge:
    """Send gated requests through the application's authenticated Douyin page."""

    def __init__(self):
        self.url = os.environ.get("DOUYIN_PAGE_BRIDGE_URL", "").strip()
        self.token = os.environ.get("DOUYIN_PAGE_BRIDGE_TOKEN", "").strip()

    @property
    def available(self):
        return bool(self.url and self.token)

    async def fetch(self, path, params, *, method="GET", data=None):
        if not self.available:
            raise PageBridgeError("UNAVAILABLE", "应用内抖音请求通道不可用")
        payload = json.dumps(
            {"path": path, "query": params or {}, "method": method, "form": data},
            ensure_ascii=False,
        ).encode("utf-8")

        def send():
            request = urllib.request.Request(
                self.url,
                data=payload,
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "X-Douyin-Bridge-Token": self.token,
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    return response.status, response.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read().decode("utf-8", "replace")
            except urllib.error.URLError as exc:
                raise PageBridgeError("TRANSPORT_ERROR", "应用内抖音请求通道不可用") from exc

        status, text = await asyncio.to_thread(send)
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PageBridgeError("INVALID_RESPONSE", "应用内抖音请求返回了无效数据") from exc
        if status != 200:
            raise PageBridgeError(
                envelope.get("code", "PAGE_BRIDGE_ERROR"),
                envelope.get("message", "应用内抖音请求失败"),
            )
        return PageBridgeResult(envelope.get("status"), envelope.get("text"))


def install():
    """Inject the official page bridge dependency into external run.py processes."""
    bridge = LocalPageBridge()
    if not bridge.available:
        return

    downloader_dir = Path(os.environ.get("DOUYIN_DOWNLOADER_DIR", "")).resolve()
    if downloader_dir.is_dir() and str(downloader_dir) not in sys.path:
        sys.path.insert(0, str(downloader_dir))

    try:
        from core.api_client import DouyinAPIClient
    except ImportError:
        return

    if "page_bridge" not in inspect.signature(DouyinAPIClient.__init__).parameters:
        return

    original_init = DouyinAPIClient.__init__

    def patched_init(self, cookies, proxy=None, page_bridge=None):
        return original_init(self, cookies, proxy, page_bridge=page_bridge or bridge)

    DouyinAPIClient.__init__ = patched_init
