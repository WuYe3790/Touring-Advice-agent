from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "travel_agent.db"


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                text TEXT NOT NULL,
                meta_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_updated_at ON conversations(updated_at)")


def make_title(text: str) -> str:
    compact = " ".join(text.strip().split())
    if not compact:
        return "新会话"
    return compact[:24] + ("..." if len(compact) > 24 else "")


def create_conversation(title: str | None = None) -> dict[str, Any]:
    now = utc_now()
    conversation_id = uuid.uuid4().hex
    title = title or "新会话"
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (conversation_id, title, now, now),
        )
    return {"id": conversation_id, "title": title, "created_at": now, "updated_at": now}


def ensure_conversation(conversation_id: str | None, title_hint: str = "") -> str:
    if conversation_id:
        with get_connection() as conn:
            row = conn.execute("SELECT id FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
            if row:
                return conversation_id
    return create_conversation(make_title(title_hint))["id"]


def list_conversations(limit: int = 50) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at, COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_messages(conversation_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    query = "SELECT id, role, text, meta_json, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC"
    params: tuple[Any, ...] = (conversation_id,)
    if limit is not None:
        query = (
            "SELECT id, role, text, meta_json, created_at FROM ("
            "SELECT id, role, text, meta_json, created_at FROM messages WHERE conversation_id = ? "
            "ORDER BY id DESC LIMIT ?) ORDER BY id ASC"
        )
        params = (conversation_id, limit)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    messages = []
    for row in rows:
        item = dict(row)
        item["meta"] = json.loads(item.pop("meta_json") or "{}")
        messages.append(item)
    return messages


def add_message(
    conversation_id: str,
    role: str,
    text: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages(conversation_id, role, text, meta_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (conversation_id, role, text, meta_json, now),
        )
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        message_id = cursor.lastrowid
    return {"id": message_id, "role": role, "text": text, "meta": meta or {}, "created_at": now}


def maybe_update_title(conversation_id: str, title_hint: str) -> None:
    title = make_title(title_hint)
    with get_connection() as conn:
        row = conn.execute("SELECT title FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if row and row["title"] == "新会话":
            conn.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", (title, utc_now(), conversation_id))


def delete_conversation(conversation_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return cursor.rowcount > 0
