"""C 期 DEV 安全回归。

FIXTURE_NOT_REAL_QWEN：夹具只覆盖协议、竞态和字面引用守卫。
不得把本文件的通过写成真实 Qwen、语义支撑、真实上游取消或性能验收。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from tests.conftest import FixtureUpstream, login, make_client, wait_file, wait_terminal
from tests.test_phase_a import PASSWORD
from zhixu_server.textutil import NOT_FOUND, PLACEHOLDER

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "zh_budget.pdf"
ANCHOR = "长文检索锚点甲乙丙"


def _statuses(settings, file_id: str) -> list[str]:
    conn = sqlite3.connect(settings.db_path)
    rows = conn.execute(
        "SELECT status FROM file_status_log WHERE file_id = ? ORDER BY id",
        (file_id,),
    ).fetchall()
    conn.close()
    return [row[0] for row in rows]


def _chunk_count(settings, file_id: str) -> int:
    conn = sqlite3.connect(settings.db_path)
    count = conn.execute("SELECT COUNT(*) FROM chunks WHERE file_id = ?", (file_id,)).fetchone()[0]
    conn.close()
    return count


def test_title_search_and_sort(tmp_path, monkeypatch):
    client, _settings = make_client(tmp_path, monkeypatch)
    try:
        login(client, "sort_user", PASSWORD)
        older = client.post("/api/conversations", json={}).json()["id"]
        newer = client.post("/api/conversations", json={}).json()["id"]
        assert client.patch("/api/conversations/" + older, json={"title": "旧预算讨论"}).status_code == 200
        assert client.patch("/api/conversations/" + newer, json={"title": "新活动安排"}).status_code == 200
        listed = client.get("/api/conversations").json()["items"]
        assert [item["id"] for item in listed[:2]] == [newer, older]
        found = client.get("/api/conversations", params={"q": "预算"}).json()["items"]
        assert [item["id"] for item in found] == [older]
        assert client.get("/api/conversations", params={"q": "不存在的标题"}).json()["items"] == []
    finally:
        client.close()


def test_upload_status_restart_idempotency_and_dedup(tmp_path, monkeypatch):
    client, settings = make_client(tmp_path, monkeypatch)
    other, _other_settings = make_client(tmp_path, monkeypatch)
    try:
        login(client, "upload_user", PASSWORD)
        conv = client.post("/api/conversations", json={}).json()["id"]
        payload = "预算金额为 1200 元。".encode()
        first = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("预算.txt", payload, "text/plain")},
            headers={"Idempotency-Key": "same-key"},
        )
        assert first.status_code == 202
        file_id = first.json()["file_id"]
        assert wait_file(client, file_id)["status"] == "ready"
        seen = _statuses(settings, file_id)
        for status in ("uploaded", "scanning", "parsing", "indexing", "ready"):
            assert status in seen
        replay = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("预算.txt", payload, "text/plain")},
            headers={"Idempotency-Key": "same-key"},
        )
        assert replay.status_code == 202
        assert replay.json()["file_id"] == file_id
        conflict = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("预算.txt", b"different", "text/plain")},
            headers={"Idempotency-Key": "same-key"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_conflict"
        reused = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("另一名字.txt", payload, "text/plain")},
        )
        assert reused.status_code == 200
        assert reused.json()["reused"] is True
        assert reused.json()["file_id"] == file_id
        login(other, "upload_other", PASSWORD)
        other_conv = other.post("/api/conversations", json={}).json()["id"]
        copied = other.post(
            "/api/files",
            data={"conversation_id": other_conv},
            files={"file": ("预算.txt", payload, "text/plain")},
        )
        assert copied.status_code == 202
        assert copied.json()["file_id"] != file_id
        before = _chunk_count(settings, file_id)
        conn = sqlite3.connect(settings.db_path)
        conn.execute(
            "UPDATE parse_jobs SET status = 'parsing', progress = 40 WHERE file_id = ?",
            (file_id,),
        )
        conn.execute("UPDATE files SET status = 'parsing', error_code = NULL WHERE id = ?", (file_id,))
        conn.commit()
        conn.close()
        from zhixu_server.service import recover_jobs

        recover_jobs(settings)
        assert wait_file(client, file_id)["status"] == "ready"
        assert _chunk_count(settings, file_id) == before
        conn = sqlite3.connect(settings.db_path)
        attempts = conn.execute(
            "SELECT attempts FROM parse_jobs WHERE file_id = ?",
            (file_id,),
        ).fetchone()[0]
        conn.close()
        assert attempts == 2
        second = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("另一份.txt", "另一句。".encode(), "text/plain")},
        )
        second_id = second.json()["file_id"]
        assert wait_file(client, second_id)["status"] == "ready"
        conn = sqlite3.connect(settings.db_path)
        conn.execute(
            "UPDATE parse_jobs SET status = 'parsing', attempts = 3 WHERE file_id = ?",
            (second_id,),
        )
        conn.execute("UPDATE files SET status = 'parsing' WHERE id = ?", (second_id,))
        conn.commit()
        conn.close()
        recover_jobs(settings)
        failed = client.get(f"/api/files/{second_id}/status").json()
        assert failed["status"] == "failed"
        assert failed["error_code"] == "interrupted"
        retried = client.post(f"/api/files/{second_id}/retry")
        assert retried.status_code == 200
        assert wait_file(client, second_id)["status"] == "ready"
        sent = client.post("/api/conversations/" + conv + "/messages", json={"content": "只检查中断"})
        request_id = sent.json()["request_id"]
        wait_terminal(settings, request_id)
        conn = sqlite3.connect(settings.db_path)
        conn.execute(
            """
            UPDATE requests
               SET status = 'streaming', finalized = 0, abort_reason = NULL
             WHERE id = ?
            """,
            (request_id,),
        )
        conn.commit()
        conn.close()
        recover_jobs(settings)
        conn = sqlite3.connect(settings.db_path)
        interrupted = conn.execute(
            "SELECT status, abort_reason FROM requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        conn.close()
        assert interrupted == ("failed", "interrupted")
    finally:
        client.close()
        other.close()


def test_chinese_pdf_docx_and_long_text(tmp_path, monkeypatch):
    from docx import Document

    client, settings = make_client(tmp_path, monkeypatch)
    try:
        login(client, "zh_user", PASSWORD)
        conv = client.post("/api/conversations", json={}).json()["id"]
        pdf = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("预算.pdf", FIXTURE.read_bytes(), "application/pdf")},
        )
        pdf_id = pdf.json()["file_id"]
        assert wait_file(client, pdf_id)["status"] == "ready"
        preview = client.get(f"/api/files/{pdf_id}/preview", params={"version": 1, "page": 1})
        assert preview.status_code == 200
        body = preview.json()
        assert "预算" in body["content"]
        assert "1200" in body["content"]
        assert "市民图书馆" in body["content"]
        assert body["page"] == 1
        document = Document()
        document.add_paragraph("市民图书馆活动说明。预算金额为 1200 元。")
        document.add_paragraph("地点说明" + ("补充" * 800) + ANCHOR)
        buffer = BytesIO()
        document.save(buffer)
        docx = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={
                "file": (
                    "说明.docx",
                    buffer.getvalue(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        docx_id = docx.json()["file_id"]
        docx_status = wait_file(client, docx_id)
        assert docx_status["status"] == "ready"
        assert docx_status["parse_notice"] == "page_unavailable"
        docx_preview = client.get(f"/api/files/{docx_id}/preview", params={"version": 1})
        assert "1200" in docx_preview.json()["content"]
        assert ANCHOR in docx_preview.json()["content"]
        long_text = ("甲" * 1300) + "\n\n" + ("乙" * 1300) + "\n\n" + ANCHOR
        uploaded = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("长文.md", long_text.encode(), "text/markdown")},
        )
        long_id = uploaded.json()["file_id"]
        assert wait_file(client, long_id)["status"] == "ready"
        conn = sqlite3.connect(settings.db_path)
        rows = conn.execute(
            "SELECT offset, length FROM chunks WHERE file_id = ? ORDER BY offset",
            (long_id,),
        ).fetchall()
        conn.close()
        assert len(rows) >= 3
        offsets = [row[0] for row in rows]
        assert offsets == sorted(offsets)
        assert offsets[0] < offsets[-1]
        long_preview = client.get(
            f"/api/files/{long_id}/preview",
            params={"version": 1, "quote": ANCHOR},
        )
        assert long_preview.json()["highlights"][0]["exact_match"] is True
        log_text = settings.log_path.read_text(encoding="utf-8")
        assert PASSWORD not in log_text
        assert "本季活动预算金额为 1200 元" not in log_text
        assert ANCHOR not in log_text
    finally:
        client.close()


def test_context_bound_records_attachments(tmp_path, monkeypatch):
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
        login(client, "bound_user", PASSWORD)
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
                (f"old-{index}", conv, owner, "旧问题" * 40, stamp),
            )
        conn.commit()
        conn.close()
        sent = client.post("/api/conversations/" + conv + "/messages", json={"content": "附件还在吗"})
        request_id = sent.json()["request_id"]
        wait_terminal(settings, request_id)
        conn = sqlite3.connect(settings.db_path)
        bound = conn.execute(
            """
            SELECT strategy, summarized_ids, attachment_ids, omitted_chunk_ids
              FROM context_bounds WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        enabled = conn.execute(
            "SELECT enabled FROM conversation_files WHERE file_id = ?",
            (file_id,),
        ).fetchone()[0]
        conn.close()
        assert bound is not None
        assert bound[0] in {"summary", "summary_and_chunk_trim", "new_conversation"}
        assert json.loads(bound[1])
        assert file_id in bound[2]
        assert enabled == 1
        events = client.get("/api/requests/" + request_id + "/events").text
        if "context_too_large" in events:
            assert file_id in events
    finally:
        client.close()
        upstream.close()


