"""Capture Git evidence at a feature boundary before the worktree changes."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=30, check=False)
    if result.returncode:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def capture(root: Path, baseline: str | None) -> dict[str, str]:
    end = _git(root, "rev-parse", "HEAD").strip()
    if baseline:
        commits = _git(root, "log", "--format=%H %s", f"{baseline}..{end}")
        committed = _git(root, "diff", "--binary", "--find-renames", baseline, end)
        changed = _git(root, "diff", "--name-status", "--find-renames", baseline, end)
    else:
        commits = committed = changed = ""
    untracked = _git(root, "ls-files", "--others", "--exclude-standard")
    return {
        "git:commits": commits,
        "git:feature-diff": committed,
        "git:changed-files": changed,
        "git:staged-final": _git(root, "diff", "--cached", "--binary"),
        "git:working-final": _git(root, "diff", "--binary"),
        "git:untracked-final": untracked,
        "git:end": end,
        "git:branch-final": _git(root, "branch", "--show-current").strip(),
        "git:status-final": _git(root, "status", "--short"),
    }


def baseline(root: Path) -> dict[str, str]:
    return {
        "git:baseline": _git(root, "rev-parse", "HEAD").strip(),
        "git:baseline-branch": _git(root, "branch", "--show-current").strip(),
        "git:baseline-status": _git(root, "status", "--short"),
        "git:baseline-untracked": _git(root, "ls-files", "--others", "--exclude-standard"),
    }
