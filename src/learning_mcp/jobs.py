"""Transactional SQLite queue shared by MCP and worker processes."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .db import Database


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def enqueue(db: Database, job_type: str, payload: dict[str, Any], *,
            project_id: str | None = None, feature_id: str | None = None,
            priority: int = 50, dedupe_key: str | None = None) -> int:
    with db.connect() as connection:
        try:
            cursor = connection.execute(
                "INSERT INTO jobs(job_type, project_id, feature_id, payload_json, priority, created_at, dedupe_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (job_type, project_id, feature_id, json.dumps(payload, ensure_ascii=False), priority, now(), dedupe_key),
            )
            return int(cursor.lastrowid)
        except sqlite3.IntegrityError:
            if dedupe_key is None:
                raise
            row = connection.execute(
                "SELECT id FROM jobs WHERE dedupe_key = ? AND status IN ('pending', 'running')",
                (dedupe_key,),
            ).fetchone()
            if row is None:
                raise
            return int(row["id"])


def claim(db: Database) -> dict[str, Any] | None:
    with db.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM jobs WHERE status = 'pending' ORDER BY priority DESC, created_at, id LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        connection.execute("UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
                           (now(), row["id"]))
        return dict(row) | {"status": "running"}


def complete(db: Database, job_id: int) -> None:
    with db.connect() as connection:
        connection.execute("UPDATE jobs SET status = 'completed', finished_at = ?, error = NULL "
                           "WHERE id = ? AND status = 'running'", (now(), job_id))


def fail(db: Database, job_id: int, error: str) -> None:
    with db.connect() as connection:
        connection.execute(
            "UPDATE jobs SET retry_count = retry_count + 1, "
            "status = CASE WHEN retry_count + 1 >= max_retries THEN 'failed' ELSE 'pending' END, "
            "error = ?, started_at = NULL, finished_at = CASE WHEN retry_count + 1 >= max_retries THEN ? ELSE NULL END "
            "WHERE id = ? AND status = 'running'", (error[:2000], now(), job_id),
        )


def recover_stale(db: Database, before: str) -> int:
    with db.connect() as connection:
        cursor = connection.execute(
            "UPDATE jobs SET retry_count = retry_count + 1, "
            "status = CASE WHEN retry_count + 1 >= max_retries THEN 'failed' ELSE 'pending' END, "
            "error = 'worker interrupted', started_at = NULL "
            "WHERE status = 'running' AND started_at < ?", (before,),
        )
        return cursor.rowcount
