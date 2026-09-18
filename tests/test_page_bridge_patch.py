import asyncio
import json
import os
import sys
import threading
import types
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import page_bridge_patch


class _BridgeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        self.server.requests.append(request)
        payload = json.dumps(
            {"status": 200, "text": json.dumps({"aweme_detail": {"aweme_id": "123"}})}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format, *_args):
        pass


class PageBridgePatchTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _BridgeHandler)
        self.server.requests = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.old_url = os.environ.get("DOUYIN_PAGE_BRIDGE_URL")
        self.old_token = os.environ.get("DOUYIN_PAGE_BRIDGE_TOKEN")
        os.environ["DOUYIN_PAGE_BRIDGE_URL"] = f"http://127.0.0.1:{self.server.server_port}/fetch"
        os.environ["DOUYIN_PAGE_BRIDGE_TOKEN"] = "test-token"
        self.old_core = sys.modules.get("core")
        self.old_api = sys.modules.get("core.api_client")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        if self.old_url is None:
            os.environ.pop("DOUYIN_PAGE_BRIDGE_URL", None)
        else:
            os.environ["DOUYIN_PAGE_BRIDGE_URL"] = self.old_url
        if self.old_token is None:
            os.environ.pop("DOUYIN_PAGE_BRIDGE_TOKEN", None)
        else:
            os.environ["DOUYIN_PAGE_BRIDGE_TOKEN"] = self.old_token
        if self.old_core is None:
            sys.modules.pop("core", None)
        else:
            sys.modules["core"] = self.old_core
        if self.old_api is None:
            sys.modules.pop("core.api_client", None)
        else:
            sys.modules["core.api_client"] = self.old_api

    def test_injects_the_official_page_bridge_dependency(self):
        core = types.ModuleType("core")
        api_client = types.ModuleType("core.api_client")

        class Client:
            def __init__(self, cookies, proxy=None, page_bridge=None):
                self.cookies = cookies
                self.proxy = proxy
                self.page_bridge = page_bridge

        api_client.DouyinAPIClient = Client
        sys.modules["core"] = core
        sys.modules["core.api_client"] = api_client
        page_bridge_patch.install()

        async def run():
            client = Client({"ttwid": "test"})
            detail = await client.page_bridge.fetch(
                "/aweme/v1/web/aweme/detail/",
                {"aweme_id": "123"},
            )
            return client, detail

        client, detail = asyncio.run(run())
        self.assertEqual(client.proxy, None)
        self.assertIsInstance(client.page_bridge, page_bridge_patch.LocalPageBridge)
        self.assertEqual(detail.body["aweme_detail"]["aweme_id"], "123")
        self.assertEqual(self.server.requests[0]["path"], "/aweme/v1/web/aweme/detail/")


if __name__ == "__main__":
    unittest.main()
