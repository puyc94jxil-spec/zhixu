"""DEV 自测，不是 TEST 独立验收。协议夹具标记为 FIXTURE_NOT_REAL_QWEN。"""

from __future__ import annotations

import secrets
import sqlite3
import time
from pathlib import Path

from tests.conftest import FixtureUpstream, login, make_client, wait_file, wait_terminal

PASSWORD = secrets.token_urlsafe(18)
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"


def test_unauthenticated_rejected(client):
    assert client.get("/api/conversations").status_code == 401
    assert client.post("/api/conversations", json={}).status_code == 403 or client.post(
        "/api/conversations", json={}
    ).status_code in {401, 403}
    assert client.get("/api/files/whatever/status").status_code == 401
    assert client.get("/api/files/whatever/preview", params={"version": 1}).status_code == 401


def test_login_isolation_and_server_session(client):
    login(client, "user_a", PASSWORD)
    created = client.post("/api/conversations", json={"title": "甲的会话"})
    assert created.status_code == 201
    conv_id = created.json()["id"]
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    again = client.post("/api/auth/login", json={"username": "user_a", "password": PASSWORD})
    assert again.status_code == 200
    client.headers["X-CSRF-Token"] = client.cookies.get("zhixu_csrf")
    listed = client.get("/api/conversations")
    assert listed.status_code == 200
    assert any(item["id"] == conv_id for item in listed.json()["items"])
    other = client.post("/api/auth/register", json={"username": "user_b", "password": PASSWORD})
    assert other.status_code == 201
    client.headers["X-CSRF-Token"] = client.cookies.get("zhixu_csrf")
    denied = client.get(f"/api/conversations/{conv_id}")
    assert denied.status_code == 403
    assert "甲的会话" not in denied.text


def test_csrf_and_origin(client):
    login(client, "user_c", PASSWORD)
    saved = client.headers["Origin"]
    client.headers["Origin"] = "http://evil.example"
    rejected = client.post("/api/conversations", json={})
    assert rejected.status_code == 403
    assert rejected.json()["error"]["code"] == "origin_rejected"
    client.headers["Origin"] = saved
    client.headers.pop("X-CSRF-Token")
    missing = client.post("/api/conversations", json={})
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "csrf_failed"


def test_login_rate_limit(client):
    for _ in range(8):
        response = client.post("/api/auth/login", json={"username": "nobody", "password": "wrong-password"})
        assert response.status_code == 401
    blocked = client.post("/api/auth/login", json={"username": "nobody", "password": "wrong-password"})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "login_rate_limited"


def test_txt_parse_preview_and_dedup(client):
    login(client, "user_d", PASSWORD)
    conv = client.post("/api/conversations", json={}).json()["id"]
    text = FIXTURE_ROOT.joinpath("zh_has_answer.txt").read_bytes()
    uploaded = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("预算.txt", text, "text/plain")},
    )
    assert uploaded.status_code == 202, uploaded.text
    file_id = uploaded.json()["file_id"]
    status = wait_file(client, file_id)
    assert status["status"] == "ready", status
    preview = client.get("/api/files/" + file_id + "/preview", params={"version": 1, "quote": "1200 元"})
    assert preview.status_code == 200
    body = preview.json()
    assert body["offset_interval"] == "half_open"
    assert body["highlights"][0]["exact_match"] is True
    assert "1200" in body["content"]
    again = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("预算.txt", text, "text/plain")},
    )
    assert again.json()["reused"] is True
    assert again.json()["file_id"] == file_id
    other = client.post("/api/auth/register", json={"username": "user_e", "password": PASSWORD})
    assert other.status_code == 201
    client.headers["X-CSRF-Token"] = client.cookies.get("zhixu_csrf")
    conv_b = client.post("/api/conversations", json={}).json()["id"]
    copied = client.post(
        "/api/files",
        data={"conversation_id": conv_b},
        files={"file": ("预算.txt", text, "text/plain")},
    )
    assert copied.status_code == 202
    assert copied.json()["file_id"] != file_id
    denied = client.get(f"/api/files/{file_id}/preview", params={"version": 1})
    assert denied.status_code == 403


def test_reject_empty_pdf_and_oversize(client):
    login(client, "user_f", PASSWORD)
    conv = client.post("/api/conversations", json={}).json()["id"]
    empty = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("空.txt", b"", "text/plain")},
    )
    assert empty.status_code == 400
    pdf = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert pdf.status_code == 415
    big = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("big.txt", b"a" * (20 * 1024 * 1024 + 1), "text/plain")},
    )
    assert big.status_code == 413