def test_cross_user_csrf_session_and_sse_reconnect(tmp_path, monkeypatch):
    upstream = FixtureUpstream(chunks=["普通回答，没有引用。"])
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
    )
    stranger, _stranger_settings = make_client(tmp_path, monkeypatch)
    try:
        login(client, "session_user", PASSWORD)
        login(stranger, "session_other", PASSWORD)
        conv = client.post("/api/conversations", json={"title": "仅自己可见"}).json()["id"]
        assert stranger.get("/api/conversations/" + conv).status_code == 403
        missing_csrf = client.post("/api/conversations", json={})
        client.headers.pop("X-CSRF-Token", None)
        missing_csrf = client.post("/api/conversations", json={})
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["error"]["code"] == "csrf_failed"
        client.headers["X-CSRF-Token"] = client.cookies.get("zhixu_csrf")
        client.headers["Origin"] = "http://evil.example"
        rejected = client.post("/api/conversations", json={})
        assert rejected.status_code == 403
        client.headers["Origin"] = "http://test.example"
        sent = client.post("/api/conversations/" + conv + "/messages", json={"content": "打个招呼"})
        request_id = sent.json()["request_id"]
        wait_terminal(settings, request_id)
        calls = upstream.calls
        replay = client.get(f"/api/requests/{request_id}/events")
        assert "普通回答" in replay.text
        assert upstream.calls == calls
        conn = sqlite3.connect(settings.db_path)
        last_id = conn.execute(
            "SELECT last_event_id FROM requests WHERE id = ?",
            (request_id,),
        ).fetchone()[0]
        conn.close()
        again = client.get(
            f"/api/requests/{request_id}/events",
            headers={"Last-Event-ID": str(last_id)},
        )
        assert again.status_code == 200
        assert again.text == ""
        assert upstream.calls == calls
        stolen = stranger.get(f"/api/requests/{request_id}/events")
        assert stolen.status_code == 403
        bad_origin = client.get(
            f"/api/requests/{request_id}/events",
            headers={"Origin": "http://evil.example"},
        )
        assert bad_origin.status_code == 403
        logged_out = client.post("/api/auth/logout")
        assert logged_out.status_code == 204
        assert client.get("/api/auth/me").status_code == 401
        assert client.get(f"/api/requests/{request_id}/events").status_code == 401
    finally:
        client.close()
        stranger.close()
        upstream.close()


