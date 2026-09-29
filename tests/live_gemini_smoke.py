"""Manual live Gemini smoke test. Writes only to a temporary repo and Vault."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from learning_mcp.config import Settings
from learning_mcp.service import LearningService
from learning_mcp.worker import run_once


def main() -> None:
    with tempfile.TemporaryDirectory() as scratch:
        base = Path(scratch)
        root = base / "repo"
        vault = base / "vault"
        root.mkdir()
        vault.mkdir()
        def git(*args: str) -> None:
            subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
        git("init", "-q")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        (root / "app.py").write_text("print('start')\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-qm", "initial")
        service = LearningService(Settings(base, base / "learning.db", root, vault, base))
        feature = service.start_feature("SQLite 작업 큐", "개발 중 세션 동기화를 비동기로 처리한다",
                                        ["MCP 호출이 즉시 돌아온다"], [], [], project_root=str(root))
        service.record_decision(feature["id"], "Redis와 SQLite 중 어떤 큐를 선택할까?", "SQLite",
                                "개인용 로컬 앱이라 별도 Redis 서버는 필요하지 않다", ["Redis"], "human")
        service.record_debug_attempt(feature["id"], "동일 작업이 두 번 실행됨", ["중복 enqueue"],
                                     "dedupe key로 조회", "중복 작업 하나로 합쳐짐", "resolved")
        (root / "app.py").write_text("print('worker')\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-qm", "add worker")
        service.finish_feature(feature["id"])
        queued = service.request_daily_review(str(root), feature["started_at"][:10])
        run_once(service)
        feature_job = service.request_feature_review(feature["id"])
        run_once(service)
        with service.db.connect() as connection:
            job = connection.execute("SELECT status, error FROM jobs WHERE id=?", (queued["job_id"],)).fetchone()
            feature_status = connection.execute("SELECT status, error FROM jobs WHERE id=?",
                                                (feature_job["job_id"],)).fetchone()
            review = connection.execute("SELECT obsidian_path, result_json FROM daily_reviews").fetchone()
            feature_review = connection.execute("SELECT obsidian_path FROM reviews WHERE feature_id=?",
                                                (feature["id"],)).fetchone()
        result = {"status": job["status"], "error": job["error"]}
        if review:
            result["note_exists"] = (vault / review["obsidian_path"]).is_file()
            result["concept_count"] = len(json.loads(review["result_json"])["concepts"])
        result["feature_status"] = feature_status["status"]
        result["feature_error"] = feature_status["error"]
        result["feature_note_exists"] = bool(feature_review and feature_review["obsidian_path"] and
                                              (vault / feature_review["obsidian_path"]).is_file())
        print(json.dumps(result, ensure_ascii=False))
        if result["status"] != "completed" or not result.get("note_exists") or \
                result["feature_status"] != "completed" or not result["feature_note_exists"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
