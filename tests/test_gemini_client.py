from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from learning_mcp.gemini_client import OfficialDocsClient


class OfficialDocsClientTests(unittest.TestCase):
    def test_uses_sandboxed_antigravity_search_without_url_reads(self) -> None:
        envelope = {
            "event": "result",
            "result": {
                "status": "SUCCESS",
                "structured_output": {"sources": []},
            },
        }
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(envelope) + "\n", stderr=""
        )
        with tempfile.TemporaryDirectory() as raw_root, patch(
            "learning_mcp.gemini_client.subprocess.run", return_value=completed
        ) as run:
            output = OfficialDocsClient(executable="agy").generate(
                "Find official docs.",
                {"topics": [{"key": "swift", "label": "Swift Optional"}]},
                Path(raw_root),
                {"type": "object"},
                web_search=True,
            )

        self.assertEqual(output, {"sources": []})
        command = run.call_args.args[0]
        self.assertIn("--sandbox", command)
        self.assertNotIn("--dangerously-skip-permissions", command)
        prompt_event = json.loads(run.call_args.kwargs["input"].strip())
        prompt = prompt_event["message"]["content"]
        self.assertIn("Use only search_web", prompt)
        self.assertIn("Do not open URLs", prompt)


if __name__ == "__main__":
    unittest.main()