def test_cancel_delete_race_and_prompt_injection(tmp_path, monkeypatch):
    upstream = FixtureUpstream(chunks=["临时可见片段"])
    client, settings = make_client(
        tmp_path,
        monkeypatch,
        ZHIXU_UPSTREAM_MODE="fixture",
        ZHIXU_MODEL_BASE_URL=upstream.base_url,
        ZHIXU_MODEL_NAME="fixture-model",
        ZHIXU_FIXTURE_HOLD="1",
    )
    try:
        login(client, "race_user", PASSWORD)
        conv = client.post("/api/conversations", json={}).json()["id"]
        text = "预算金额为 1200 元。地点在市民图书馆。".encode()
        uploaded = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("预算.txt", text, "text/plain")},
        )
        file_id = uploaded.json()["file_id"]
        assert wait_file(client, file_id)["status"] == "ready"
        conn = sqlite3.connect(settings.db_path)
        version = conn.execute("SELECT version FROM files WHERE id = ?", (file_id,)).fetchone()[0]
        chunk_id = conn.execute("SELECT id FROM chunks WHERE file_id = ?", (file_id,)).fetchone()[0]
        conn.close()
        upstream.chunks = ["临时可见片段"]
        sent = client.post("/api/conversations/" + conv + "/messages", json={"content": "预算金额是多少"})
        request_id = sent.json()["request_id"]
        _wait_delta(settings, request_id)
        cancelled = client.post(f"/api/requests/{request_id}/cancel")
        assert cancelled.status_code == 200
        wait_terminal(settings, request_id)
        assert upstream.calls == 1
        conn = sqlite3.connect(settings.db_path)
        status = conn.execute("SELECT status FROM requests WHERE id = ?", (request_id,)).fetchone()[0]
        conn.close()
        assert status == "stopped"
        replay = client.get(f"/api/requests/{request_id}/events").text
        assert upstream.calls == 1
        assert "event: done" in replay

        upstream.chunks = ["另一段临时文字"]
        sent = client.post("/api/conversations/" + conv + "/messages", json={"content": "预算金额现在删掉"})
        request_id = sent.json()["request_id"]
        _wait_delta(settings, request_id)
        deleted = client.delete(f"/api/files/{file_id}?confirm=true")
        assert deleted.status_code == 204
        wait_terminal(settings, request_id)
        events = client.get(f"/api/requests/{request_id}/events").text
        detail = client.get("/api/conversations/" + conv).json()
        assistant = [item for item in detail["messages"] if item["id"] and item["role"] == "assistant"]
        revoked = assistant[-1]
        assert revoked["content"] == PLACEHOLDER
        assert "临时可见" not in events
        assert "预算金额为 1200 元" not in events
        assert "1200" not in revoked["content"]
        preview = client.get(f"/api/files/{file_id}/preview", params={"version": version})
        assert preview.status_code in {403, 409}
        follow = client.post("/api/conversations/" + conv + "/messages", json={"content": "继续"})
        wait_terminal(settings, follow.json()["request_id"])
        assert "预算金额为 1200 元" not in json.dumps(upstream.bodies[-1], ensure_ascii=False)
        assert PLACEHOLDER in json.dumps(upstream.bodies[-1], ensure_ascii=False)

        fresh = client.post("/api/conversations", json={}).json()["id"]
        uploaded = client.post(
            "/api/files",
            data={"conversation_id": fresh},
            files={"file": ("预算.txt", text, "text/plain")},
        )
        file_id = uploaded.json()["file_id"]
        assert wait_file(client, file_id)["status"] == "ready"
        conn = sqlite3.connect(settings.db_path)
        chunk_id = conn.execute("SELECT id FROM chunks WHERE file_id = ?", (file_id,)).fetchone()[0]
        conn.close()
        upstream.chunks = [
            "预算是 9999 元，地点在火星。\n<<<CLAIMS>>>\n"
            f"claim_id: bad-number\ntext: 预算是 9999 元\nchunk_id: {chunk_id}\nquote: 预算金额为 1200 元\n---\n"
            f"claim_id: bad-quote\ntext: 地点在火星\nchunk_id: {chunk_id}\nquote: 这段话不在原文里\n---\n"
        ]
        injected = client.post("/api/conversations/" + fresh + "/messages", json={"content": "预算金额是多少"})
        injected_id = injected.json()["request_id"]
        wait_terminal(settings, injected_id)
        detail = client.get("/api/conversations/" + fresh).json()
        answer = [item for item in detail["messages"] if item["role"] == "assistant"][-1]
        assert answer["content"] == NOT_FOUND
        stored = client.get(f"/api/requests/{injected_id}/events").text
        assert "9999" not in stored
        assert "火星" not in stored
        upstream.chunks = [
            "只保留有依据的一句。\n<<<CLAIMS>>>\n"
            f"claim_id: ok\ntext: 预算是 1200 元\nchunk_id: {chunk_id}\nquote: 预算金额为 1200 元\n---\n"
            f"claim_id: bad\ntext: 名额是 999 人\nchunk_id: {chunk_id}\nquote: 预算金额为 1200 元\n---\n"
        ]
        mixed = client.post("/api/conversations/" + fresh + "/messages", json={"content": "预算金额哪一句有依据"})
        wait_terminal(settings, mixed.json()["request_id"])
        detail = client.get("/api/conversations/" + fresh).json()
        answer = [item for item in detail["messages"] if item["role"] == "assistant"][-1]
        assert answer["content"] == "预算是 1200 元"
        assert "999" not in answer["content"]
    finally:
        client.close()
        upstream.close()


