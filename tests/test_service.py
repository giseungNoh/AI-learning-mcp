from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from learning_mcp.codex_usage import latest_usage, usage_delta
from learning_mcp.config import Settings
from learning_mcp.obsidian import _filename_slug
from learning_mcp.service import LearningService


def token_event(input_tokens: int, cached: int, output: int, reasoning: int) -> str:
    total = input_tokens + output
    return json.dumps(
        {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": input_tokens,
                        "cached_input_tokens": cached,
                        "output_tokens": output,
                        "reasoning_output_tokens": reasoning,
                        "total_tokens": total,
                    }
                },
            },
        }
    )


def message_event(role: str, message: str) -> str:
    event_type = "user_message" if role == "user" else "agent_message"
    return json.dumps(
        {
            "timestamp": "2026-08-25T00:00:00Z",
            "type": "event_msg",
            "payload": {"type": event_type, "message": message},
        }
    )


class LearningServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.project = base / "sample-project"
        self.project.mkdir()
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(self.project), "config", "user.name", "Test"], check=True)
        (self.project / "app.py").write_text("print('start')\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.project), "add", "app.py"], check=True)
        subprocess.run(["git", "-C", str(self.project), "commit", "-qm", "initial"], check=True)
        self.vault = base / "vault"
        self.vault.mkdir()
        settings = Settings(
            home=base,
            db_path=base / "learning.db",
            project_root=self.project,
            obsidian_vault=self.vault,
            codex_session_root=base,
        )
        self.service = LearningService(settings)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def start(self) -> dict:
        return self.service.start_feature(
            title="Token collector",
            goal="Collect Codex token deltas",
            success_conditions=["Delta is exact"],
            user_owned_scope=["Aggregation rule"],
            ai_allowed_scope=["Boilerplate"],
            project_name="learning-mcp",
            project_root=str(self.project),
        )

    def test_feature_review_flow_and_obsidian_export(self) -> None:
        feature = self.start()
        feature_id = feature["id"]
        decision = self.service.record_decision(
            feature_id,
            "Where should token state live?",
            "SQLite",
            "Need local durable storage",
            ["JSONL", "Postgres"],
            "human",
        )
        debug = self.service.record_debug_attempt(
            feature_id,
            "Cumulative tokens were double-counted",
            ["Snapshots were summed"],
            "Compare end minus baseline",
            "Delta matched",
            "resolved",
        )

        session = Path(self.temp.name) / "rollout-test.jsonl"
        session.write_text(token_event(100, 40, 10, 2) + "\n", encoding="utf-8")
        self.service.sync_codex_session(feature_id, str(session), "start")
        with session.open("a", encoding="utf-8") as handle:
            handle.write(message_event("user", "I choose SQLite because this is local-first.") + "\n")
            handle.write(message_event("assistant", "I will implement the repository boundary.") + "\n")
            handle.write(token_event(180, 90, 30, 8) + "\n")
        synced = self.service.sync_codex_session(feature_id, str(session), "update")
        self.assertEqual(synced["usage"]["input_tokens"], 80)
        self.assertEqual(synced["usage"]["cached_input_tokens"], 50)
        self.assertEqual(synced["measurement"], "exact-feature-delta")
        self.assertEqual(synced["conversation_events_imported"], 2)

        (self.project / "app.py").write_text("print('changed')\n", encoding="utf-8")
        manifest = self.service.get_feature_manifest(feature_id)
        self.assertEqual(manifest["feature"]["user_owned_scope"], ["Aggregation rule"])
        self.assertEqual(manifest["token_usage"]["output_tokens"], 20)
        self.assertTrue(manifest["git"]["working_stat"])
        self.assertTrue(any(item["kind"] == "conversation-user" for item in manifest["evidence_index"]))

        evidence = self.service.get_evidence(
            feature_id,
            [decision["ref"], debug["ref"], "diff:working"],
            max_chars=4_000,
        )
        self.assertEqual(len(evidence["items"]), 3)
        self.assertLessEqual(evidence["characters"], 4_000)

        saved = self.service.save_feature_review(
            feature_id=feature_id,
            summary="Token deltas are stored without double counting.",
            code_flow="JSONL → parser → session delta → manifest",
            ownership={
                "requirements": "human-led",
                "architecture": "shared",
                "implementation": "ai-led-verified",
                "debugging": "human-led",
                "testing": "shared",
            },
            alternatives=["Read all logs on every review", "Store normalized snapshots"],
            weaknesses=["token-accounting"],
            next_topics=["SQLite transactions"],
            verified=True,
        )
        self.assertTrue(saved["saved"])
        self.assertTrue((self.vault / saved["obsidian_path"]).is_file())
        self.assertEqual(Path(saved["obsidian_path"]).name, "review-token-collector.md")
        note = (self.vault / saved["obsidian_path"]).read_text(encoding="utf-8")
        self.assertIn("human-led", note)
        self.assertIn("input_tokens: 80", note)

        finished = self.service.finish_feature(feature_id)
        self.assertEqual(finished["status"], "completed")
        history = self.service.get_learning_history("learning-mcp")
        self.assertEqual(history["recurring_weaknesses"], [("token-accounting", 1)])

    def test_only_one_active_feature_per_project(self) -> None:
        self.start()
        with self.assertRaisesRegex(ValueError, "already active"):
            self.start()

    def test_project_root_is_required_and_normalized(self) -> None:
        nested = self.project / "src" / "nested"
        nested.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "project_root is required"):
            self.service.start_feature(
                "Missing root", "Do not guess", ["Rejected"], ["Path"], ["None"]
            )
        feature = self.service.start_feature(
            "Nested root", "Normalize root", ["Canonical"], ["Path"], ["None"],
            project_root=str(nested),
        )
        self.assertEqual(feature["project_root"], str(self.project.resolve()))
        context = self.service.get_project_context(str(nested))
        self.assertEqual(context["active_feature"]["id"], feature["id"])

    def test_token_parser_uses_latest_cumulative_snapshot(self) -> None:
        path = Path(self.temp.name) / "tokens.jsonl"
        path.write_text(
            token_event(10, 5, 2, 1) + "\n" + token_event(30, 20, 8, 3) + "\n",
            encoding="utf-8",
        )
        latest = latest_usage(path)
        self.assertEqual(latest["total_tokens"], 38)
        delta = usage_delta(
            {
                "input_tokens": 10,
                "cached_input_tokens": 5,
                "output_tokens": 2,
                "reasoning_output_tokens": 1,
                "total_tokens": 12,
            },
            latest,
        )
        self.assertEqual(delta["total_tokens"], 26)

    def test_obsidian_filename_keeps_readable_korean_title(self) -> None:
        self.assertEqual(_filename_slug("상품 키워드 검색 API"), "상품-키워드-검색-api")
        self.assertEqual(_filename_slug("경로/오류: 수정?"), "경로-오류-수정")


if __name__ == "__main__":
    unittest.main()
