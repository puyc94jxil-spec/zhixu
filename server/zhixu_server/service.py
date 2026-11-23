"""会话、文件和在线删除。文件字节只由隔离子进程读取。"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
from pathlib import Path

from zhixu_server.config import Settings
from zhixu_server.logutil import log_event
from zhixu_server.sandbox import ParseFailed, extract_document
from zhixu_server.security import iso, new_id
from zhixu_server.textutil import PLACEHOLDER, lex, split_paragraphs

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_FILES = 5
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_PDF_PAGES = 200
_WORKERS: dict[str, int] = {}
_WORKER_LOCK = threading.Lock()

_MIME = {
    ".txt": {"text/plain", "application/octet-stream", "text/markdown", ""},
    ".md": {"text/markdown", "text/plain", "application/octet-stream", "text/x-markdown", ""},
    ".pdf": {"application/pdf", "application/octet-stream", ""},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
        "application/zip",
        "",
    },
}

ERROR_TEXT = {
    "empty": "空文档，不能分析",
    "encrypted": "文件已加密，不能分析",
    "corrupt": "文件已损坏，不能分析",
    "no_text": "不含可提取文字",
    "too_many_pages": "PDF 超过 200 页",
    "type_mismatch": "扩展名与文件内容不一致",
    "binary": "文件不是可解析文本",
    "unsupported_media": "只接受 TXT、MD、PDF、DOCX",
    "isolation_unavailable": "解析隔离不可用，已拒绝解析",
    "dependency_unavailable": "解析组件不可用，已拒绝解析",
    "expand_limit": "展开后体积超过限制",
    "timeout": "解析超时",
    "cancelled": "解析已取消",
    "interrupted": "服务中断，请重试",
    "deleted": "文件已删除",
    "limits": "解析超出资源限制",
    "parse_failed": "解析失败",
}


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _status(conn: sqlite3.Connection, file_id: str, version: int, status: str, error: str | None = None) -> None:
    conn.execute(
        "UPDATE files SET status = ?, error_code = ? WHERE id = ? AND version = ?",
        (status, error, file_id, version),
    )
    conn.execute(
        "INSERT INTO file_status_log(file_id, version, status, created_at) VALUES (?, ?, ?, ?)",
        (file_id, version, status, iso()),
    )


def _delete_fts(conn: sqlite3.Connection, rowid: int, fts_lex: str, chunk_id: str) -> None:
    del fts_lex
    conn.execute("DELETE FROM chunks_fts WHERE rowid = ? OR chunk_id = ?", (rowid, chunk_id))


def redact_request_events(conn: sqlite3.Connection, request_id: str) -> None:
    """清掉已保存的增量原文和引用摘录。重连续传不能再把已删正文推回去。"""
    import json

    rows = conn.execute(
        "SELECT seq, event, data FROM request_events WHERE request_id = ?",
        (request_id,),
    ).fetchall()
    for row in rows:
        if row["event"] not in {"delta", "citation"}:
            continue
        try:
            payload = json.loads(row["data"])
        except json.JSONDecodeError:
            payload = {"request_id": request_id}
        if row["event"] == "delta":
            payload["text"] = ""
        else:
            payload["quote"] = ""
            payload["verified"] = False
        payload["redacted"] = True
        conn.execute(
            "UPDATE request_events SET data = ? WHERE request_id = ? AND seq = ?",
            (json.dumps(payload, ensure_ascii=False), request_id, row["seq"]),
        )


def redact_events_for_file(conn: sqlite3.Connection, file_id: str) -> None:
    rows = conn.execute(
        """
        SELECT DISTINCT r.id AS request_id
          FROM requests r
          JOIN conversation_files cf ON cf.conversation_id = r.conversation_id
         WHERE cf.file_id = ?
        """,
        (file_id,),
    ).fetchall()
    for row in rows:
        redact_request_events(conn, row["request_id"])
    rows = conn.execute(
        "SELECT message_id FROM message_sources WHERE file_id = ?",
        (file_id,),
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            UPDATE messages
               SET content = ?, withdrawn_reason = 'source_deleted', status = 'withdrawn'
             WHERE id = ? AND role = 'assistant'
            """,
            (PLACEHOLDER, row["message_id"]),
        )
        conn.execute("DELETE FROM citations WHERE message_id = ?", (row["message_id"],))


