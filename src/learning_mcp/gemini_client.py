"""Headless Gemini CLI boundary; model output is data, never a file operation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .redaction import safe_json


class GeminiClient:
    def __init__(self, executable: str | None = None, timeout: int = 180):
        self.backend = os.getenv("LEARNING_MCP_GEMINI_BACKEND") or (
            "agy" if shutil.which("agy") else "gemini")
        name = executable or os.getenv("LEARNING_MCP_GEMINI_EXECUTABLE", self.backend)
        self.executable = shutil.which(name) or name
        self.timeout = timeout

    def generate(self, instruction: str, packet: dict[str, Any], cwd: Path,
                 schema: dict[str, Any] | None = None) -> dict[str, Any]:
        project_settings = cwd / ".gemini" / "settings.json"
        project_settings.parent.mkdir(parents=True, exist_ok=True)
        project_settings.write_text(json.dumps({"tools": {"core": []}, "mcp": {"allowed": []},
                                                "context": {"includeDirectoryTree": False}}), encoding="utf-8")
        prompt = ("Return exactly one JSON object, without Markdown. Do not use tools or access files. "
                  "Use only the evidence JSON supplied here. Never invent evidence refs.\n\n"
                  + instruction + "\n\nEvidence:\n" + safe_json(packet))
        if self.backend == "agy":
            schema_path = cwd / "response-schema.json"
            schema_path.write_text(json.dumps(schema or {"type": "object"}), encoding="utf-8")
            command = [self.executable, "--input-format", "stream-json", "--output-format", "stream-json",
                       "--model", os.getenv("LEARNING_MCP_GEMINI_MODEL", "gemini-3.8-flash-medium"),
                       "--json-schema", str(schema_path)]
            input_text = json.dumps({"event": "user", "message": {"content": prompt}}, ensure_ascii=False) + "\n"
        else:
            command = [self.executable, "--output-format", "json", "--prompt", prompt]
            input_text = None
        try:
            result = subprocess.run(
                command,
                input=input_text,
                cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Gemini CLI unavailable: {exc}") from exc
        if result.returncode:
            raise RuntimeError(f"Gemini CLI exited {result.returncode}: {result.stderr[:1000]}")
        try:
            if self.backend == "agy":
                records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
                outcomes = [record["result"] for record in records if record.get("event") == "result"]
                envelope = outcomes[-1] if outcomes else {}
            else:
                envelope = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Gemini CLI envelope is malformed JSON at {exc.pos}") from exc
        if envelope.get("status") == "ERROR" or envelope.get("error"):
            raise RuntimeError(f"Gemini CLI error: {str(envelope.get('error'))[:1000]}")
        response = envelope.get("structured_output") or envelope.get("response")
        try:
            output = json.loads(response) if isinstance(response, str) else response
        except json.JSONDecodeError as exc:
            raise ValueError(f"Gemini response is malformed JSON at {exc.pos}") from exc
        if not isinstance(output, dict):
            raise ValueError("Gemini response must be an object "
                             f"(status={envelope.get('status')}, keys={sorted(envelope)}, "
                             f"structured={type(envelope.get('structured_output')).__name__}, "
                             f"response={type(envelope.get('response')).__name__})")
        return output
