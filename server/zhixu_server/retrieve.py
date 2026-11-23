"""检索只命中当前用户、当前会话、已启用、版本一致且未删除的原文块。"""

from __future__ import annotations

import sqlite3

from zhixu_server.textutil import fts_query


def search_chunks(
    conn: sqlite3.Connection,
    *,
    owner_user_id: str,
    conversation_id: str,
    query: str,
    limit: int = 8,
) -> list[sqlite3.Row]:
    match = fts_query(query)
    if not match:
        return []
    return list(
        conn.execute(
            """
            SELECT c.id, c.text, c.file_id, c.version, c.page, c.paragraph,
                   c.offset, c.length, c.fts_lex
            FROM chunks_fts
            JOIN chunks c ON c.id = chunks_fts.chunk_id
            JOIN files f ON f.id = c.file_id AND f.version = c.version
            JOIN conversation_files cf
              ON cf.file_id = c.file_id AND cf.version = c.version
            WHERE chunks_fts MATCH ?
              AND cf.conversation_id = ?
              AND cf.owner_user_id = ?
              AND cf.enabled = 1
              AND f.owner_user_id = ?
              AND c.owner_user_id = ?
              AND f.deleted_at IS NULL
            LIMIT ?
            """,
            (match, conversation_id, owner_user_id, owner_user_id, owner_user_id, limit),
        )
    )
