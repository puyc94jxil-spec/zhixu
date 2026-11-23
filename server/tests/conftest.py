"""DEV 自测公共夹具。FIXTURE_NOT_REAL_QWEN：不是真实模型联调。"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient


class FixtureUpstream:
    """本地协议夹具。不得把这里的成功写成真实 Qwen 通过。"""

    def __init__(self, chunks: list[str] | None = None, mode: str = "sse", status: int = 200):
        self.chunks = chunks or ["夹具回答"]
        self.mode = mode
        self.status = status
        self.calls = 0
        self.bodies: list[dict] = []
        state = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):
                return

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                state.calls += 1
                state.bodies.append(json.loads(raw.decode()))
                if state.mode == "status":
                    body = b"{}"
                    self.send_response(state.status)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                if state.mode == "silent":
                    time.sleep(2)
                    return
                for chunk in state.chunks:
                    payload = json.dumps({"choices": [{"delta": {"content": chunk}}]}, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        port = self.httpd.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}/v1"

    def close(self):
        self.httpd.shutdown()


def apply_env(monkeypatch, tmp_path, **extra):
    monkeypatch.setenv("ZHIXU_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ZHIXU_ALLOWED_ORIGINS", "http://test.example")
    monkeypatch.setenv("ZHIXU_COOKIE_SECURE", "0")
    monkeypatch.setenv("ZHIXU_UPSTREAM_MODE", "unconfigured")
    monkeypatch.setenv("ZHIXU_MODEL_BASE_URL", "")
    monkeypatch.setenv("ZHIXU_MODEL_NAME", "")
    monkeypatch.setenv("ZHIXU_MODEL_API_KEY", "")
    monkeypatch.setenv("ZHIXU_UPSTREAM_RETRY_DELAYS", "0,0")
    monkeypatch.setenv("ZHIXU_UPSTREAM_CONNECT_TIMEOUT", "1")
    monkeypatch.setenv("ZHIXU_UPSTREAM_FIRST_BYTE_TIMEOUT", "1")
    monkeypatch.setenv("ZHIXU_UPSTREAM_TOTAL_TIMEOUT", "5")
    monkeypatch.setenv("ZHIXU_FIXTURE_HOLD", "0")
    for key, value in extra.items():
        monkeypatch.setenv(key, value)


def make_client(tmp_path, monkeypatch, **extra):
    apply_env(monkeypatch, tmp_path, **extra)
    from zhixu_server.config import load_settings
    from zhixu_server.main import create_app

    settings = load_settings()
    app = create_app(settings)
    client = TestClient(app)
    client.headers.update({"Origin": "http://test.example"})
    return client, settings


def login(client: TestClient, username: str, password: str) -> None:
    response = client.post("/api/auth/register", json={"username": username, "password": password})
    assert response.status_code == 201, response.text
    client.headers["X-CSRF-Token"] = client.cookies.get("zhixu_csrf")


def wait_file(client: TestClient, file_id: str) -> dict:
    last = {}
    for _ in range(80):
        last = client.get(f"/api/files/{file_id}/status").json()
        if last.get("status") in {"ready", "failed"}:
            return last
        time.sleep(0.1)
    raise AssertionError(last)


def wait_terminal(settings, request_id: str) -> None:
    import sqlite3

    for _ in range(80):
        conn = sqlite3.connect(settings.db_path)
        row = conn.execute("SELECT finalized FROM requests WHERE id = ?", (request_id,)).fetchone()
        conn.close()
        if row and row[0]:
            return
        time.sleep(0.1)
    raise AssertionError("generation did not finish")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    yield client
    client.close()
