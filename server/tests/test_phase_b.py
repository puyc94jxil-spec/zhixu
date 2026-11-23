"""B 期 DEV 自测。协议夹具和这些断言都不是 TEST 签收，也不是真实模型通过。"""

from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from docx import Document
from pypdf import PdfWriter

from tests.conftest import FixtureUpstream, login, make_client, wait_file, wait_terminal
from tests.test_phase_a import PASSWORD


def _pdf_bytes(pages: int, encrypt: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if encrypt:
        writer.encrypt(encrypt)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _text_pdf() -> bytes:
    content = b"BT /F1 18 Tf 36 120 Td (Budget 1200) Tj ET"
    stream = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content)
    objects = [
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n",
        b"2 0 obj<< /Type /Pages /Count 1 /Kids [3 0 R] >>endobj\n",
        (
            b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>endobj\n"
        ),
        b"4 0 obj" + stream + b"endobj\n",
        b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n",
    ]
    body = b"".join(objects)
    return b"%PDF-1.4\n" + body + b"trailer<< /Root 1 0 R >>\nstartxref\n0\n%%EOF"


def _docx_bytes() -> bytes:
    document = Document()
    document.add_paragraph("本季活动预算金额为 1200 元。")
    document.add_paragraph("地点在市民图书馆。")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_pdf_and_docx_location_and_independent_failure(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    login(client, "pdf_user", PASSWORD)
    conv = client.post("/api/conversations", json={}).json()["id"]
    uploaded = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("预算.pdf", _text_pdf(), "application/pdf")},
    )
    assert uploaded.status_code == 202
    ready = wait_file(client, uploaded.json()["file_id"])
    assert ready["status"] == "ready", ready
    assert ready["page_count"] == 1
    preview = client.get(
        "/api/files/" + uploaded.json()["file_id"] + "/preview",
        params={"version": 1, "page": 1},
    )
    assert preview.status_code == 200
    assert "1200" in preview.json()["content"]
    docx = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={
            "file": (
                "预算.docx",
                _docx_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert wait_file(client, docx.json()["file_id"])["status"] == "ready"
    detail = client.get("/api/conversations/" + conv).json()
    docx_row = [item for item in detail["files"] if item["name"].endswith(".docx")][0]
    assert docx_row["parse_notice"] == "page_unavailable"
    broken = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("坏.pdf", b"%PDF-1.4\nnot-a-pdf", "application/pdf")},
    )
    failed = wait_file(client, broken.json()["file_id"])
    assert failed["status"] == "failed"
    assert failed["error_code"] in {"corrupt", "no_text"}
    still = client.get("/api/files/" + uploaded.json()["file_id"] + "/status").json()
    assert still["status"] == "ready"
    client.close()


def test_pdf_error_classes_and_dedup(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    login(client, "pdf_err", PASSWORD)
    conv = client.post("/api/conversations", json={}).json()["id"]
    scanned = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("扫描.pdf", _pdf_bytes(1), "application/pdf")},
    )
    scanned_status = wait_file(client, scanned.json()["file_id"])
    assert scanned_status["error_code"] == "no_text"
    assert "可提取文字" in scanned_status["error_message"]
    encrypted = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("加密.pdf", _pdf_bytes(1, "secret-pass"), "application/pdf")},
    )
    assert wait_file(client, encrypted.json()["file_id"])["error_code"] == "encrypted"
    many = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("太长.pdf", _pdf_bytes(201), "application/pdf")},
    )
    assert wait_file(client, many.json()["file_id"])["error_code"] == "too_many_pages"
    mismatch = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("伪装.pdf", "这不是 pdf".encode(), "application/pdf")},
    )
    assert mismatch.status_code == 415
    text = "预算金额为 880 元。".encode()
    first = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("金额.txt", text, "text/plain")},
    )
    assert wait_file(client, first.json()["file_id"])["status"] == "ready"
    second = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("金额.txt", text, "text/plain")},
        headers={"Idempotency-Key": "same-bytes"},
    )
    assert second.status_code == 200
    assert second.json()["reused"] is True
    again = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("金额.txt", text, "text/plain")},
        headers={"Idempotency-Key": "same-bytes"},
    )
    assert again.json()["file_id"] == second.json()["file_id"]
    client.close()


