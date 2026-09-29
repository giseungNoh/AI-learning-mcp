from __future__ import annotations

import subprocess
import json
import tempfile
import unittest
from pathlib import Path

from learning_mcp import jobs
from learning_mcp.config import Settings
from learning_mcp.service import LearningService
from learning_mcp.worker import run_once


class PhaseOneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / "repository"
        self.root.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        (self.root / "app.py").write_text("first\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "initial")
        self.service = LearningService(Settings(base, base / "learning.db", self.root, None, base))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True, encoding="utf-8").stdout.strip()

    def feature(self):
        return self.service.start_feature("Change", "Capture evidence", [], [], [], project_root=str(self.root))

    def test_committed_and_worktree_evidence_is_immutable(self):
        feature = self.feature()
        (self.root / "app.py").write_text("second\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "feature commit")
        (self.root / "app.py").write_text("third\n", encoding="utf-8")
        (self.root / "new.txt").write_text("untracked\n", encoding="utf-8")
        self.service.finish_feature(feature["id"])
        before = self.service.get_evidence(feature["id"],
                                           ["git:feature-diff", "git:working-final", "git:untracked-final"])
        self.assertIn("+second", before["items"][0]["content"])
        self.assertIn("+third", before["items"][1]["content"])
        self.assertIn("new.txt", before["items"][2]["content"])
        (self.root / "app.py").write_text("fourth\n", encoding="utf-8")
        self.git("add", ".")
        self.git("commit", "-qm", "later commit")
        after = self.service.get_evidence(feature["id"],
                                          ["git:feature-diff", "git:working-final", "git:untracked-final"])
        self.assertEqual(before["items"], after["items"])
        with self.assertRaisesRegex(ValueError, "already completed"):
            self.service.finish_feature(feature["id"])
        with self.assertRaisesRegex(ValueError, "active feature"):
            self.service.record_decision(feature["id"], "Q", "A", "R", [], "human")

    def test_project_identity_survives_root_move(self):
        first = self.service.get_project_context(str(self.root))["project_id"]
        moved = self.root.with_name("moved")
        self.root.rename(moved)
        self.root = moved
        second = self.service.get_project_context(str(self.root))["project_id"]
        self.assertEqual(first, second)

    def test_queue_dedup_retry_and_worker(self):
        feature = self.feature()
        session = Path(self.temp.name) / "session.jsonl"
        session.write_text(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 1, "cached_input_tokens": 0,
                                  "output_tokens": 1, "reasoning_output_tokens": 0, "total_tokens": 2}
        }}}) + "\n", encoding="utf-8")
        first = self.service.request_session_sync(feature["id"], str(session))
        second = self.service.request_session_sync(feature["id"], str(session))
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertTrue(run_once(self.service))
        with self.service.db.connect() as connection:
            row = connection.execute("SELECT status, error FROM jobs WHERE id = ?", (first["job_id"],)).fetchone()
        self.assertEqual(row["status"], "completed", row["error"])
        failing = jobs.enqueue(self.service.db, "unknown", {}, feature_id=feature["id"])
        for _ in range(3):
            self.assertTrue(run_once(self.service))
        with self.service.db.connect() as connection:
            row = connection.execute("SELECT status, retry_count FROM jobs WHERE id = ?", (failing,)).fetchone()
        self.assertEqual((row["status"], row["retry_count"]), ("failed", 3))

    def test_session_cursor_only_advances_past_complete_lines(self):
        feature = self.feature()
        session = Path(self.temp.name) / "cursor.jsonl"
        token = {"type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}}}
        session.write_text(json.dumps(token) + "\n", encoding="utf-8")
        self.service.sync_codex_session(feature["id"], str(session), "start")
        message = json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Hello"}})
        with session.open("a", encoding="utf-8") as handle:
            handle.write(message[:10])
        first = self.service.sync_codex_session(feature["id"], str(session), "update")
        self.assertEqual(first["conversation_events_imported"], 0)
        with session.open("a", encoding="utf-8") as handle:
            handle.write(message[10:] + "\n")
        second = self.service.sync_codex_session(feature["id"], str(session), "update")
        third = self.service.sync_codex_session(feature["id"], str(session), "update")
        self.assertEqual(second["conversation_events_imported"], 1)
        self.assertEqual(third["conversation_events_imported"], 0)
        with self.service.db.connect() as connection:
            row = connection.execute("SELECT latest_byte FROM sessions WHERE feature_id=?", (feature["id"],)).fetchone()
        self.assertEqual(row["latest_byte"], session.stat().st_size)


if __name__ == "__main__":
    unittest.main()
