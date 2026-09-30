"""macOS LaunchAgent support for the Learning MCP background worker."""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .config import PACKAGE_ROOT, Settings

LABEL = "com.learning-mcp.worker"


def launch_agent_payload(
    settings: Settings,
    *,
    uv_executable: str | None = None,
    log_dir: Path | None = None,
) -> dict[str, Any]:
    uv = uv_executable or shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    logs = log_dir or Path.home() / "Library/Logs/LearningMCP"
    env = {
        "LEARNING_MCP_HOME": str(settings.home),
        "LEARNING_MCP_DB": str(settings.db_path),
        "PATH": os.environ.get(
            "PATH",
            f"{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        ),
    }
    if settings.obsidian_vault:
        env["LEARNING_MCP_OBSIDIAN_VAULT"] = str(settings.obsidian_vault)
        env["LEARNING_MCP_OBSIDIAN_BASE_DIR"] = settings.obsidian_base_dir.as_posix()
    if settings.codex_session_root:
        env["LEARNING_MCP_CODEX_SESSION_ROOT"] = str(settings.codex_session_root)
    return {
        "Label": LABEL,
        "ProgramArguments": [
            uv,
            "run",
            "--directory",
            str(PACKAGE_ROOT),
            "learning-mcp-worker",
        ],
        "EnvironmentVariables": env,
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "StandardOutPath": str(logs / "worker.log"),
        "StandardErrorPath": str(logs / "worker.error.log"),
    }


def install_worker_launch_agent(
    settings: Settings | None = None,
    *,
    load: bool = True,
    uv_executable: str | None = None,
) -> dict[str, Any]:
    if os.uname().sysname != "Darwin":
        raise RuntimeError("worker autostart currently supports macOS only")
    current = settings or Settings.from_env()
    agent_dir = Path.home() / "Library/LaunchAgents"
    log_dir = Path.home() / "Library/Logs/LearningMCP"
    agent_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = agent_dir / f"{LABEL}.plist"
    with path.open("wb") as handle:
        plistlib.dump(
            launch_agent_payload(current, uv_executable=uv_executable, log_dir=log_dir),
            handle,
            sort_keys=False,
        )
    loaded = False
    if load:
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", domain, str(path)], check=False,
                       capture_output=True, text=True)
        subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
        subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], check=True)
        loaded = True
    return {"installed": True, "loaded": loaded, "label": LABEL, "path": str(path),
            "logs": str(log_dir)}