def abort_requests_for_file(conn: sqlite3.Connection, file_id: str) -> list[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT r.id
          FROM requests r
          JOIN conversation_files cf ON cf.conversation_id = r.conversation_id
         WHERE cf.file_id = ?
           AND r.status IN ('accepted', 'streaming', 'verifying', 'cancel_requested')
        """,
        (file_id,),
    ).fetchall()
    ids = []
    for row in rows:
        conn.execute(
            "UPDATE requests SET abort_reason = 'material_revoked', updated_at = ? WHERE id = ?",
            (iso(), row["id"]),
        )
        ids.append(row["id"])
    return ids


def remove_online_file(conn: sqlite3.Connection, settings: Settings, file_row: sqlite3.Row) -> None:
    file_id = file_row["id"]
    conn.execute(
        "UPDATE files SET deleted_at = ?, status = 'failed', error_code = 'deleted' WHERE id = ?",
        (iso(), file_id),
    )
    conn.execute(
        "UPDATE conversation_files SET enabled = 0 WHERE file_id = ?",
        (file_id,),
    )
    chunks = conn.execute(
        "SELECT id, fts_rowid, fts_lex FROM chunks WHERE file_id = ?",
        (file_id,),
    ).fetchall()
    for chunk in chunks:
        if chunk["fts_rowid"] is not None:
            _delete_fts(conn, chunk["fts_rowid"], chunk["fts_lex"], chunk["id"])
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    redact_events_for_file(conn, file_id)
    object_path = settings.objects_dir / file_row["object_key"]
    if object_path.exists():
        object_path.unlink()
    log_event("file_deleted_online", file_id=file_id, owner_user_id=file_row["owner_user_id"])


def signal_abort(request_ids: list[str]) -> None:
    # 延迟导入，避免和 generate 循环依赖
    from zhixu_server.generate import signal_requests

    signal_requests(request_ids)


def validate_upload(filename: str, content_type: str | None, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in _MIME:
        raise ServiceError(415, "unsupported_media", ERROR_TEXT["unsupported_media"])
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime and mime not in _MIME[suffix]:
        raise ServiceError(415, "type_mismatch", ERROR_TEXT["type_mismatch"])
    if len(data) <= 0:
        raise ServiceError(400, "empty", ERROR_TEXT["empty"])
    if len(data) > MAX_FILE_BYTES:
        raise ServiceError(413, "file_too_large", "单个文件不能超过 20MB")
    _sniff(suffix, data)
    return suffix


def _sniff(suffix: str, data: bytes) -> None:
    if suffix == ".pdf":
        if not data.startswith(b"%PDF-"):
            raise ServiceError(415, "type_mismatch", ERROR_TEXT["type_mismatch"])
        return
    if suffix == ".docx":
        if not data.startswith(b"PK\x03\x04"):
            raise ServiceError(415, "type_mismatch", ERROR_TEXT["type_mismatch"])
        return
    if b"\x00" in data[:8192] or data.startswith(b"%PDF-") or data.startswith(b"PK\x03\x04"):
        raise ServiceError(415, "type_mismatch", ERROR_TEXT["type_mismatch"])


def store_upload(
    conn: sqlite3.Connection,
    settings: Settings,
    *,
    owner_user_id: str,
    conversation_id: str,
    filename: str,
    content_type: str | None,
    data: bytes,
) -> dict:
    conv = conn.execute(
        "SELECT id FROM conversations WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL",
        (conversation_id, owner_user_id),
    ).fetchone()
    if conv is None:
        raise ServiceError(403, "forbidden", "不能使用这个会话")
    suffix = validate_upload(filename, content_type, data)
    digest = hashlib.sha256(data).hexdigest()
    existing = conn.execute(
        """
        SELECT * FROM files
         WHERE owner_user_id = ? AND hash = ? AND deleted_at IS NULL
        """,
        (owner_user_id, digest),
    ).fetchone()
    if existing is not None:
        _ensure_capacity(
            conn,
            conversation_id,
            extra_size=existing["size"],
            extra_count=1,
            file_id=existing["id"],
        )
        _bind(conn, conversation_id, existing, owner_user_id)
        log_event("file_reused", file_id=existing["id"], owner_user_id=owner_user_id)
        return _file_payload(existing, job_id=None, reused=True)
    _ensure_capacity(conn, conversation_id, extra_size=len(data), extra_count=1, file_id=None)
    file_id = new_id()
    version = 1
    object_key = new_id()
    path = settings.objects_dir / object_key
    path.write_bytes(data)
    os.chmod(path, 0o600)
    created = iso()
    conn.execute(
        """
        INSERT INTO files(
            id, owner_user_id, hash, name, mime, size, version, status,
            object_key, error_code, page_count, created_at, deleted_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded', ?, NULL, NULL, ?, NULL)
        """,
        (
            file_id,
            owner_user_id,
            digest,
            Path(filename).name,
            (content_type or "text/plain").split(";")[0],
            len(data),
            version,
            object_key,
            created,
        ),
    )
    _status(conn, file_id, version, "uploaded")
    conn.execute(
        """
        INSERT INTO conversation_files(
            conversation_id, file_id, version, owner_user_id, enabled, created_at
        ) VALUES (?, ?, ?, ?, 1, ?)
        """,
        (conversation_id, file_id, version, owner_user_id, created),
    )
    job_id = new_id()
    conn.execute(
        """
        INSERT INTO parse_jobs(
            id, file_id, version, status, progress, error_code, attempts, worker_pid, created_at, updated_at
        ) VALUES (?, ?, ?, 'uploaded', 0, NULL, 1, NULL, ?, ?)
        """,
        (job_id, file_id, version, created, created),
    )
    log_event("file_stored", file_id=file_id, owner_user_id=owner_user_id, size=len(data), suffix=suffix)
    return _file_payload(
        conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone(),
        job_id=job_id,
        reused=False,
    )


def _bind(conn: sqlite3.Connection, conversation_id: str, file_row: sqlite3.Row, owner: str) -> None:
    found = conn.execute(
        """
        SELECT 1 FROM conversation_files
         WHERE conversation_id = ? AND file_id = ? AND version = ?
        """,
        (conversation_id, file_row["id"], file_row["version"]),
    ).fetchone()
    if found:
        conn.execute(
            """
            UPDATE conversation_files SET enabled = 1
             WHERE conversation_id = ? AND file_id = ? AND version = ?
            """,
            (conversation_id, file_row["id"], file_row["version"]),
        )
        return
    conn.execute(
        """
        INSERT INTO conversation_files(
            conversation_id, file_id, version, owner_user_id, enabled, created_at
        ) VALUES (?, ?, ?, ?, 1, ?)
        """,
        (conversation_id, file_row["id"], file_row["version"], owner, iso()),
    )


def _ensure_capacity(conn, conversation_id: str, extra_size: int, extra_count: int, file_id: str | None) -> None:
    rows = conn.execute(
        """
        SELECT f.id, f.size
          FROM conversation_files cf
          JOIN files f ON f.id = cf.file_id AND f.version = cf.version
         WHERE cf.conversation_id = ? AND cf.enabled = 1 AND f.deleted_at IS NULL
        """,
        (conversation_id,),
    ).fetchall()
    ids = {row["id"] for row in rows}
    count = len(ids)
    total = sum(row["size"] for row in rows)
    if file_id and file_id in ids:
        extra_count = 0
        extra_size = 0
    if count + extra_count > MAX_FILES:
        raise ServiceError(413, "too_many_files", "每个会话最多 5 个文件")
    if total + extra_size > MAX_TOTAL_BYTES:
        raise ServiceError(413, "too_large_total", "每个会话的文件合计不能超过 50MB")


def _file_payload(row: sqlite3.Row, job_id: str | None, reused: bool) -> dict:
    return {
        "file_id": row["id"],
        "version": row["version"],
        "name": row["name"],
        "mime": row["mime"],
        "size": row["size"],
        "hash": row["hash"],
        "status": row["status"],
        "job_id": job_id,
        "reused": reused,
    }


def start_parse(settings: Settings, file_id: str, job_id: str) -> None:
    thread = threading.Thread(
        target=_parse_worker,
        args=(settings, file_id, job_id),
        daemon=True,
        name=f"parse-{file_id[:8]}",
    )
    thread.start()


def _parse_worker(settings: Settings, file_id: str, job_id: str) -> None:
    from zhixu_server.db import connect

    conn = connect(settings)
    try:
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        job = conn.execute("SELECT * FROM parse_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None or job is None or row["deleted_at"] is not None:
            return
        if _job_cancelled(conn, job_id):
            return
        _mark_job(conn, job_id, file_id, row["version"], "scanning", 10, None)
        source = settings.objects_dir / row["object_key"]
        _mark_job(conn, job_id, file_id, row["version"], "parsing", 40, None)
        try:
            kind = {".pdf": "pdf", ".docx": "docx", ".md": "md"}.get(Path(row["name"]).suffix.lower(), "txt")
            document = extract_document(source, row["size"], kind, job_id=job_id)
        except ParseFailed as exc:
            code = "cancelled" if _job_cancelled(conn, job_id) else exc.code
            _mark_job(conn, job_id, file_id, row["version"], "failed", 100, code)
            log_event("parse_failed", file_id=file_id, error_code=code)
            return
        except Exception:
            _mark_job(conn, job_id, file_id, row["version"], "failed", 100, "parse_failed")
            log_event("parse_failed", file_id=file_id, error_code="parse_failed")
            return
        if _job_cancelled(conn, job_id) or _file_gone(conn, file_id):
            _mark_job(conn, job_id, file_id, row["version"], "failed", 100, "cancelled")
            return
        _mark_job(conn, job_id, file_id, row["version"], "indexing", 70, None)
        try:
            _index_document(conn, row, document)
        except ParseFailed as exc:
            _mark_job(conn, job_id, file_id, row["version"], "failed", 100, exc.code)
            log_event("parse_failed", file_id=file_id, error_code=exc.code)
            return
        if _file_gone(conn, file_id):
            return
        page_count = document.get("page_count")
        notice = document.get("notice")
        conn.execute(
            """
            UPDATE files
               SET page_count = ?, parse_notice = ?, status = 'ready', error_code = NULL
             WHERE id = ?
            """,
            (page_count, notice, file_id),
        )
        _status(conn, file_id, row["version"], "ready")
        conn.execute(
            """
            UPDATE parse_jobs
               SET status = 'ready', progress = 100, error_code = NULL, updated_at = ?
             WHERE id = ?
            """,
            (iso(), job_id),
        )
        log_event("parse_ready", file_id=file_id, job_id=job_id)
    finally:
        conn.close()


def _job_cancelled(conn: sqlite3.Connection, job_id: str) -> bool:
    job = conn.execute("SELECT status FROM parse_jobs WHERE id = ?", (job_id,)).fetchone()
    return job is not None and job["status"] in {"cancel_requested", "cancelled", "failed"}


def _file_gone(conn: sqlite3.Connection, file_id: str) -> bool:
    row = conn.execute("SELECT deleted_at FROM files WHERE id = ?", (file_id,)).fetchone()
    return row is None or row["deleted_at"] is not None


def _mark_job(conn, job_id, file_id, version, status, progress, error) -> None:
    file_status = "failed" if status == "failed" else status
    conn.execute(
        """
        UPDATE parse_jobs
           SET status = ?, progress = ?, error_code = ?, updated_at = ?, worker_pid = ?
         WHERE id = ?
        """,
        (status, progress, error, iso(), os.getpid(), job_id),
    )
    _status(conn, file_id, version, file_status, error)


def _index_document(conn: sqlite3.Connection, file_row: sqlite3.Row, document: dict) -> None:
    pages = document.get("pages") or []
    wrote = 0
    for page in pages:
        if not isinstance(page, dict):
            continue
        paragraphs = split_paragraphs(str(page.get("text") or ""))
        page_number = page.get("page")
        for item in paragraphs:
            chunk_id = new_id()
            tokens = lex(item["text"])
            cur = conn.execute(
                "INSERT INTO chunks_fts(fts_lex, chunk_id) VALUES (?, ?)",
                (tokens, chunk_id),
            )
            conn.execute(
                """
                INSERT INTO chunks(
                    id, file_id, version, owner_user_id, page, paragraph, offset, length, text, fts_lex, fts_rowid
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    file_row["id"],
                    file_row["version"],
                    file_row["owner_user_id"],
                    page_number,
                    item["paragraph"],
                    item["offset"],
                    item["length"],
                    item["text"],
                    tokens,
                    cur.lastrowid,
                ),
            )
            wrote += 1
    if wrote == 0:
        raise ParseFailed("no_text" if document.get("kind") == "pdf" else "empty")


def retry_parse(conn: sqlite3.Connection, settings: Settings, owner: str, file_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM files WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL",
        (file_id, owner),
    ).fetchone()
    if row is None:
        raise ServiceError(403, "forbidden", "不能重试这个文件")
    if row["status"] == "ready":
        return _file_payload(row, None, False)
    attempts = conn.execute(
        "SELECT COALESCE(MAX(attempts), 0) AS n FROM parse_jobs WHERE file_id = ?",
        (file_id,),
    ).fetchone()["n"]
    job_id = new_id()
    stamp = iso()
    conn.execute(
        """
        INSERT INTO parse_jobs(
            id, file_id, version, status, progress, error_code, attempts, worker_pid, created_at, updated_at
        ) VALUES (?, ?, ?, 'uploaded', 0, NULL, ?, NULL, ?, ?)
        """,
        (job_id, file_id, row["version"], int(attempts) + 1, stamp, stamp),
    )
    _status(conn, file_id, row["version"], "uploaded")
    return _file_payload(row, job_id, False)


def cancel_parse(conn: sqlite3.Connection, owner: str, file_id: str) -> dict:
    row = conn.execute(
        "SELECT * FROM files WHERE id = ? AND owner_user_id = ?",
        (file_id, owner),
    ).fetchone()
    if row is None:
        raise ServiceError(403, "forbidden", "不能取消这个文件")
    from zhixu_server.sandbox import cancel_extract

    jobs = conn.execute(
        "SELECT id FROM parse_jobs WHERE file_id = ? AND status NOT IN ('ready', 'failed', 'cancelled')",
        (file_id,),
    ).fetchall()
    for job in jobs:
        cancel_extract(job["id"])
    conn.execute(
        """
        UPDATE parse_jobs
           SET status = 'cancelled', error_code = 'cancelled', updated_at = ?
         WHERE file_id = ? AND status NOT IN ('ready', 'failed', 'cancelled')
        """,
        (iso(), file_id),
    )
    if row["status"] != "ready":
        _status(conn, file_id, row["version"], "failed", "cancelled")
    return {"file_id": file_id, "status": "cancelled"}


def recover_jobs(settings: Settings) -> int:
    from zhixu_server.db import connect

    conn = connect(settings)
    try:
        rows = conn.execute(
            """
            SELECT id FROM parse_jobs
             WHERE status IN ('uploaded', 'scanning', 'parsing', 'indexing')
            """
        ).fetchall()
        for row in rows:
            job = conn.execute("SELECT * FROM parse_jobs WHERE id = ?", (row["id"],)).fetchone()
            _mark_job(conn, job["id"], job["file_id"], job["version"], "failed", 100, "interrupted")
        requests = conn.execute(
            """
            SELECT id, assistant_message_id FROM requests
             WHERE status IN ('accepted', 'streaming', 'verifying', 'cancel_requested')
            """
        ).fetchall()
        for row in requests:
            conn.execute(
                """
                UPDATE requests
                   SET status = 'failed', finalized = 1, updated_at = ?, abort_reason = 'interrupted'
                 WHERE id = ?
                """,
                (iso(), row["id"]),
            )
            conn.execute(
                """
                UPDATE messages
                   SET status = 'failed', withdrawn_reason = 'interrupted'
                 WHERE id = ?
                """,
                (row["assistant_message_id"],),
            )
            _append_event(
                conn,
                row["id"],
                "error",
                {"request_id": row["id"], "code": "internal", "message": "服务重启，生成已中断"},
            )
        return len(rows) + len(requests)
    finally:
        conn.close()


def _append_event(conn, request_id: str, event: str, data: dict) -> None:
    import json

    current = conn.execute(
        "SELECT last_event_id FROM requests WHERE id = ?",
        (request_id,),
    ).fetchone()
    seq = int(current["last_event_id"]) + 1
    conn.execute(
        "INSERT INTO request_events(request_id, seq, event, data) VALUES (?, ?, ?, ?)",
        (request_id, seq, event, json.dumps(data, ensure_ascii=False)),
    )
    conn.execute(
        "UPDATE requests SET last_event_id = ?, updated_at = ? WHERE id = ?",
        (seq, iso(), request_id),
    )


def owned_file(conn, owner: str, file_id: str):
    return conn.execute(
        "SELECT * FROM files WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL",
        (file_id, owner),
    ).fetchone()


def delete_account_online(conn: sqlite3.Connection, settings: Settings, user_id: str) -> None:
    """立刻从在线库和对象目录移除该账号的数据。备份目录留给 30 天清除，不在这里回滚。"""
    from zhixu_server.security import DUMMY_HASH

    files = conn.execute(
        "SELECT * FROM files WHERE owner_user_id = ? AND deleted_at IS NULL",
        (user_id,),
    ).fetchall()
    request_ids: list[str] = []
    for file_row in files:
        request_ids.extend(abort_requests_for_file(conn, file_row["id"]))
        remove_online_file(conn, settings, file_row)
    requests = conn.execute("SELECT id FROM requests WHERE owner_user_id = ?", (user_id,)).fetchall()
    for row in requests:
        redact_request_events(conn, row["id"])
        request_ids.append(row["id"])
    conn.execute(
        """
        UPDATE messages
           SET content = ?, status = 'withdrawn', withdrawn_reason = 'account_deleted'
         WHERE owner_user_id = ?
        """,
        ("[账号数据已删除]", user_id),
    )
    conn.execute("DELETE FROM feedback WHERE owner_user_id = ?", (user_id,))
    conn.execute(
        "UPDATE conversations SET deleted_at = ?, updated_at = ? WHERE owner_user_id = ? AND deleted_at IS NULL",
        (iso(), iso(), user_id),
    )
    conn.execute(
        "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
        (iso(), user_id),
    )
    conn.execute(
        "UPDATE users SET username = ?, password_hash = ?, deleted_at = ? WHERE id = ?",
        (f"deleted-{user_id}", DUMMY_HASH, iso(), user_id),
    )
    signal_abort(request_ids)
    log_event("account_deleted_online", user_id=user_id)