def test_measured_isolation_and_fail_closed(tmp_path, monkeypatch):
    import zhixu_server.sandbox as sandbox
    from zhixu_server.sandbox import ParseFailed, extract_document, probe

    sandbox._PROBE = None
    measured = probe(force=True)
    assert measured["ready"] is True
    assert measured["uid"] not in {None, "0"}
    assert measured["network"] == "unreachable"
    assert measured["sentinel_blocked"] is True
    work = tmp_path / "work"
    work.mkdir()
    (work / "input.bin").write_text("probe", encoding="utf-8")
    os.chmod(work, 0o755)
    os.chmod(work / "input.bin", 0o644)
    code = (
        "import resource,sys\n"
        "sys.path.insert(0,'/pkg')\n"
        "from zhixu_server.parser_child import _limits, _ADDRESS_LIMIT, _CPU_SECONDS, _FILE_BYTES\n"
        "_limits()\n"
        "print('AS', resource.getrlimit(resource.RLIMIT_AS)[0], _ADDRESS_LIMIT)\n"
        "print('CPU', resource.getrlimit(resource.RLIMIT_CPU)[0], _CPU_SECONDS)\n"
        "print('FSIZE', resource.getrlimit(resource.RLIMIT_FSIZE)[0], _FILE_BYTES)\n"
        "print('NOFILE', resource.getrlimit(resource.RLIMIT_NOFILE)[0])\n"
        "print('NPROC', resource.getrlimit(resource.RLIMIT_NPROC)[0])\n"
        "try:\n"
        " open('/usr/zhixu-probe-write','w').write('x')\n"
        " print('WRITE ok')\n"
        "except Exception:\n"
        " print('WRITE blocked')\n"
        "try:\n"
        " open('/etc/passwd').read(1)\n"
        " print('ETC open')\n"
        "except Exception:\n"
        " print('ETC blocked')\n"
    )
    cmd = sandbox._command(work)
    cmd.extend(["--", "python3", "-c", code])
    completed = sandbox._run(cmd, 30)
    text = completed.stdout.decode()
    assert completed.returncode == 0, text
    assert "AS 268435456 268435456" in text
    assert "CPU 60 60" in text
    assert "FSIZE 33554432 33554432" in text
    assert "NOFILE 64" in text
    assert "NPROC 32" in text
    assert "WRITE blocked" in text
    assert "ETC blocked" in text or "ETC open" not in text
    source = tmp_path / "note.txt"
    source.write_text("隔离失败时不能解析。", encoding="utf-8")
    sandbox._PROBE = {"ready": False, "reason": "test"}
    try:
        try:
            extract_document(source, source.stat().st_size, "txt")
            raised = False
        except ParseFailed as exc:
            raised = exc.code == "isolation_unavailable"
        assert raised is True
        assert not (tmp_path / "note.txt.out").exists()
    finally:
        sandbox._PROBE = None
    monkeypatch.setattr(sandbox, "bwrap_path", lambda: None)
    failed = probe(force=True)
    assert failed["ready"] is False
    assert failed["reason"] == "bwrap_missing"
    sandbox._PROBE = None