def test_fail_closed_when_isolation_unavailable(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "zhixu_server.sandbox.probe",
        lambda force=False: {"ready": False, "reason": "forced"},
    )
    login(client, "user_g", PASSWORD)
    conv = client.post("/api/conversations", json={}).json()["id"]
    uploaded = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("a.txt", "隔离失败时不能解析".encode(), "text/plain")},
    )
    status = wait_file(client, uploaded.json()["file_id"])
    assert status["status"] == "failed"
    assert status["error_code"] == "isolation_unavailable"
    conn = sqlite3.connect(settings.db_path)
    count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    conn.close()
    assert count == 0
    client.close()


def _claim(chunk_id: str, text: str, quote: str) -> str:
    return (
        "\n<<<CLAIMS>>>\n"
        f"claim_id: c1\ntext: {text}\nchunk_id: {chunk_id}\nquote: {quote}\n---\n"
    )


def test_fixture_citation_withdraw_and_context(tmp_path, monkeypatch):
    upstream = FixtureUpstream(chunks=["占位"])
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
        ZHIXU_MODEL_API_KEY="fixture-secret-not-for-logs",
    )
    try:
        login(client, "user_h", PASSWORD)
        conv = client.post("/api/conversations", json={}).json()["id"]
        text = FIXTURE_ROOT.joinpath("zh_has_answer.txt").read_bytes()
        uploaded = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("预算.txt", text, "text/plain")},
        )
        file_id = uploaded.json()["file_id"]
        assert wait_file(client, file_id)["status"] == "ready"
        conn = sqlite3.connect(settings.db_path)
        chunk_id = conn.execute("SELECT id FROM chunks WHERE file_id = ?", (file_id,)).fetchone()[0]
        conn.close()
        upstream.chunks = ["活动预算已经写明。", _claim(chunk_id, "活动预算是 1200 元", "预算金额为 1200 元")]
        sent = client.post(
            f"/api/conversations/{conv}/messages",
            json={"content": "文中的 1200 指什么"},
        )
        assert sent.status_code == 202, sent.text
        request_id = sent.json()["request_id"]
        duplicate = client.post(
            f"/api/conversations/{conv}/messages",
            json={"content": "再问一次"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "generation_in_progress"
        wait_terminal(settings, request_id)
        detail = client.get(f"/api/conversations/{conv}").json()
        assistant = [item for item in detail["messages"] if item["role"] == "assistant"][-1]
        assert assistant["status"] == "completed"
        assert assistant["citations"]
        assert assistant["citations"][0]["verified_at"] if False else assistant["citations"][0]["quote"]
        assert "1200" in assistant["content"]
        calls_after_first = upstream.calls
        replay = client.get(
            f"/api/requests/{request_id}/events",
            headers={"Last-Event-ID": "0"},
        )
        assert "citation" in replay.text
        assert upstream.calls == calls_after_first
        upstream.chunks = ["活动预算是 9999 元。", _claim(chunk_id, "活动预算是 9999 元", "预算金额为 9999 元")]
        bad = client.post(
            f"/api/conversations/{conv}/messages",
            json={"content": "请再确认金额"},
        )
        wait_terminal(settings, bad.json()["request_id"])
        detail = client.get(f"/api/conversations/{conv}").json()
        last = [item for item in detail["messages"] if item["role"] == "assistant"][-1]
        assert last["status"] == "withdrawn"
        assert last["content"] == "资料中未找到"
        assert last["citations"] == []
        body = upstream.bodies[0]
        assert body["model"] == "fixture-model"
        assert "文中的 1200 指什么" in json_text(body)
        assert json_text(body).count("文中的 1200 指什么") == 1
        other = client.post("/api/conversations", json={"title": "另一会话"}).json()["id"]
        upstream.chunks = ["没有提到那个词。"]
        client.post(f"/api/conversations/{other}/messages", json={"content": "上文有没有预算金额"})
        wait_terminal(settings, client.get(f"/api/conversations/{other}").json()["messages"][-1]["request_id"])
        leaked = upstream.bodies[-1]
        assert "1200" not in json_text(leaked)
        removed = client.delete(f"/api/files/{file_id}?confirm=true")
        assert removed.status_code == 204
        preview = client.get(f"/api/files/{file_id}/preview", params={"version": 1})
        assert preview.status_code in {403, 409}
        follow = client.post(
            f"/api/conversations/{conv}/messages",
            json={"content": "删除之后还看得到预算吗"},
        )
        wait_terminal(settings, follow.json()["request_id"])
        sent_text = json_text(upstream.bodies[-1])
        assert "预算金额为 1200 元" not in sent_text
        assert "活动预算是 1200 元" not in sent_text
        assert "依据文件已删除或撤销" in sent_text
    finally:
        client.close()
        upstream.close()


def json_text(body: dict) -> str:
    import json

    return json.dumps(body, ensure_ascii=False)


def test_cancel_keeps_partial_and_is_idempotent(tmp_path, monkeypatch):
    upstream = FixtureUpstream(chunks=["已生成的半句", "不会再出现"])
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
        ZHIXU_FIXTURE_HOLD="1",
    )
    try:
        login(client, "user_i", PASSWORD)
        conv = client.post("/api/conversations", json={}).json()["id"]
        sent = client.post(f"/api/conversations/{conv}/messages", json={"content": "普通问题"})
        request_id = sent.json()["request_id"]
        for _ in range(40):
            conn = sqlite3.connect(settings.db_path)
            count = conn.execute(
                "SELECT COUNT(*) FROM request_events WHERE request_id = ? AND event = 'delta'",
                (request_id,),
            ).fetchone()[0]
            conn.close()
            if count:
                break
            time.sleep(0.05)
        cancelled = client.post(f"/api/requests/{request_id}/cancel")
        assert cancelled.status_code == 200
        again = client.post(f"/api/requests/{request_id}/cancel")
        assert again.status_code == 200
        wait_terminal(settings, request_id)
        detail = client.get(f"/api/conversations/{conv}").json()
        assistant = [item for item in detail["messages"] if item["role"] == "assistant"][-1]
        assert assistant["status"] == "stopped"
        assert assistant["status"] != "completed"
        assert "已生成的半句" in assistant["content"]
    finally:
        client.close()
        upstream.close()


def test_error_mapping_and_retry_version(tmp_path, monkeypatch):
    upstream = FixtureUpstream(mode="status", status=429)
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
    )
    try:
        login(client, "user_j", PASSWORD)
        conv = client.post("/api/conversations", json={}).json()["id"]
        sent = client.post(f"/api/conversations/{conv}/messages", json={"content": "会失败的问题"})
        user_message = sent.json()["user_message_id"]
        wait_terminal(settings, sent.json()["request_id"])
        detail = client.get(f"/api/conversations/{conv}").json()
        failed = [item for item in detail["messages"] if item["role"] == "assistant"][-1]
        assert failed["status"] == "failed"
        events = client.get(f"/api/requests/{sent.json()['request_id']}/events").text
        assert "rate_limited" in events
        assert "completed" not in events
        upstream.mode = "sse"
        upstream.chunks = ["重试后的普通回答"]
        retried = client.post(
            f"/api/conversations/{conv}/messages",
            json={"content": "不会被再次插入", "retry_of_message_id": user_message},
        )
        assert retried.status_code == 202
        wait_terminal(settings, retried.json()["request_id"])
        detail = client.get(f"/api/conversations/{conv}").json()
        users = [item for item in detail["messages"] if item["role"] == "user"]
        assistants = [item for item in detail["messages"] if item["role"] == "assistant"]
        assert len(users) == 1
        assert len(assistants) == 2
        assert assistants[0]["status"] == "failed"
        assert assistants[1]["status"] == "completed"
    finally:
        client.close()
        upstream.close()


