"""Stable repository identity and local root aliases."""

from __future__ import annotations

import hashlib
import re
import subprocess
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .db import Database


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", check=False, timeout=20)
    return result.stdout.strip() if result.returncode == 0 else ""


def repository_key(root: Path) -> tuple[str | None, str | None]:
    remote = _git(root, "remote", "get-url", "origin")
    if remote:
        normalized = re.sub(r"^[^@/]+@([^:]+):", r"https://\1/", remote.strip())
        parsed = urlsplit(normalized)
        if parsed.scheme and parsed.netloc:
            normalized = urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))
        normalized = normalized.removesuffix(".git").rstrip("/").lower()
        return f"remote:{normalized}", normalized
    initial = _git(root, "rev-list", "--max-parents=0", "HEAD").splitlines()
    return (f"initial:{initial[0]}", None) if initial else (None, None)


def ensure_project(db: Database, root: Path, name: str, timestamp: str) -> str:
    key, remote = repository_key(root)
    with db.connect() as connection:
        alias = connection.execute("SELECT project_id FROM project_roots WHERE local_root = ?",
                                   (str(root),)).fetchone()
        if alias:
            project_id = alias["project_id"]
        else:
            existing = connection.execute("SELECT id FROM projects WHERE repository_key = ?",
                                          (key,)).fetchone() if key else None
            project_id = existing["id"] if existing else (
                "P-" + hashlib.sha256(key.encode()).hexdigest()[:12] if key else "P-" + uuid.uuid4().hex[:12]
            )
            connection.execute("INSERT OR IGNORE INTO projects VALUES (?, ?, ?, ?, ?, ?)",
                               (project_id, name, key, remote, timestamp, timestamp))
        connection.execute("INSERT INTO project_roots VALUES (?, ?, ?) "
                           "ON CONFLICT(local_root) DO UPDATE SET project_id=excluded.project_id, last_seen_at=excluded.last_seen_at",
                           (project_id, str(root), timestamp))
        connection.execute("UPDATE projects SET updated_at = ?, name = ? WHERE id = ?",
                           (timestamp, name, project_id))
    return project_id
