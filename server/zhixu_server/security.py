"""Argon2id、会话 Cookie、CSRF 与登录限速。"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from argon2.low_level import Type

from zhixu_server.config import Settings

# 交互式登录用的 Argon2id 参数。不是明文，也不是已通过安全验收的证明。
HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
DUMMY_HASH = HASHER.hash("dummy-password-not-used")

SESSION_COOKIE = "zhixu_session"
CSRF_COOKIE = "zhixu_csrf"
LOGIN_LIMIT = 8
LOGIN_WINDOW_SECONDS = 15 * 60
IP_LIMIT = 30


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or now()).isoformat()


def hash_password(password: str) -> str:
    return HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return HASHER.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_id() -> str:
    return secrets.token_hex(16)


def rate_limited(conn: sqlite3.Connection, bucket: str, limit: int, window: int = LOGIN_WINDOW_SECONDS) -> bool:
    cutoff = iso(now() - timedelta(seconds=window))
    conn.execute("DELETE FROM login_attempts WHERE created_at < ?", (cutoff,))
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM login_attempts WHERE bucket = ? AND created_at >= ?",
        (bucket, cutoff),
    ).fetchone()
    return int(row["n"]) >= limit


def record_failure(conn: sqlite3.Connection, bucket: str) -> None:
    conn.execute(
        "INSERT INTO login_attempts(bucket, created_at) VALUES (?, ?)",
        (bucket, iso()),
    )


def origin_ok(settings: Settings, origin: str | None, referer: str | None) -> bool:
    candidates = []
    if origin:
        candidates.append(origin.strip().rstrip("/"))
    elif referer:
        # 只取来源站点，不记录路径里的查询内容
        parts = referer.split("/", 3)
        if len(parts) >= 3:
            candidates.append(parts[0] + "//" + parts[2])
    return any(item in settings.allowed_origins for item in candidates)


def cookie_kwargs(settings: Settings, httponly: bool) -> dict:
    return {
        "httponly": httponly,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "path": "/",
        "max_age": settings.session_ttl_hours * 3600,
    }
