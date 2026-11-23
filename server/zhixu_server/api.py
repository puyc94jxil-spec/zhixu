"""HTTP 接口。路径加 /api 前缀，字段用 snake_case。"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta

from fastapi import APIRouter, Body, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from zhixu_server.config import Settings
from zhixu_server.db import connect, lock
from zhixu_server.generate import signal_requests, start_generation
from zhixu_server.logutil import log_event
from zhixu_server.security import (
    CSRF_COOKIE,
    DUMMY_HASH,
    IP_LIMIT,
    LOGIN_LIMIT,
    SESSION_COOKIE,
    cookie_kwargs,
    hash_password,
    iso,
    new_id,
    now,
    origin_ok,
    rate_limited,
    record_failure,
    token,
    token_hash,
    verify_password,
)
from zhixu_server.service import (
    ERROR_TEXT,
    MAX_FILE_BYTES,
    ServiceError,
    abort_requests_for_file,
    cancel_parse,
    delete_account_online,
    remove_online_file,
    retry_parse,
    start_parse,
    store_upload,
)
from zhixu_server.textutil import PLACEHOLDER, fold_ws

router = APIRouter(prefix="/api")
_ACTIVE = ("accepted", "streaming", "verifying", "cancel_requested")


def _error(status: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
    )


def _rid(request: Request) -> str:
    return request.state.request_id


def _conn(request: Request):
    return connect(request.app.state.settings)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


def _require_origin(request: Request) -> JSONResponse | None:
    if origin_ok(_settings(request), request.headers.get("origin"), request.headers.get("referer")):
        return None
    return _error(403, "origin_rejected", "来源不被允许", _rid(request))


def _user(request: Request, conn):
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    row = conn.execute(
        """
        SELECT s.csrf_token, s.expires_at, s.revoked_at, u.id AS user_id, u.username, u.deleted_at
          FROM sessions s
          JOIN users u ON u.id = s.user_id
         WHERE s.token_hash = ?
        """,
        (token_hash(raw),),
    ).fetchone()
    if row is None or row["revoked_at"] is not None or row["deleted_at"] is not None:
        return None
    if row["expires_at"] <= iso():
        return None
    return row


def _require_user(request: Request, conn):
    user = _user(request, conn)
    if user is None:
        raise ServiceError(401, "unauthorized", "请先登录")
    return user


def _require_csrf(request: Request, user) -> None:
    header = request.headers.get("x-csrf-token") or ""
    cookie = request.cookies.get(CSRF_COOKIE) or ""
    if not header or header != user["csrf_token"] or header != cookie:
        raise ServiceError(403, "csrf_failed", "缺少或无效的 CSRF 令牌")


def _set_session(response: Response, settings: Settings, conn, user_id: str) -> None:
    raw = token()
    csrf = token()
    conn.execute(
        """
        INSERT INTO sessions(id, token_hash, user_id, csrf_token, expires_at, created_at, revoked_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL)
        """,
        (new_id(), token_hash(raw), user_id, csrf, iso(now() + timedelta(hours=settings.session_ttl_hours)), iso()),
    )
    response.set_cookie(SESSION_COOKIE, raw, **cookie_kwargs(settings, True))
    response.set_cookie(CSRF_COOKIE, csrf, **cookie_kwargs(settings, False))


def _guard_write(request: Request, conn):
    origin = _require_origin(request)
    if origin is not None:
        raise ServiceError(403, "origin_rejected", "来源不被允许")
    user = _require_user(request, conn)
    _require_csrf(request, user)
    return user


@router.post("/auth/register")
def register(request: Request, body: dict = Body(...)):
    origin = _require_origin(request)
    if origin is not None:
        return origin
    username = str(body.get("username") or "")
    password = str(body.get("password") or "")
    if not (3 <= len(username) <= 32 and username.replace("_", "").isalnum()):
        return _error(400, "invalid_username", "用户名需要 3 到 32 位字母、数字或下划线", _rid(request))
    if len(password) < 10:
        return _error(400, "invalid_password", "密码至少 10 位", _rid(request))
    conn = _conn(request)
    try:
        ip = _client_ip(request)
        with lock():
            if rate_limited(conn, f"ip|{ip}", IP_LIMIT) or rate_limited(conn, f"reg|{ip}", LOGIN_LIMIT):
                log_event("register_rate_limited", error_code="login_rate_limited")
                return _error(429, "login_rate_limited", "尝试次数过多，请稍后再试", _rid(request))
            found = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if found:
                record_failure(conn, f"reg|{ip}")
                return _error(409, "username_taken", "用户名已存在", _rid(request))
            user_id = new_id()
            conn.execute(
                "INSERT INTO users(id, username, password_hash, created_at, deleted_at) VALUES (?, ?, ?, ?, NULL)",
                (user_id, username, hash_password(password), iso()),
            )
        response = JSONResponse(status_code=201, content={"user_id": user_id, "request_id": _rid(request)})
        _set_session(response, _settings(request), conn, user_id)
        log_event("register", user_id=user_id)
        return response
    finally:
        conn.close()


@router.post("/auth/login")
def login(request: Request, body: dict = Body(...)):
    origin = _require_origin(request)
    if origin is not None:
        return origin
    username = str(body.get("username") or body.get("email") or "")
    password = str(body.get("password") or "")
    conn = _conn(request)
    try:
        ip = _client_ip(request)
        bucket = f"{ip}|{username}"
        with lock():
            if rate_limited(conn, f"ip|{ip}", IP_LIMIT) or rate_limited(conn, bucket, LOGIN_LIMIT):
                log_event("login_rate_limited", error_code="login_rate_limited")
                return _error(429, "login_rate_limited", "尝试次数过多，请稍后再试", _rid(request))
            row = conn.execute(
                "SELECT * FROM users WHERE username = ? AND deleted_at IS NULL",
                (username,),
            ).fetchone()
            password_hash = row["password_hash"] if row else DUMMY_HASH
            ok = verify_password(password_hash, password) and row is not None
            if not ok:
                record_failure(conn, bucket)
                record_failure(conn, f"ip|{ip}")
                log_event("login_failed", error_code="unauthorized")
                return _error(401, "unauthorized", "账号或密码不正确", _rid(request))
        response = JSONResponse(content={"user_id": row["id"], "request_id": _rid(request)})
        _set_session(response, _settings(request), conn, row["id"])
        log_event("login", user_id=row["id"])
        return response
    finally:
        conn.close()


@router.post("/auth/logout")
def logout(request: Request):
    conn = _conn(request)
    try:
        try:
            user = _guard_write(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        raw = request.cookies.get(SESSION_COOKIE, "")
        conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token_hash = ?",
            (iso(), token_hash(raw)),
        )
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        log_event("logout", user_id=user["user_id"])
        return response
    finally:
        conn.close()


@router.get("/auth/me")
def me(request: Request):
    conn = _conn(request)
    try:
        try:
            user = _require_user(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        return {"user_id": user["user_id"], "username": user["username"], "request_id": _rid(request)}
    finally:
        conn.close()


@router.delete("/auth/me")
def delete_me(request: Request, confirm: bool = False):
    conn = _conn(request)
    try:
        try:
            user = _guard_write(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        if not confirm:
            return _error(400, "confirm_required", "删除账号需要 confirm=true", _rid(request))
        delete_account_online(conn, _settings(request), user["user_id"])
        response = Response(status_code=204)
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return response
    finally:
        conn.close()


@router.post("/conversations", status_code=201)
def create_conversation(request: Request, body: dict | None = Body(default=None)):
    body = body or {}
    conn = _conn(request)
    try:
        try:
            user = _guard_write(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        key = request.headers.get("idempotency-key")
        body_hash = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        cached = _idempotent(conn, user["user_id"], key, body_hash)
        if cached is not None:
            return cached
        title = str(body.get("title") or "新对话")[:80]
        conv_id = new_id()
        stamp = iso()
        conn.execute(
            """
            INSERT INTO conversations(id, owner_user_id, title, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (conv_id, user["user_id"], title, stamp, stamp),
        )
        payload = {"id": conv_id, "title": title, "created_at": stamp, "updated_at": stamp, "request_id": _rid(request)}
        _store_idempotent(conn, user["user_id"], key, body_hash, 201, payload)
        return JSONResponse(status_code=201, content=payload)
    finally:
        conn.close()