def test_wal_backup_restore_and_purge(tmp_path, monkeypatch):
    from zhixu_server.backup import backup_consistent, purge_expired_backups, restore_consistent

    client, settings = make_client(tmp_path / "live", monkeypatch)
    try:
        login(client, "backup_user", PASSWORD)
        conv = client.post("/api/conversations", json={"title": "备份标题甲"}).json()["id"]
        holder = sqlite3.connect(settings.db_path)
        holder.execute("PRAGMA journal_mode=WAL")
        holder.execute(
            "UPDATE conversations SET title = ? WHERE id = ?",
            ("备份标题甲已提交", conv),
        )
        holder.commit()
        first = tmp_path / "snap-before-delete"
        backup_consistent(settings, first)
        assert client.delete(f"/api/conversations/{conv}?confirm=true").status_code == 204
        second = tmp_path / "snap-after-delete"
        backup_consistent(settings, second)
        holder.close()
        restored = tmp_path / "restored-before"
        restore_consistent(first, restored)
        conn = sqlite3.connect(restored / "zhixu.db")
        title, deleted = conn.execute(
            "SELECT title, deleted_at FROM conversations WHERE id = ?",
            (conv,),
        ).fetchone()
        conn.close()
        live = sqlite3.connect(settings.db_path)
        mode = live.execute("PRAGMA journal_mode").fetchone()[0]
        live.close()
        assert title == "备份标题甲已提交"
        assert deleted is None
        assert str(mode).lower() == "wal"
        after = tmp_path / "restored-after"
        restore_consistent(second, after)
        conn = sqlite3.connect(after / "zhixu.db")
        deleted = conn.execute(
            "SELECT deleted_at FROM conversations WHERE id = ?",
            (conv,),
        ).fetchone()[0]
        conn.close()
        assert deleted is not None
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
        assert purge_expired_backups(root, 30)["removed"] == 1
        assert not old.exists()
        assert fresh.exists()
        refused = False
        try:
            purge_expired_backups(settings.data_dir, 30)
        except RuntimeError:
            refused = True
        assert refused is True
        assert settings.db_path.exists()
    finally:
        client.close()


