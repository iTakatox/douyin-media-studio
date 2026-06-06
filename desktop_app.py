import socket
import threading
import time

import webview
from werkzeug.serving import make_server

from app import app


HOST = "127.0.0.1"
PORT = 5055
URL = f"http://{HOST}:{PORT}"


class ServerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.server = make_server(HOST, PORT, app)
        self.context = app.app_context()
        self.context.push()

    def run(self):
        self.server.serve_forever()

    def shutdown(self):
        self.server.shutdown()


def wait_for_server(timeout_seconds=8):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection((HOST, PORT), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.15)
    return False


if __name__ == "__main__":
    server = ServerThread()
    server.start()
    wait_for_server()
    window = webview.create_window(
        "Douyin Media Studio",
        URL,
        width=1180,
        height=820,
        min_size=(980, 680),
    )
    try:
        webview.start()
    finally:
        server.shutdown()