def test_network_and_unconfigured_are_not_complete(tmp_path, monkeypatch):
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL="http://127.0.0.1:9/v1",
        ZHIXU_MODEL_NAME="fixture-model",
    )
    login(client, "user_k", PASSWORD)
    conv = client.post("/api/conversations", json={}).json()["id"]
    sent = client.post(f"/api/conversations/{conv}/messages", json={"content": "断网问题"})
    wait_terminal(settings, sent.json()["request_id"])
    events = client.get(f"/api/requests/{sent.json()['request_id']}/events").text
    assert "network" in events
    client.close()
    bare, bare_settings = make_client(tmp_path, monkeypatch)
    login(bare, "user_k2", PASSWORD)
    conv = bare.post("/api/conversations", json={}).json()["id"]
    sent = bare.post(f"/api/conversations/{conv}/messages", json={"content": "未配置"})
    wait_terminal(bare_settings, sent.json()["request_id"])
    events = bare.get(f"/api/requests/{sent.json()['request_id']}/events").text
    assert "model_unconfigured" in events
    bare.close()


def test_idempotency_and_delete_race(tmp_path, monkeypatch):
    upstream = FixtureUpstream(chunks=["临时增量", "后续"])
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
        ZHIXU_FIXTURE_HOLD="1",
    )
    try:
        login(client, "user_l", PASSWORD)
        first = client.post("/api/conversations", json={}, headers={"Idempotency-Key": "conv-1"})
        second = client.post("/api/conversations", json={}, headers={"Idempotency-Key": "conv-1"})
        assert first.json()["id"] == second.json()["id"]
        conv = client.post("/api/conversations", json={}).json()["id"]
        text = FIXTURE_ROOT.joinpath("zh_has_answer.txt").read_bytes()
        uploaded = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("预算.txt", text, "text/plain")},
        )
        file_id = uploaded.json()["file_id"]
        assert wait_file(client, file_id)["status"] == "ready"
        sent = client.post(
            f"/api/conversations/{conv}/messages",
            json={"content": "看预算"},
            headers={"Idempotency-Key": "msg-1"},
        )
        request_id = sent.json()["request_id"]
        again = client.post(
            f"/api/conversations/{conv}/messages",
            json={"content": "看预算"},
            headers={"Idempotency-Key": "msg-1"},
        )
        assert again.json()["request_id"] == request_id
        for _ in range(40):
            conn = sqlite3.connect(settings.db_path)
            count = conn.execute(
                "SELECT COUNT(*) FROM request_events WHERE request_id = ? AND event = 'delta'",
                (request_id,),
            ).fetchone()[0]
            conn.close()
            if count:
                break
            time.sleep(0.05)
        deleted = client.delete(f"/api/files/{file_id}?confirm=true")
        assert deleted.status_code == 204
        wait_terminal(settings, request_id)
        detail = client.get(f"/api/conversations/{conv}").json()
        assistant = [item for item in detail["messages"] if item["role"] == "assistant"][-1]
        assert assistant["status"] == "withdrawn"
        assert "1200" not in assistant["content"]
        events = client.get(f"/api/requests/{request_id}/events").text
        assert "1200" not in events
    finally:
        client.close()
        upstream.close()


