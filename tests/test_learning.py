from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from learning_mcp.config import Settings
from learning_mcp.learning import daily_packet, store_daily
from learning_mcp.learning_notes import write_concept
from learning_mcp.obsidian import export_review
from learning_mcp.redaction import ignored, redact_text
from learning_mcp.schemas import validate_daily, validate_feature_review
from learning_mcp.service import LearningService
from learning_mcp.worker import run_once


class LearningPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root = base / "repo"
        self.root.mkdir()
        self.vault = base / "vault"
        self.vault.mkdir()
        def git(*args):
            subprocess.run(["git", "-C", str(self.root), *args], check=True, capture_output=True)
        git("init", "-q")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        (self.root / "app.py").write_text("print('ok')\n", encoding="utf-8")
        git("add", ".")
        git("commit", "-qm", "initial")
        self.service = LearningService(Settings(base, base / "learning.db", self.root, self.vault, base))
        self.feature = self.service.start_feature("학습 테스트", "Test daily learning", [], [], [],
                                                  project_root=str(self.root))
        self.project_id = self.feature["project_id"]
        self.day = self.feature["started_at"][:10]

    def response(self, ref):
        return {
            "summary": "SQLite 큐를 구현했다.",
            "decisions": [{"title": "SQLite 선택", "summary": "로컬 큐를 선택했다.",
                           "user_reasoning": "작은 규모에 적합하다.", "evidence_refs": [ref]}],
            "development_concepts": [{"name": "Background Worker", "canonical_id": "dev.background.worker",
                                      "explanation": "큐에서 작업을 가져와 처리한다.",
                                      "why_it_appeared": "세션 동기화를 분리했다.",
                                      "related_concepts": ["Queue"], "evidence_refs": [ref]}],
            "cs_concepts": [{"name": "Producer Consumer", "canonical_id": "cs.concurrency.producer-consumer",
                             "explanation": "생산과 소비를 분리한다.",
                             "connection_to_today": "MCP와 Worker가 분리됐다.",
                             "related_concepts": ["Queue"], "evidence_refs": [ref]}],
            "weaknesses": [{"concept": "Queue", "reason": "사용자 설명이 부족했다.",
                            "confidence": 0.7, "evidence_refs": [ref]}],
            "review_candidates": ["Queue"],
        }

    def test_real_obsidian_writer_via_worker_and_preserve_notes(self):
        packet, refs = daily_packet(self.service.db, self.project_id, self.day)
        self.assertTrue(packet["events"])
        ref = next(iter(refs))
        queued = self.service.request_daily_review(str(self.root), self.day)
        with patch("learning_mcp.worker.GeminiClient") as client:
            client.return_value.generate.return_value = self.response(ref)
            self.assertTrue(run_once(self.service))
        with self.service.db.connect() as connection:
            job = connection.execute("SELECT status FROM jobs WHERE id=?", (queued["job_id"],)).fetchone()
            row = connection.execute("SELECT obsidian_path FROM daily_reviews").fetchone()
            concepts = connection.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        self.assertEqual(job["status"], "completed")
        self.assertEqual(concepts, 2)
        daily = self.vault / row["obsidian_path"]
        self.assertTrue(daily.is_file())
        self.assertIn("Producer Consumer", daily.read_text(encoding="utf-8"))
        concept = self.vault / "dev/concepts/cs/concurrency/producer-consumer.md"
        self.assertTrue(concept.is_file())
        concept.write_text(concept.read_text(encoding="utf-8") + "\nMy personal note\n", encoding="utf-8")
        write_concept(self.vault, self.response(ref)["cs_concepts"][0] | {
            "id": "cs.concurrency.producer-consumer", "type": "cs", "connection": "두 번째 사용",
        }, self.day)
        self.assertIn("My personal note", concept.read_text(encoding="utf-8"))
        self.assertIn("두 번째 사용", concept.read_text(encoding="utf-8"))
        store_daily(self.service.db, self.project_id, self.day, self.response(ref), refs, self.vault)
        with self.service.db.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM daily_reviews").fetchone()[0], 1)

    def test_validation_rejects_hallucinated_refs_and_concepts(self):
        response = self.response("event:1")
        with self.assertRaisesRegex(ValueError, "unknown evidence ref"):
            validate_daily(response, set())
        response["cs_concepts"][0]["canonical_id"] = "../escape"
        with self.assertRaisesRegex(ValueError, "invalid concept id"):
            validate_daily(response, {"event:1"})
        with self.assertRaisesRegex(ValueError, "ownership"):
            validate_feature_review({"summary": "x", "code_flow": "x", "ownership": {}}, set())

    def test_secret_redaction(self):
        text = "password=verysecret123 Bearer abcdefghijklmnopqrstuvwxyz"
        redacted = redact_text(text)
        self.assertNotIn("verysecret123", redacted)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz", redacted)
        (self.root / ".learningignore").write_text("private-data/*\n", encoding="utf-8")
        self.assertTrue(ignored("private-data/user.json", self.root))

    def test_review_verification_requires_user_confirmation(self):
        with self.assertRaisesRegex(ValueError, "confirmation ref"):
            self.service.save_feature_review(self.feature["id"], "x", "x", {}, [], [], [], verified=True)
        confirmation = self.service.record_review_confirmation(self.feature["id"], "I understand the code flow")
        saved = self.service.save_feature_review(self.feature["id"], "x", "x", {}, [], [], [],
                                                 verified=True, verification_ref=confirmation["ref"])
        self.assertTrue(saved["verified"])

    def test_decision_gate_and_concept_learning_state(self):
        with patch("learning_mcp.gemini_client.GeminiClient.generate", return_value={
            "should_ask_user": True, "importance": 85,
            "reason": "Architecture", "question": "Why use SQLite?",
        }):
            result = self.service.evaluate_decision_candidate(
                self.feature["id"], "Choose a queue", architecture_related=True,
                hard_to_reverse=True, affects_data_model=True)
        self.assertEqual(len(self.service.get_pending_questions(self.feature["id"])), 1)
        answer = self.service.record_user_answer(result["question_id"], "Local first needs no server")
        self.assertEqual(answer["ref"], f"answer:{result['question_id']}")
        self.assertEqual(self.service.get_pending_questions(self.feature["id"]), [])

    def test_worker_retries_invalid_gemini_json_without_writing_note(self):
        queued = self.service.request_daily_review(str(self.root), self.day)
        with patch("learning_mcp.worker.GeminiClient") as client:
            client.return_value.generate.return_value = {"summary": "Only summary"}
            self.assertTrue(run_once(self.service))
        with self.service.db.connect() as connection:
            job = connection.execute("SELECT status, retry_count FROM jobs WHERE id=?",
                                     (queued["job_id"],)).fetchone()
            reviews = connection.execute("SELECT COUNT(*) FROM daily_reviews").fetchone()[0]
        self.assertEqual((job["status"], job["retry_count"]), ("pending", 1))
        self.assertEqual(reviews, 0)

    def test_feature_review_export_preserves_user_text(self):
        feature = self.service._feature(self.feature["id"])
        relative, _ = export_review(self.vault, feature, "---\ntype: feature-review\n---\n\n# First")
        path = self.vault / relative
        path.write_text(path.read_text(encoding="utf-8") + "\nPersonal note\n", encoding="utf-8")
        export_review(self.vault, feature, "---\ntype: feature-review\n---\n\n# Second")
        content = path.read_text(encoding="utf-8")
        self.assertIn("# Second", content)
        self.assertNotIn("# First", content)
        self.assertIn("Personal note", content)

    def test_short_concept_id_has_normal_filename(self):
        path = write_concept(self.vault, {"id": "dev.job-queue", "type": "dev", "name": "Job Queue",
                                          "explanation": "작업을 저장한다", "connection": "Worker가 사용한다",
                                          "related_concepts": [], "evidence_refs": []}, self.day)
        self.assertEqual(path, "dev/concepts/development/general/job-queue.md")
        self.assertTrue((self.vault / path).is_file())


if __name__ == "__main__":
    unittest.main()
