"""Reduce accidental secret exposure in Gemini evidence packets."""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_IGNORES = (".env", ".env.*", "*.pem", "*.key", "secrets/*", "credentials/*", "private/*")
SECRET = "[REDACTED_SECRET]"
PATTERNS = (
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/-]{12,}"),
    re.compile(r"(?i)\b((?:api[_-]?key|token|password|secret|cookie)\s*[:=]\s*)[\"']?[^\s\"',;]{6,}"),
    re.compile(r"\b(?:ghp|github_pat|sk)-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^\s\"']+"),
)


def ignored(path: str, root: Path | None = None) -> bool:
    rules = list(DEFAULT_IGNORES)
    if root:
        config = root / ".learningignore"
        if config.is_file():
            rules.extend(line.strip() for line in config.read_text(encoding="utf-8").splitlines()
                         if line.strip() and not line.lstrip().startswith("#"))
    normalized = path.replace("\\", "/").lstrip("./")
    return any(fnmatch.fnmatch(normalized, pattern) or
               fnmatch.fnmatch(normalized.split("/")[-1], pattern) for pattern in rules)


def redact_text(value: str) -> str:
    result = value
    for pattern in PATTERNS:
        result = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + SECRET, result)
    return result


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        return {key: (SECRET if re.search(r"(?i)(?:password|secret|token|api_key|cookie)", key)
                      else redact(item)) for key, item in value.items()}
    return value


def safe_json(value: Any) -> str:
    return json.dumps(redact(value), ensure_ascii=False, separators=(",", ":"))