def test_file_status_returns_job_progress(tmp_path, monkeypatch):
    """ADV-11：状态接口回传当前任务的 progress。越权仍是 403。"""
    client, settings = make_client(tmp_path, monkeypatch)
    stranger, _stranger_settings = make_client(tmp_path, monkeypatch)
    try:
        login(client, "progress_user", PASSWORD)
        login(stranger, "progress_other", PASSWORD)
        conv = client.post("/api/conversations", json={}).json()["id"]
        uploaded = client.post(
            "/api/files",
            data={"conversation_id": conv},
            files={"file": ("进度.txt", "预算金额为 1200 元。".encode(), "text/plain")},
        )
        file_id = uploaded.json()["file_id"]
        ready = wait_file(client, file_id)
        assert ready["status"] == "ready"
        assert ready["progress"] == 100
        assert ready["job_id"]
        denied = stranger.get(f"/api/files/{file_id}/status")
        assert denied.status_code == 403
        assert "progress" not in denied.json()
        conn = sqlite3.connect(settings.db_path)
        conn.execute(
            "UPDATE parse_jobs SET status = 'parsing', progress = 40 WHERE id = ?",
            (ready["job_id"],),
        )
        conn.execute("UPDATE files SET status = 'parsing' WHERE id = ?", (file_id,))
        conn.commit()
        conn.close()
        mid = client.get(f"/api/files/{file_id}/status")
        assert mid.status_code == 200
        assert mid.json()["status"] == "parsing"
        assert mid.json()["progress"] == 40
        assert mid.json()["job_id"] == ready["job_id"]
    finally:
        client.close()
        stranger.close()


def _wait_delta(settings, request_id: str) -> None:
    for _ in range(50):
        conn = sqlite3.connect(settings.db_path)
        row = conn.execute(
            "SELECT 1 FROM request_events WHERE request_id = ? AND event = 'delta'",
            (request_id,),
        ).fetchone()
        conn.close()
        if row:
            return
        time.sleep(0.05)
    raise AssertionError("delta was not stored")
