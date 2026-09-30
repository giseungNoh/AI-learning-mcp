from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from learning_mcp.autostart import LABEL, launch_agent_payload
from learning_mcp.config import Settings


class AutostartTests(unittest.TestCase):
    def test_launch_agent_contains_worker_paths_and_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vault = root / "vault"
            settings = Settings(
                root, root / "learning.db", root, vault, root / "sessions",
                obsidian_base_dir=Path("dev/learning-mcp"),
            )
            payload = launch_agent_payload(
                settings, uv_executable="/opt/uv", log_dir=root / "logs"
            )
        self.assertEqual(payload["Label"], LABEL)
        self.assertEqual(payload["ProgramArguments"][0], "/opt/uv")
        self.assertEqual(payload["ProgramArguments"][-1], "learning-mcp-worker")
        self.assertEqual(payload["EnvironmentVariables"]["LEARNING_MCP_DB"], str(root / "learning.db"))
        self.assertEqual(payload["EnvironmentVariables"]["LEARNING_MCP_OBSIDIAN_VAULT"], str(vault))
        self.assertEqual(
            payload["EnvironmentVariables"]["LEARNING_MCP_OBSIDIAN_BASE_DIR"],
            "dev/learning-mcp",
        )
        self.assertTrue(payload["RunAtLoad"])
        self.assertTrue(payload["KeepAlive"])


if __name__ == "__main__":
    unittest.main()
