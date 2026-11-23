"""SQLite WAL 存储。解析任务和请求事件都落在库里，不只用内存队列。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from zhixu_server.config import Settings

_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    user_id TEXT NOT NULL,
    csrf_token TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bucket TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    model TEXT,
    request_id TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    user_message_id TEXT,
    withdrawn_reason TEXT,
    material INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS message_sources (
    message_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    PRIMARY KEY (message_id, file_id, version)
);
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    hash TEXT NOT NULL,
    name TEXT NOT NULL,
    mime TEXT NOT NULL,
    size INTEGER NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    object_key TEXT NOT NULL,
    error_code TEXT,
    page_count INTEGER,
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS conversation_files (
    conversation_id TEXT NOT NULL,
    file_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    owner_user_id TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (conversation_id, file_id, version)
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    owner_user_id TEXT NOT NULL,
    page INTEGER,
    paragraph INTEGER,
    offset INTEGER NOT NULL,
    length INTEGER NOT NULL,
    text TEXT NOT NULL,
    fts_lex TEXT NOT NULL,
    fts_rowid INTEGER
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    fts_lex,
    chunk_id UNINDEXED
);
CREATE TABLE IF NOT EXISTS citations (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    claim_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    quote TEXT NOT NULL,
    file_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    page INTEGER,
    paragraph INTEGER,
    offset INTEGER,
    length INTEGER,
    verified_at TEXT
);
CREATE TABLE IF NOT EXISTS parse_jobs (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    progress INTEGER NOT NULL,
    error_code TEXT,
    attempts INTEGER NOT NULL,
    worker_pid INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS file_status_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    user_message_id TEXT NOT NULL,
    assistant_message_id TEXT NOT NULL,
    status TEXT NOT NULL,
    last_event_id INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    upstream_started INTEGER NOT NULL DEFAULT 0,
    finalized INTEGER NOT NULL DEFAULT 0,
    abort_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS request_events (
    request_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (request_id, seq)
);
CREATE TABLE IF NOT EXISTS idempotency (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    body_hash TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE INDEX IF NOT EXISTS idx_conv_owner ON conversations(owner_user_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_req_conv ON requests(conversation_id, status);
"""


def lock():
    return _LOCK


def connect(settings: Settings) -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.objects_dir.mkdir(parents=True, exist_ok=True)
    marker = settings.data_dir / "ZHIXU_DATA_MARKER"
    if not marker.exists():
        marker.write_text("zhixu-data\n", encoding="utf-8")
    conn = sqlite3.connect(settings.db_path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(settings: Settings) -> None:
    conn = connect(settings)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
    finally:
        conn.close()


def db_path_of(settings: Settings) -> Path:
    return settings.db_path