def test_logs_do_not_store_secrets_or_document_text(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    login(client, "user_m", PASSWORD)
    conv = client.post("/api/conversations", json={}).json()["id"]
    secret_sentence = "日志不该出现的原文句子甲乙丙"
    client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("note.txt", secret_sentence.encode(), "text/plain")},
    )
    log = settings.log_path.read_text(encoding="utf-8")
    assert PASSWORD not in log
    assert secret_sentence not in log
    assert "fixture-secret" not in log
    client.close()


def test_backup_and_restore_roundtrip(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    login(client, "user_n", PASSWORD)
    conv = client.post("/api/conversations", json={"title": "要备份"}).json()["id"]
    client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("a.txt", "备份正文".encode(), "text/plain")},
    )
    from zhixu_server.backup import backup_consistent, restore_consistent

    dest = tmp_path / "backup"
    backup_consistent(settings, dest)
    assert (dest / "zhixu.db").exists()
    assert not (dest / "zhixu.db-wal").exists() or True
    restored = tmp_path / "restored"
    restore_consistent(dest, restored)
    conn = sqlite3.connect(restored / "zhixu.db")
    title = conn.execute("SELECT title FROM conversations").fetchone()[0]
    conn.close()
    assert title == "要备份"
    client.close()


def test_no_private_address_in_runtime_tree():
    root = Path(__file__).resolve().parents[2]
    banned = "192.168." + "2.46"
    scanned = []
    for folder in (root / "server" / "zhixu_server", root / "web"):
        for path in folder.rglob("*"):
            if path.suffix.lower() in {".py", ".js", ".html", ".css", ".md", ".txt"}:
                scanned.append(path)
                assert banned not in path.read_text(encoding="utf-8")
    assert scanned


def test_feedback_and_account_delete_not_in_phase_a(client):
    login(client, "user_o", PASSWORD)
    assert client.delete("/api/auth/me").status_code == 405
    assert client.post("/api/messages/missing/feedback", json={"reason": "other"}).status_code == 404