@router.get("/conversations")
def list_conversations(request: Request, q: str | None = None, limit: int = 20, cursor: str | None = None):
    conn = _conn(request)
    try:
        try:
            user = _require_user(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        limit = max(1, min(limit, 50))
        params: list = [user["user_id"]]
        where = "owner_user_id = ? AND deleted_at IS NULL"
        if q:
            where += " AND title LIKE ?"
            params.append("%" + q.replace("%", "").replace("_", "") + "%")
        if cursor:
            where += " AND updated_at < ?"
            params.append(cursor)
        params.append(limit + 1)
        rows = conn.execute(
            f"SELECT id, title, updated_at FROM conversations WHERE {where} ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
        items = [dict(row) for row in rows[:limit]]
        next_cursor = items[-1]["updated_at"] if len(rows) > limit and items else None
        return {"items": items, "next_cursor": next_cursor, "request_id": _rid(request)}
    finally:
        conn.close()


@router.get("/conversations/{conversation_id}")
def get_conversation(request: Request, conversation_id: str):
    conn = _conn(request)
    try:
        try:
            user = _require_user(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        conv = _own_conversation(conn, user["user_id"], conversation_id)
        if conv is None:
            return _error(403, "forbidden", "不能打开这个会话", _rid(request))
        messages = []
        for row in conn.execute(
            """
            SELECT id, role, content, status, version, request_id, user_message_id, withdrawn_reason, created_at
              FROM messages WHERE conversation_id = ? ORDER BY created_at ASC
            """,
            (conversation_id,),
        ):
            item = dict(row)
            if row["role"] == "assistant" and _message_redacted(conn, row["id"], conversation_id):
                item["content"] = PLACEHOLDER
                item["status"] = "withdrawn"
                item["citations"] = []
            else:
                item["citations"] = [
                    dict(cite)
                    for cite in conn.execute(
                        """
                        SELECT c.claim_id, c.chunk_id, c.quote, c.file_id, c.version,
                               c.page, c.paragraph, c.offset, c.length
                          FROM citations c
                          JOIN files f ON f.id = c.file_id AND f.version = c.version
                         WHERE c.message_id = ? AND c.verified_at IS NOT NULL
                           AND f.deleted_at IS NULL AND f.owner_user_id = ?
                        """,
                        (row["id"], user["user_id"]),
                    )
                ]
            messages.append(item)
        files = [
            dict(row)
            for row in conn.execute(
                """
                SELECT f.id AS file_id, f.version, f.name, f.status, f.error_code, f.page_count,
                       f.parse_notice, cf.enabled
                  FROM conversation_files cf
                  JOIN files f ON f.id = cf.file_id AND f.version = cf.version
                 WHERE cf.conversation_id = ? AND f.deleted_at IS NULL
                """,
                (conversation_id,),
            )
        ]
        return {
            "id": conv["id"],
            "title": conv["title"],
            "updated_at": conv["updated_at"],
            "messages": messages,
            "files": files,
            "request_id": _rid(request),
        }
    finally:
        conn.close()


@router.patch("/conversations/{conversation_id}")
def patch_conversation(request: Request, conversation_id: str, body: dict = Body(...)):
    conn = _conn(request)
    try:
        try:
            user = _guard_write(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        conv = _own_conversation(conn, user["user_id"], conversation_id)
        if conv is None:
            return _error(403, "forbidden", "不能修改这个会话", _rid(request))
        title = str(body.get("title") or "").strip()[:80]
        if not title:
            return _error(400, "invalid_title", "标题不能为空", _rid(request))
        stamp = iso()
        conn.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, stamp, conversation_id),
        )
        return {"id": conversation_id, "title": title, "updated_at": stamp, "request_id": _rid(request)}
    finally:
        conn.close()


@router.delete("/conversations/{conversation_id}")
def delete_conversation(request: Request, conversation_id: str, confirm: bool = False, delete_files: bool = False):
    conn = _conn(request)
    try:
        try:
            user = _guard_write(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        if not confirm:
            return _error(400, "confirm_required", "删除会话需要 confirm=true", _rid(request))
        conv = _own_conversation(conn, user["user_id"], conversation_id)
        if conv is None:
            return _error(403, "forbidden", "不能删除这个会话", _rid(request))
        conn.execute(
            "UPDATE conversations SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (iso(), iso(), conversation_id),
        )
        conn.execute(
            "UPDATE conversation_files SET enabled = 0 WHERE conversation_id = ?",
            (conversation_id,),
        )
        running = conn.execute(
            f"SELECT id FROM requests WHERE conversation_id = ? AND status IN ({','.join('?' * len(_ACTIVE))})",
            (conversation_id, *_ACTIVE),
        ).fetchall()
        ids = [row["id"] for row in running]
        for request_id in ids:
            conn.execute(
                "UPDATE requests SET abort_reason = 'material_revoked', updated_at = ? WHERE id = ?",
                (iso(), request_id),
            )
        if delete_files:
            file_rows = conn.execute(
                """
                SELECT f.* FROM files f
                  JOIN conversation_files cf ON cf.file_id = f.id
                 WHERE cf.conversation_id = ? AND f.owner_user_id = ? AND f.deleted_at IS NULL
                """,
                (conversation_id, user["user_id"]),
            ).fetchall()
            for file_row in file_rows:
                others = conn.execute(
                    """
                    SELECT 1 FROM conversation_files cf
                      JOIN conversations c ON c.id = cf.conversation_id
                     WHERE cf.file_id = ? AND cf.conversation_id != ? AND c.deleted_at IS NULL AND cf.enabled = 1
                    """,
                    (file_row["id"], conversation_id),
                ).fetchone()
                if others is None:
                    ids.extend(abort_requests_for_file(conn, file_row["id"]))
                    remove_online_file(conn, _settings(request), file_row)
        signal_requests(ids)
        log_event("conversation_deleted", conversation_id=conversation_id, user_id=user["user_id"])
        return Response(status_code=204)
    finally:
        conn.close()


@router.post("/files")
async def upload_file(
    request: Request,
    conversation_id: str = Form(...),
    upload: UploadFile = File(..., alias="file"),
):
    origin = _require_origin(request)
    if origin is not None:
        return origin
    conn = _conn(request)
    try:
        try:
            user = _require_user(request, conn)
            _require_csrf(request, user)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        data = bytearray()
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            if len(data) + len(chunk) > MAX_FILE_BYTES:
                return _error(413, "file_too_large", "单个文件不能超过 20MB", _rid(request))
            data.extend(chunk)
        key = request.headers.get("idempotency-key")
        body_hash = hashlib.sha256(bytes(data) + b"\0" + (upload.filename or "").encode()).hexdigest()
        cached = _idempotent(conn, user["user_id"], key, body_hash)
        if cached is not None:
            return cached
        try:
            with lock():
                payload = store_upload(
                    conn,
                    _settings(request),
                    owner_user_id=user["user_id"],
                    conversation_id=conversation_id,
                    filename=upload.filename or "unnamed.txt",
                    content_type=upload.content_type,
                    data=bytes(data),
                )
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        payload["request_id"] = _rid(request)
        if payload.get("job_id"):
            start_parse(_settings(request), payload["file_id"], payload["job_id"])
        status = 200 if payload.get("reused") else 202
        _store_idempotent(conn, user["user_id"], key, body_hash, status, payload)
        return JSONResponse(status_code=status, content=payload)
    finally:
        conn.close()


@router.get("/files/{file_id}/status")
def file_status(request: Request, file_id: str):
    conn = _conn(request)
    try:
        try:
            user = _require_user(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        row = conn.execute(
            "SELECT * FROM files WHERE id = ? AND owner_user_id = ?",
            (file_id, user["user_id"]),
        ).fetchone()
        if row is None or row["deleted_at"] is not None:
            return _error(403, "forbidden", "不能查看这个文件", _rid(request))
        job = conn.execute(
            """
            SELECT id, progress FROM parse_jobs
             WHERE file_id = ? AND version = ?
             ORDER BY updated_at DESC, rowid DESC
             LIMIT 1
            """,
            (row["id"], row["version"]),
        ).fetchone()
        if job is not None:
            progress = int(job["progress"])
            job_id = job["id"]
        elif row["status"] == "ready":
            progress = 100
            job_id = None
        else:
            progress = 0
            job_id = None
        return {
            "file_id": row["id"],
            "version": row["version"],
            "status": row["status"],
            "progress": progress,
            "job_id": job_id,
            "error_code": row["error_code"],
            "error_message": ERROR_TEXT.get(row["error_code"] or "", None),
            "page_count": row["page_count"],
            "parse_notice": row["parse_notice"],
            "request_id": _rid(request),
        }
    finally:
        conn.close()


@router.post("/files/{file_id}/retry")
def file_retry(request: Request, file_id: str):
    conn = _conn(request)
    try:
        try:
            user = _guard_write(request, conn)
            payload = retry_parse(conn, _settings(request), user["user_id"], file_id)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        if payload.get("job_id"):
            start_parse(_settings(request), file_id, payload["job_id"])
        payload["request_id"] = _rid(request)
        return payload
    finally:
        conn.close()


@router.post("/files/{file_id}/cancel")
def file_cancel(request: Request, file_id: str):
    conn = _conn(request)
    try:
        try:
            user = _guard_write(request, conn)
            payload = cancel_parse(conn, user["user_id"], file_id)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        payload["request_id"] = _rid(request)
        return payload
    finally:
        conn.close()


@router.delete("/files/{file_id}")
def delete_file(request: Request, file_id: str, confirm: bool = False):
    conn = _conn(request)
    try:
        try:
            user = _guard_write(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        if not confirm:
            return _error(400, "confirm_required", "删除文件需要 confirm=true", _rid(request))
        row = conn.execute(
            "SELECT * FROM files WHERE id = ? AND owner_user_id = ?",
            (file_id, user["user_id"]),
        ).fetchone()
        if row is None or row["deleted_at"] is not None:
            return _error(403, "forbidden", "不能删除这个文件", _rid(request))
        ids = abort_requests_for_file(conn, file_id)
        remove_online_file(conn, _settings(request), row)
        signal_requests(ids)
        return Response(status_code=204)
    finally:
        conn.close()


@router.get("/files/{file_id}/preview")
def preview_file(
    request: Request,
    file_id: str,
    version: int,
    page: int | None = None,
    paragraph: int | None = None,
    start_offset: int | None = None,
    end_offset: int | None = None,
    quote: str | None = None,
):
    conn = _conn(request)
    try:
        try:
            user = _require_user(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        if row is None or row["owner_user_id"] != user["user_id"]:
            return _error(403, "forbidden", "不能预览这个文件", _rid(request))
        if row["deleted_at"] is not None or row["version"] != version:
            return _error(409, "version_conflict", "文件版本不存在或已删除", _rid(request))
        allowed = conn.execute(
            """
            SELECT 1 FROM conversation_files
             WHERE file_id = ? AND version = ? AND owner_user_id = ? AND enabled = 1
            """,
            (file_id, version, user["user_id"]),
        ).fetchone()
        if allowed is None:
            return _error(409, "revoked", "文件授权已撤销", _rid(request))
        clauses = "file_id = ? AND version = ?"
        params: list = [file_id, version]
        if paragraph is not None:
            clauses += " AND paragraph = ?"
            params.append(paragraph)
        if page is not None:
            clauses += " AND (page = ? OR page IS NULL)"
            params.append(page)
        chunks = conn.execute(
            f"SELECT * FROM chunks WHERE {clauses} ORDER BY offset ASC",
            params,
        ).fetchall()
        if not chunks:
            return _error(409, "version_conflict", "没有可预览的原文", _rid(request))
        content = "\n".join(chunk["text"] for chunk in chunks)
        highlights = []
        highlight_error = None
        if quote:
            placed = False
            for chunk in chunks:
                if quote in chunk["text"] or fold_ws(quote) in fold_ws(chunk["text"]):
                    local = chunk["text"].find(quote)
                    exact = local >= 0
                    start = chunk["offset"] + (local if exact else 0)
                    end = start + (len(quote) if exact else 0)
                    highlights.append(
                        {
                            "page": chunk["page"],
                            "paragraph": chunk["paragraph"],
                            "start_offset": start,
                            "end_offset": end if exact else start,
                            "quote": quote,
                            "exact_match": exact,
                        }
                    )
                    placed = True
                    break
            if not placed:
                highlight_error = "无法在该版本原文中定位，请重新打开"
        return {
            "file_id": file_id,
            "version": version,
            "name": row["name"],
            "page": page or 1,
            "page_count": row["page_count"] or 1,
            "paragraph": paragraph,
            "offset_interval": "half_open",
            "content": content,
            "highlights": highlights,
            "highlight_error": highlight_error,
            "request_id": _rid(request),
            "start_offset": start_offset,
            "end_offset": end_offset,
        }
    finally:
        conn.close()


@router.post("/conversations/{conversation_id}/messages")
def create_message(request: Request, conversation_id: str, body: dict = Body(...)):
    conn = _conn(request)
    try:
        try:
            user = _guard_write(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        content = str(body.get("content") or "")
        if not content.strip():
            return _error(400, "empty_content", "请先写下问题", _rid(request))
        conv = _own_conversation(conn, user["user_id"], conversation_id)
        if conv is None:
            return _error(403, "forbidden", "不能在这个会话里发送", _rid(request))
        key = request.headers.get("idempotency-key") or body.get("client_message_id")
        body_hash = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        cached = _idempotent(conn, user["user_id"], key, body_hash)
        if cached is not None:
            return cached
        busy = conn.execute(
            f"""
            SELECT id FROM requests
             WHERE conversation_id = ? AND status IN ({','.join('?' * len(_ACTIVE))})
            """,
            (conversation_id, *_ACTIVE),
        ).fetchone()
        if busy:
            return _error(409, "generation_in_progress", "正在生成，请等待或停止", _rid(request))
        retry_of = body.get("retry_of_message_id")
        stamp = iso()
        if retry_of:
            original = conn.execute(
                """
                SELECT * FROM messages
                 WHERE id = ? AND conversation_id = ? AND owner_user_id = ? AND role = 'user'
                """,
                (retry_of, conversation_id, user["user_id"]),
            ).fetchone()
            if original is None:
                return _error(403, "forbidden", "不能重试这条消息", _rid(request))
            user_message_id = original["id"]
            version = conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS n FROM messages WHERE user_message_id = ?",
                (user_message_id,),
            ).fetchone()["n"]
        else:
            user_message_id = new_id()
            version = 1
            conn.execute(
                """
                INSERT INTO messages(
                    id, conversation_id, owner_user_id, role, content, status, model, request_id,
                    version, user_message_id, withdrawn_reason, material, created_at
                ) VALUES (?, ?, ?, 'user', ?, 'completed', NULL, NULL, 1, NULL, NULL, 0, ?)
                """,
                (user_message_id, conversation_id, user["user_id"], content.strip(), stamp),
            )
            if conv["title"] in {"", "新对话"}:
                conn.execute(
                    "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                    (content.strip()[:24], stamp, conversation_id),
                )
        assistant_id = new_id()
        request_id = new_id()
        conn.execute(
            """
            INSERT INTO messages(
                id, conversation_id, owner_user_id, role, content, status, model, request_id,
                version, user_message_id, withdrawn_reason, material, created_at
            ) VALUES (?, ?, ?, 'assistant', '', 'accepted', ?, ?, ?, ?, NULL, 0, ?)
            """,
            (
                assistant_id,
                conversation_id,
                user["user_id"],
                _settings(request).model_name or None,
                request_id,
                version,
                user_message_id,
                stamp,
            ),
        )
        conn.execute(
            """
            INSERT INTO requests(
                id, conversation_id, owner_user_id, user_message_id, assistant_message_id,
                status, last_event_id, idempotency_key, upstream_started, finalized, abort_reason,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'accepted', 0, ?, 0, 0, NULL, ?, ?)
            """,
            (request_id, conversation_id, user["user_id"], user_message_id, assistant_id, key, stamp, stamp),
        )
        conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (stamp, conversation_id),
        )
        payload = {
            "message_id": assistant_id,
            "user_message_id": user_message_id,
            "request_id": request_id,
            "status": "accepted",
        }
        _store_idempotent(conn, user["user_id"], key, body_hash, 202, payload)
        start_generation(_settings(request), request_id)
        return JSONResponse(status_code=202, content=payload)
    finally:
        conn.close()


@router.get("/requests/{request_id}/events")
def request_events(request: Request, request_id: str):
    origin = request.headers.get("origin")
    if origin and not origin_ok(_settings(request), origin, None):
        return _error(403, "origin_rejected", "来源不被允许", _rid(request))
    conn = _conn(request)
    try:
        try:
            user = _require_user(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        row = conn.execute(
            "SELECT * FROM requests WHERE id = ? AND owner_user_id = ?",
            (request_id, user["user_id"]),
        ).fetchone()
        if row is None:
            return _error(403, "forbidden", "不能订阅这个请求", _rid(request))
    finally:
        conn.close()
    last_header = request.headers.get("last-event-id") or request.query_params.get("last_event_id") or "0"
    try:
        last_id = int(last_header)
    except ValueError:
        last_id = 0

    def stream():
        seen = last_id
        deadline = now().timestamp() + 130
        while now().timestamp() < deadline:
            local = connect(_settings(request))
            try:
                current = local.execute(
                    "SELECT last_event_id, finalized, status FROM requests WHERE id = ?",
                    (request_id,),
                ).fetchone()
                if current is None:
                    return
                if seen > int(current["last_event_id"]) and current["finalized"]:
                    payload = {"error": {"code": "resync", "message": "请改拉消息快照"}}
                    yield _sse(seen, "error", payload)
                    return
                rows = local.execute(
                    """
                    SELECT seq, event, data FROM request_events
                     WHERE request_id = ? AND seq > ? ORDER BY seq ASC
                    """,
                    (request_id, seen),
                ).fetchall()
                for item in rows:
                    seen = item["seq"]
                    yield f"id: {item['seq']}\nevent: {item['event']}\ndata: {item['data']}\n\n"
                    if item["event"] in {"done", "error"}:
                        return
                if current["finalized"] and not rows:
                    return
            finally:
                local.close()
            import time

            time.sleep(0.05)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/requests/{request_id}/cancel")
def cancel_request(request: Request, request_id: str):
    conn = _conn(request)
    try:
        try:
            user = _guard_write(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        row = conn.execute(
            "SELECT * FROM requests WHERE id = ? AND owner_user_id = ?",
            (request_id, user["user_id"]),
        ).fetchone()
        if row is None:
            return _error(403, "forbidden", "不能取消这个请求", _rid(request))
        # 只改尚未结束的请求。已经写成 stopped 的行不能再被改回 cancel_requested。
        updated = conn.execute(
            f"""
            UPDATE requests
               SET status = 'cancel_requested', updated_at = ?
             WHERE id = ? AND owner_user_id = ? AND finalized = 0
               AND status IN ({','.join('?' * len(_ACTIVE))})
            """,
            (iso(), request_id, user["user_id"], *_ACTIVE),
        ).rowcount
        if updated:
            signal_requests([request_id])
            status = "stopped"
        else:
            status = row["status"] if row["finalized"] else conn.execute(
                "SELECT status FROM requests WHERE id = ?",
                (request_id,),
            ).fetchone()["status"]
        log_event("cancel", request_id=request_id, status=status)
        return {"request_id": request_id, "status": status if status != "cancel_requested" else "stopped"}
    finally:
        conn.close()


_FEEDBACK_REASONS = {"incorrect", "incomplete", "citation", "format", "other"}


@router.post("/messages/{message_id}/feedback", status_code=201)
def create_feedback(request: Request, message_id: str, body: dict = Body(...)):
    conn = _conn(request)
    try:
        try:
            user = _guard_write(request, conn)
        except ServiceError as exc:
            return _error(exc.status, exc.code, exc.message, _rid(request))
        reason = str(body.get("reason") or "")
        if reason not in _FEEDBACK_REASONS:
            return _error(400, "invalid_reason", "请选择反馈原因", _rid(request))
        note = str(body.get("note") or "").strip()
        if len(note) > 200:
            return _error(400, "note_too_long", "补充说明不能超过 200 字", _rid(request))
        message = conn.execute(
            """
            SELECT id FROM messages
             WHERE id = ? AND owner_user_id = ? AND role = 'assistant'
            """,
            (message_id, user["user_id"]),
        ).fetchone()
        if message is None:
            return _error(403, "forbidden", "不能给这条回答反馈", _rid(request))
        existing = conn.execute(
            "SELECT id FROM feedback WHERE message_id = ? AND owner_user_id = ?",
            (message_id, user["user_id"]),
        ).fetchone()
        if existing is not None:
            return _error(409, "feedback_exists", "这条回答已经反馈过", _rid(request))
        feedback_id = new_id()
        conn.execute(
            """
            INSERT INTO feedback(id, message_id, owner_user_id, reason, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (feedback_id, message_id, user["user_id"], reason, note or None, iso()),
        )
        log_event("feedback_stored", message_id=message_id, reason=reason)
        return JSONResponse(
            status_code=201,
            content={"id": feedback_id, "message_id": message_id, "reason": reason, "request_id": _rid(request)},
        )
    finally:
        conn.close()


@router.get("/health")
def health(request: Request):
    from zhixu_server.sandbox import probe

    settings = _settings(request)
    isolation = probe()
    return {
        "status": "ok",
        "upstream_mode": settings.upstream_mode,
        "model_configured": bool(settings.model_base_url and settings.model_name),
        "isolation_ready": bool(isolation.get("ready")),
        "isolation_reason": isolation.get("reason"),
        "request_id": _rid(request),
    }


def _sse(seq: int, event: str, payload: dict) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _own_conversation(conn, owner: str, conversation_id: str):
    return conn.execute(
        """
        SELECT * FROM conversations
         WHERE id = ? AND owner_user_id = ? AND deleted_at IS NULL
        """,
        (conversation_id, owner),
    ).fetchone()


def _message_redacted(conn, message_id: str, conversation_id: str) -> bool:
    from zhixu_server.generate import _sources_revoked

    return _sources_revoked(conn, message_id, conversation_id)


def _idempotent(conn, user_id: str, key: str | None, body_hash: str):
    if not key:
        return None
    row = conn.execute(
        "SELECT * FROM idempotency WHERE user_id = ? AND key = ?",
        (user_id, key),
    ).fetchone()
    if row is None:
        return None
    if row["body_hash"] != body_hash:
        return JSONResponse(
            status_code=409,
            content={"error": {"code": "idempotency_conflict", "message": "幂等键已被另一内容使用"}},
        )
    return JSONResponse(status_code=row["status_code"], content=json.loads(row["response_json"]))


def _store_idempotent(conn, user_id: str, key: str | None, body_hash: str, status: int, payload: dict) -> None:
    if not key:
        return
    conn.execute(
        """
        INSERT OR IGNORE INTO idempotency(user_id, key, body_hash, status_code, response_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, key, body_hash, status, json.dumps(payload, ensure_ascii=False), iso()),
    )


def mount_pages(app: FastAPI, settings: Settings) -> None:
    @app.get("/")
    def index():
        return FileResponse(settings.web_dir / "index.html")

    @app.get("/styles.css")
    def styles():
        return FileResponse(settings.web_dir / "styles.css")

    @app.get("/extra.css")
    def extra():
        return FileResponse(settings.web_dir / "extra.css")

    @app.get("/app.js")
    def app_js():
        return FileResponse(settings.web_dir / "app.js")

    @app.get("/input_rules.js")
    def rules():
        return FileResponse(settings.web_dir / "input_rules.js")

    @app.get("/stream_state.js")
    def stream_state():
        return FileResponse(settings.web_dir / "stream_state.js")

    allowed = {"index.html", "styles.css", "app.js"}

    @app.get("/prototype-snapshot/{name}")
    def prototype(name: str):
        if name not in allowed:
            return JSONResponse(status_code=404, content={"error": {"code": "not_found", "message": "没有这个对照文件"}})
        return FileResponse(settings.prototype_dir / name)
