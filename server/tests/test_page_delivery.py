"""真实 HTTP 检查页面资源是否齐，以及无脚本时登录会不会把口令送进地址。

这里的口令只在进程里临时生成。失败时只报告“口令出现在哪里”，不把口令写进断言文本。
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import replace
from html.parser import HTMLParser
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tests.conftest import apply_env


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict] = []
        self.current: dict | None = None
        self._noscript = False
        self.noscript: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key: value for key, value in attrs}
        if tag == "form":
            self.current = {
                "id": data.get("id", ""),
                "method": (data.get("method") or "get").lower(),
                "action": data.get("action") or "",
                "controls": [],
            }
            self.forms.append(self.current)
        elif self.current is not None and tag in {"input", "button", "textarea"}:
            self.current["controls"].append(
                {
                    "tag": tag,
                    "id": data.get("id", ""),
                    "name": data.get("name"),
                    "type": data.get("type") or ("submit" if tag == "button" else "text"),
                    "disabled": "disabled" in data,
                }
            )
        elif tag == "noscript":
            self._noscript = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.current = None
        elif tag == "noscript":
            self._noscript = False

    def handle_data(self, data: str) -> None:
        if self._noscript and data.strip():
            self.noscript.append(data.strip())


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_health(port: int) -> None:
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/api/health")
            response = conn.getresponse()
            response.read()
            conn.close()
            if response.status == 200:
                return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("server did not start")


def _request(port: int, method: str, target: str, body: bytes | None = None, headers: dict | None = None):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, target, body=body, headers=headers or {})
    response = conn.getresponse()
    payload = response.read()
    status = response.status
    ctype = response.getheader("Content-Type")
    conn.close()
    return status, ctype, payload


def test_missing_page_assets_refuse_startup(tmp_path, monkeypatch):
    apply_env(monkeypatch, tmp_path)
    from zhixu_server.config import load_settings
    from zhixu_server.main import create_app

    empty = tmp_path / "empty-web"
    empty.mkdir()
    settings = replace(load_settings(), web_dir=empty)
    with pytest.raises(RuntimeError, match="页面资源缺失"):
        create_app(settings)


# 公开标记，不是口令。用来观察它会不会出现在地址或访问日志里。
MARKER = "NOSSECRET-MARKER"


def test_real_http_serves_page_assets_and_login_does_not_use_url(tmp_path, monkeypatch):
    apply_env(monkeypatch, tmp_path)
    from zhixu_server.api import WEB_ASSETS
    from zhixu_server.config import load_settings

    web = load_settings().web_dir
    app_js = (web / "app.js").read_text(encoding="utf-8")
    html = (web / "index.html").read_text(encoding="utf-8")
    imports = re.findall(r"""from ["']\./([^"']+)["']""", app_js)
    assert imports, "app.js 没有模块导入，检查无法代表页面"
    missing = sorted(set(imports) - set(WEB_ASSETS))
    assert missing == [], missing
    for ref in re.findall(r"""(?:src|href)=["'](/[^"']+)["']""", html):
        name = ref.split("?", 1)[0].lstrip("/")
        if not name or name.startswith("prototype-snapshot/"):
            continue
        assert name in WEB_ASSETS, name

    port = _free_port()
    log_path = tmp_path / "access.log"
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"plain": {"format": "%(message)s"}},
        "handlers": {"file": {"class": "logging.FileHandler", "formatter": "plain", "filename": str(log_path)}},
        "loggers": {
            "uvicorn.access": {"handlers": ["file"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["file"], "level": "INFO", "propagate": False},
        },
    }
    config_path = tmp_path / "log.json"
    config_path.write_text(json.dumps(log_config), encoding="utf-8")
    env = os.environ.copy()
    # 子进程沿用当前解释器能导入的路径，不另装依赖。
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "zhixu_server.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-config",
            str(config_path),
        ],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_health(port)
        seen = []
        for name, media in WEB_ASSETS.items():
            target = "/" if name == "index.html" else "/" + name
            status, ctype, payload = _request(port, "GET", target)
            seen.append((name, status, ctype, len(payload)))
            assert status == 200, name
            assert ctype is not None and ctype.split(";")[0] == media.split(";")[0], (name, ctype)
            if name == "index.html":
                assert b'id="auth-form"' in payload
            if name.endswith(".js") and name != "index.html":
                assert payload.startswith(b"import") or b"function" in payload or b"export" in payload
        assert len(seen) == len(WEB_ASSETS)

        for extra in ("phase_b.test.js", "phase_c.test.js", "input_rules.test.js", "package.json"):
            status, _ctype, _payload = _request(port, "GET", "/" + extra)
            assert status == 404, extra

        for blocked in (
            "/../server/zhixu_server/config.py",
            "/%2e%2e/server/zhixu_server/config.py",
            "/app.js%2f%2e%2e%2fserver%2fzhixu_server%2fconfig.py",
        ):
            status, _ctype, payload = _request(port, "GET", blocked)
            assert status == 404, blocked
            assert b"model_api_key" not in payload

        status, ctype, payload = _request(port, "GET", "/prototype-snapshot/app.js")
        assert status == 200 and ctype and ctype.startswith("text/javascript")
        status, _ctype, payload = _request(port, "GET", "/prototype-snapshot/markdown.js")
        assert status == 404
        assert b"parseMarkdown" not in payload

        status, _ctype, page = _request(port, "GET", "/")
        assert status == 200
        parser = _PageParser()
        parser.feed(page.decode())
        form = next(item for item in parser.forms if item["id"] == "auth-form")
        assert form["method"] == "post"
        action = urlsplit(form["action"] or "/")
        assert action.query == ""
        assert action.scheme == "" and action.netloc == ""
        password = next(item for item in form["controls"] if item["id"] == "password")
        username = next(item for item in form["controls"] if item["id"] == "username")
        login = next(item for item in form["controls"] if item["id"] == "login")
        assert password["name"] is None
        assert username["name"] is None
        assert login["disabled"] is True
        assert any("口令不会提交" in item for item in parser.noscript)

        # 无脚本时只提交带 name 且未禁用的控件。修复后没有这样的控件，标记不会进入请求。
        successful = [item for item in form["controls"] if item.get("name") and not item["disabled"]]
        assert successful == []
        target = form["action"] or "/"
        status, _ctype, body = _request(port, form["method"].upper(), target)
        assert status == 405
        assert MARKER not in target
        assert MARKER.encode() not in body
        time.sleep(0.3)
        access = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        app_log = Path(os.environ["ZHIXU_DATA_DIR"]) / "logs" / "zhixu.log"
        app_text = app_log.read_text(encoding="utf-8", errors="replace") if app_log.exists() else ""
        assert MARKER not in access
        assert MARKER not in app_text
        assert "GET /?" not in access
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
