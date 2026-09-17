"""Apply the desktop page bridge to the external downloader at process startup."""

import asyncio
import json
import os
import urllib.error
import urllib.request


GATED_PATHS = {
    "/aweme/v1/web/aweme/post/",
    "/aweme/v1/web/aweme/detail/",
}


class PageBridgeError(RuntimeError):
    pass


async def bridge_request(url, token, path, params):
    payload = json.dumps(
        {"path": path, "query": params or {}, "method": "GET", "form": None},
        ensure_ascii=False,
    ).encode("utf-8")

    def send():
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "X-Douyin-Bridge-Token": token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    status, text = await asyncio.to_thread(send)
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PageBridgeError("应用内抖音请求返回了无效数据") from exc
    if status != 200:
        raise PageBridgeError(envelope.get("message", "应用内抖音请求失败"))
    response_text = str(envelope.get("text") or "")
    if int(envelope.get("status") or 0) != 200:
        raise PageBridgeError(f"抖音详情请求失败（HTTP {envelope.get('status') or 0}）")
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise PageBridgeError("抖音详情页返回了无效数据") from exc
    if not isinstance(data, dict):
        raise PageBridgeError("抖音详情页没有返回可用数据")
    return data


def install():
    url = os.environ.get("DOUYIN_PAGE_BRIDGE_URL", "").strip()
    token = os.environ.get("DOUYIN_PAGE_BRIDGE_TOKEN", "").strip()
    if not (url and token):
        return

    try:
        from core.api_client import DouyinAPIClient
    except ImportError:
        return

    original_request_json = DouyinAPIClient._request_json

    async def patched_request_json(self, path, params, *, suppress_error=False, max_retries=3):
        if path not in GATED_PATHS:
            return await original_request_json(
                self,
                path,
                params,
                suppress_error=suppress_error,
                max_retries=max_retries,
            )
        last_error = None
        for attempt in range(max(1, min(int(max_retries or 1), 3))):
            try:
                return await bridge_request(url, token, path, params)
            except PageBridgeError as exc:
                last_error = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(attempt + 1)
        raise last_error or PageBridgeError("应用内抖音请求失败")

    DouyinAPIClient._request_json = patched_request_json
