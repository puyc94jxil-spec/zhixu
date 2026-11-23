#!/usr/bin/env python3
"""内网真实模型验收。

check 只看本机条件，不连接模型。
accept 由内网操作者显式运行，会在 127.0.0.1 上临时启动服务。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MARKER = "ZHIXU-SAMPLE-MARKER"
SAMPLE = "验收样本写明预算金额为 ZHIXU-SAMPLE-MARKER。"


def python_ok() -> dict:
    info = sys.version_info
    return {"version": sys.version.split()[0], "at_least_3_10": (info.major, info.minor) >= (3, 10)}


def check() -> dict:
    lock = ROOT / "server" / "requirements-prod.lock"
    return {
        "action": "check",
        "python": python_ok(),
        "bwrap": shutil.which("bwrap") is not None,
        "prod_lock": str(lock.relative_to(ROOT)),
        "prod_lock_exists": lock.is_file(),
        "model_contacted": False,
        "intranet_acceptance": "pending_user_network",
        "fixture_used": False,
    }


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def call(base: str, method: str, path: str, body: bytes | None, headers: dict, timeout: int = 30):
    req = urllib.request.Request(base + path, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers


def json_call(base: str, method: str, path: str, payload: dict | None, headers: dict, timeout: int = 30):
    data = None if payload is None else json.dumps(payload).encode()
    status, raw, response_headers = call(base, method, path, data, headers, timeout)
    try:
        body = json.loads(raw.decode() or "{}") if raw else {}
    except json.JSONDecodeError:
        body = {}
    return status, body, response_headers


def cookie_header(response_headers) -> tuple[str, str]:
    values = response_headers.get_all("Set-Cookie") or []
    jar = {}
    for item in values:
        pair = item.split(";", 1)[0]
        if "=" in pair:
            key, value = pair.split("=", 1)
            jar[key.strip()] = value.strip()
    cookie = "; ".join(f"{key}={value}" for key, value in jar.items())
    return cookie, jar.get("zhixu_csrf", "")


def read_events(base: str, request_id: str, headers: dict, sink: dict) -> None:
    status, raw, _headers = call(base, "GET", f"/api/requests/{request_id}/events", None, headers, timeout=150)
    text = raw.decode(errors="replace")
    names = []
    terminal = None
    marker_in_delta = False
    citation_count = 0
    for block in text.split("\n\n"):
        name = "message"
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data += line.split(":", 1)[1].strip()
        if not data:
            continue
        names.append(name)
        if name == "delta" and MARKER in data:
            marker_in_delta = True
        if name == "citation":
            citation_count += 1
        if name == "done":
            try:
                terminal = json.loads(data).get("status")
            except json.JSONDecodeError:
                terminal = "unparsed"
    sink.update(
        {
            "status": status,
            "event_names": names,
            "terminal": terminal,
            "marker_in_delta": marker_in_delta,
            "citation_events": citation_count,
        }
    )


def accept() -> dict:
    if os.environ.get("ZHIXU_UPSTREAM_MODE", "live") == "fixture":
        raise SystemExit("拒绝用夹具冒充真实模型")
    url = os.environ.get("ZHIXU_MODEL_BASE_URL", "").strip()
    name = os.environ.get("ZHIXU_MODEL_NAME", "").strip()
    if not url or not name:
        raise SystemExit("缺少 ZHIXU_MODEL_BASE_URL 或 ZHIXU_MODEL_NAME")
    py = python_ok()
    if not py["at_least_3_10"]:
        raise SystemExit("Python 低于 3.10")
    work = Path(tempfile.mkdtemp(prefix="zhixu-qwen-accept-"))
    site = work / "site"
    data = work / "data"
    site.mkdir()
    installer = os.environ.get("ZHIXU_INSTALLER_PIP", f"{sys.executable} -m pip").split()
    subprocess.check_call(
        installer
        + [
            "install",
            "--disable-pip-version-check",
            "--target",
            str(site),
            "-r",
            str(ROOT / "server" / "requirements-prod.lock"),
        ]
    )
    port = free_port()
    origin = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": f"{site}{os.pathsep}{ROOT / 'server'}",
            "ZHIXU_DATA_DIR": str(data),
            "ZHIXU_HOST": "127.0.0.1",
            "ZHIXU_PORT": str(port),
            "ZHIXU_UPSTREAM_MODE": "live",
            "ZHIXU_MODEL_BASE_URL": url,
            "ZHIXU_MODEL_NAME": name,
            "ZHIXU_ALLOWED_ORIGINS": os.environ.get("ZHIXU_ALLOWED_ORIGINS", origin),
        }
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "zhixu_server.main"],
        cwd=ROOT / "server",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    evidence: dict = {
        "action": "accept",
        "python": py,
        "model_name_configured": True,
        "api_key_configured": bool(os.environ.get("ZHIXU_MODEL_API_KEY")),
        "bind": "127.0.0.1",
        "fixture_used": False,
    }
    try:
        deadline = time.time() + 20
        health = None
        while time.time() < deadline:
            try:
                status, payload, _headers = json_call(origin, "GET", "/api/health", None, {})
                health = {"status": status, "upstream_mode": payload.get("upstream_mode"), "model_configured": payload.get("model_configured")}
                if status == 200:
                    break
            except OSError:
                time.sleep(0.2)
        evidence["health"] = health
        headers = {"Origin": origin, "Content-Type": "application/json"}
        password = "accept-" + os.urandom(8).hex()
        accounts = []
        for username in ("accept_a", "accept_b"):
            status, _payload, response_headers = json_call(
                origin,
                "POST",
                "/api/auth/register",
                {"username": username, "password": password},
                headers,
            )
            accounts.append({"username": username, "status": status})
            if username == "accept_a" and status == 201:
                cookie, csrf = cookie_header(response_headers)
                headers["Cookie"] = cookie
                headers["X-CSRF-Token"] = csrf
        evidence["accounts"] = accounts
        status, created, _headers = json_call(origin, "POST", "/api/conversations", {}, headers)
        evidence["conversation_status"] = status
        conversation_id = created.get("id")
        boundary = "zhixuaccept"
        upload = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="conversation_id"\r\n\r\n{conversation_id}\r\n'
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="sample.txt"\r\n'
            f"Content-Type: text/plain\r\n\r\n{SAMPLE}\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        upload_headers = {
            "Origin": origin,
            "Cookie": headers.get("Cookie", ""),
            "X-CSRF-Token": headers.get("X-CSRF-Token", ""),
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        upload_status, upload_raw, _headers = call(origin, "POST", "/api/files", upload, upload_headers)
        uploaded = json.loads(upload_raw.decode() or "{}")
        evidence["upload_status"] = upload_status
        file_id = uploaded.get("file_id")
        for _ in range(40):
            file_status, file_body, _headers = json_call(origin, "GET", f"/api/files/{file_id}/status", None, headers)
            if file_body.get("status") in {"ready", "failed"}:
                evidence["file"] = {"http": file_status, "status": file_body.get("status"), "error_code": file_body.get("error_code")}
                break
            time.sleep(0.4)
        status, sent, _headers = json_call(
            origin,
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            {"content": "样本里的标记原文是什么"},
            headers,
        )
        evidence["send_status"] = status
        finished: dict = {}
        thread = threading.Thread(target=read_events, args=(origin, sent.get("request_id", ""), headers, finished))
        thread.start()
        thread.join(timeout=150)
        evidence["stream"] = finished
        status, second, _headers = json_call(
            origin,
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            {"content": "请再根据样本说一次标记"},
            headers,
        )
        evidence["cancel_send_status"] = status
        cancelled: dict = {}
        thread = threading.Thread(target=read_events, args=(origin, second.get("request_id", ""), headers, cancelled))
        thread.start()
        time.sleep(1.5)
        cancel_status, cancel_body, _headers = json_call(
            origin, "POST", f"/api/requests/{second.get('request_id', '')}/cancel", None, headers
        )
        thread.join(timeout=150)
        evidence["cancel"] = {"http": cancel_status, "terminal": cancelled.get("terminal"), "code": (cancel_body.get("error") or {}).get("code")}
        delete_status, _raw, _headers = call(
            origin, "DELETE", f"/api/files/{file_id}?confirm=true", None, headers
        )
        evidence["delete_status"] = delete_status
        status, follow, _headers = json_call(
            origin,
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            {"content": "删除之后还看得到样本标记吗"},
            headers,
        )
        evidence["follow_status"] = status
        followed: dict = {}
        thread = threading.Thread(target=read_events, args=(origin, follow.get("request_id", ""), headers, followed))
        thread.start()
        thread.join(timeout=150)
        evidence["follow_stream"] = {key: followed.get(key) for key in ("status", "terminal", "marker_in_delta", "event_names")}
        status, detail, _headers = json_call(origin, "GET", f"/api/conversations/{conversation_id}", None, headers)
        assistants = [item for item in detail.get("messages", []) if item.get("role") == "assistant"]
        last = assistants[-1] if assistants else {}
        content = str(last.get("content") or "")
        evidence["history"] = {
            "http": status,
            "status": last.get("status"),
            "content_is_placeholder": "依据文件已删除或撤销" in content,
            "marker_in_content": MARKER in content,
            "citation_count": len(last.get("citations") or []),
        }
        log_path = data / "logs" / "zhixu.log"
        log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
        key = os.environ.get("ZHIXU_MODEL_API_KEY") or ""
        evidence["log"] = {
            "exists": log_path.is_file(),
            "marker_in_log": MARKER in log_text,
            "password_in_log": password in log_text,
            "api_key_in_log": bool(key) and key in log_text,
        }
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        evidence["server_stopped"] = True
    out = Path(os.environ.get("ZHIXU_ACCEPT_OUT", str(work / "evidence.json")))
    out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence["wrote"] = str(out)
    return evidence


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "check"
    if action == "check":
        print(json.dumps(check(), ensure_ascii=False, indent=2))
        return
    if action == "accept":
        print(json.dumps(accept(), ensure_ascii=False, indent=2))
        return
    raise SystemExit("用法: check 或 accept")


if __name__ == "__main__":
    main()