def test_dependency_failure_is_closed(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    monkeypatch.setattr("zhixu_server.sandbox.parser_dependency_ready", lambda kind: False)
    login(client, "dep_user", PASSWORD)
    conv = client.post("/api/conversations", json={}).json()["id"]
    uploaded = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("a.pdf", _pdf_bytes(1), "application/pdf")},
    )
    status = wait_file(client, uploaded.json()["file_id"])
    assert status["error_code"] == "dependency_unavailable"
    conn = sqlite3.connect(settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 0
    conn.close()
    client.close()


def test_feedback_account_delete_and_second_client(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    other, _other_settings = make_client(tmp_path, monkeypatch)
    login(client, "sync_user", PASSWORD)
    logged = other.post("/api/auth/login", json={"username": "sync_user", "password": PASSWORD})
    assert logged.status_code == 200
    other.headers["X-CSRF-Token"] = other.cookies.get("zhixu_csrf")
    conv = client.post("/api/conversations", json={"title": "可搜索标题甲"}).json()["id"]
    renamed = client.patch("/api/conversations/" + conv, json={"title": "预算讨论"})
    assert renamed.status_code == 200
    found = other.get("/api/conversations", params={"q": "预算"}).json()
    assert [item["id"] for item in found["items"]] == [conv]
    sent = client.post("/api/conversations/" + conv + "/messages", json={"content": "普通问题"})
    wait_terminal(settings, sent.json()["request_id"])
    detail = client.get("/api/conversations/" + conv).json()
    message_id = [item["id"] for item in detail["messages"] if item["role"] == "assistant"][-1]
    secret_note = "反馈说明甲乙丙不要进日志"
    saved = client.post(
        "/api/messages/" + message_id + "/feedback",
        json={"reason": "citation", "note": secret_note},
    )
    assert saved.status_code == 201
    assert secret_note not in settings.log_path.read_text(encoding="utf-8")
    stranger, _stranger_settings = make_client(tmp_path, monkeypatch)
    login(stranger, "other_person", PASSWORD)
    assert stranger.post("/api/messages/" + message_id + "/feedback", json={"reason": "other"}).status_code == 403
    uploaded = client.post(
        "/api/files",
        data={"conversation_id": conv},
        files={"file": ("私有.txt", "只属于这个账号的句子。".encode(), "text/plain")},
    )
    file_id = uploaded.json()["file_id"]
    assert wait_file(client, file_id)["status"] == "ready"
    conn = sqlite3.connect(settings.db_path)
    object_key = conn.execute("SELECT object_key FROM files WHERE id = ?", (file_id,)).fetchone()[0]
    conn.close()
    object_path = settings.objects_dir / object_key
    assert object_path.exists()
    deleted = client.delete("/api/auth/me?confirm=true")
    assert deleted.status_code == 204
    assert not object_path.exists()
    assert client.get("/api/conversations").status_code == 401
    assert other.get("/api/conversations").status_code == 401
    client.close()
    other.close()
    stranger.close()


def test_completed_sse_does_not_keep_deleted_quote(tmp_path, monkeypatch):
    upstream = FixtureUpstream(chunks=["临时"])
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
    )
    try:
        login(client, "sse_user", PASSWORD)
        conv = client.post("/api/conversations", json={}).json()["id"]
        text = Path(__file__).resolve().parents[1].joinpath("fixtures/zh_has_answer.txt").read_bytes()
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
        upstream.chunks = [
            "预算是 1200 元。\n<<<CLAIMS>>>\n"
            f"claim_id: c1\ntext: 预算是 1200 元\nchunk_id: {chunk_id}\nquote: 预算金额为 1200 元\n---\n"
        ]
        sent = client.post("/api/conversations/" + conv + "/messages", json={"content": "文中的 1200 指什么"})
        request_id = sent.json()["request_id"]
        wait_terminal(settings, request_id)
        deleted = client.delete(f"/api/files/{file_id}?confirm=true")
        assert deleted.status_code == 204
        events = client.get(f"/api/requests/{request_id}/events").text
        assert "预算金额为 1200 元" not in events
        assert "1200" not in events
        detail = client.get("/api/conversations/" + conv).json()
        assistant = [item for item in detail["messages"] if item["role"] == "assistant"][-1]
        assert "1200" not in assistant["content"]
    finally:
        client.close()
        upstream.close()


def test_context_summary_keeps_attachment_ids(tmp_path, monkeypatch):
    monkeypatch.setattr("zhixu_server.generate._PROMPT_LIMIT", 120)
    upstream = FixtureUpstream(chunks=["普通回答"])
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
    )
    try:
        login(client, "summary_user", PASSWORD)
        conv = client.post("/api/conversations", json={}).json()["id"]
        uploaded = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("短.txt", "预算金额为 1200 元。".encode(), "text/plain")},
        )
        file_id = uploaded.json()["file_id"]
        assert wait_file(client, file_id)["status"] == "ready"
        conn = sqlite3.connect(settings.db_path)
        owner = conn.execute("SELECT owner_user_id FROM files WHERE id = ?", (file_id,)).fetchone()[0]
        stamp = "2026-11-23T00:00:00+00:00"
        for index in range(3):
            conn.execute(
                """
                INSERT INTO messages(
                    id, conversation_id, owner_user_id, role, content, status, model, request_id,
                    version, user_message_id, withdrawn_reason, material, created_at
                ) VALUES (?, ?, ?, 'user', ?, 'completed', NULL, NULL, 1, NULL, NULL, 0, ?)
                """,
                (f"old-{index}", conv, owner, "旧问题" * 30, stamp),
            )
        conn.close()
        sent = client.post("/api/conversations/" + conv + "/messages", json={"content": "还看得到附件吗"})
        wait_terminal(settings, sent.json()["request_id"])
        conn = sqlite3.connect(settings.db_path)
        bound = conn.execute("SELECT strategy, attachment_ids FROM context_bounds").fetchone()
        enabled = conn.execute(
            "SELECT enabled FROM conversation_files WHERE file_id = ?",
            (file_id,),
        ).fetchone()[0]
        conn.close()
        assert bound is not None
        assert file_id in bound[1]
        assert enabled == 1
        events = client.get("/api/requests/" + sent.json()["request_id"] + "/events").text
        if "context_too_large" in events:
            assert file_id in events
    finally:
        client.close()
        upstream.close()


def test_backup_purge_removes_only_expired_snapshots(tmp_path):
    from zhixu_server.backup import purge_expired_backups

    root = tmp_path / "backups"
    old = root / "old"
    fresh = root / "fresh"
    for folder, days in ((old, 31), (fresh, 1)):
        folder.mkdir(parents=True)
        created = datetime.now(timezone.utc) - timedelta(days=days)
        (folder / "zhixu-backup.json").write_text(
            json.dumps({"created_at": created.isoformat()}),
            encoding="utf-8",
        )
        (folder / "secret.txt").write_text("不要留过期副本", encoding="utf-8")
    data = tmp_path / "live"
    data.mkdir()
    (data / "ZHIXU_DATA_MARKER").write_text("zhixu-data\n", encoding="utf-8")
    raised = False
    try:
        purge_expired_backups(data, 30)
    except RuntimeError:
        raised = True
    assert raised
    result = purge_expired_backups(root, 30)
    assert result["removed"] == 1
    assert result["kept"] == 1
    assert not old.exists()
    assert fresh.exists()
