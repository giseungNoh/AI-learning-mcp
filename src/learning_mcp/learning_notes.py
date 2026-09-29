"""Deterministic Obsidian writers that preserve text outside generated blocks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .obsidian import _filename_slug

START = "<!-- learning-mcp:start -->"
END = "<!-- learning-mcp:end -->"


def _safe_write(vault: Path, relative: Path, heading: str, body: str) -> str:
    root = vault.resolve()
    destination = (root / relative).resolve()
    if root not in destination.parents:
        raise ValueError("Obsidian path escapes vault")
    destination.parent.mkdir(parents=True, exist_ok=True)
    generated = f"{START}\n{body.rstrip()}\n{END}"
    if destination.exists():
        old = destination.read_text(encoding="utf-8")
        if START in old and END in old and old.index(START) < old.index(END):
            before, rest = old.split(START, 1)
            _, after = rest.split(END, 1)
            content = before + generated + after
        else:
            content = old.rstrip() + "\n\n" + generated + "\n"
    else:
        content = heading + "\n\n" + generated + "\n"
    destination.write_text(content, encoding="utf-8")
    return relative.as_posix()


def write_daily(vault: Path, project: str, review_date: str, result: dict[str, Any]) -> str:
    relative = Path("dev/daily") / review_date[:4] / f"{review_date}-{_filename_slug(project)}.md"
    heading = (f"---\ntype: daily-development-learning\ndate: {json.dumps(review_date)}\n"
               f"project: {json.dumps(project, ensure_ascii=False)}\n---\n\n# {review_date} 개발 학습")
    lines = ["## 오늘 개발한 것", "", result["summary"], "", "## 내가 직접 내린 결정", ""]
    for item in result["decisions"]:
        lines.extend([f"### {item['title']}", "", item["summary"], "",
                      item["user_reasoning"] or "사용자 판단 근거 미기록", "",
                      "근거: " + ", ".join(item["evidence_refs"]), ""])
    lines.extend(["## 오늘 등장한 개발 개념", ""])
    lines.extend(f"- [[{item['name']}]]" for item in result["concepts"] if item["type"] == "dev")
    lines.extend(["", "## 연결된 CS 개념", ""])
    lines.extend(f"- [[{item['name']}]]" for item in result["concepts"] if item["type"] == "cs")
    lines.extend(["", "## 다시 볼 내용", ""])
    lines.extend(f"- {item}" for item in result["review_candidates"])
    return _safe_write(vault, relative, heading, "\n".join(lines))


def write_concept(vault: Path, concept: dict[str, Any], review_date: str) -> str:
    cid = concept["id"]
    parts = cid.split(".")
    kind = "cs" if concept["type"] == "cs" else "development"
    category = parts[1] if len(parts) > 2 else "general"
    filename = "-".join(parts[2:]) if len(parts) > 2 else parts[1]
    relative = Path("dev/concepts") / kind / category / f"{filename}.md"
    heading = (f"---\ntype: {json.dumps(concept['type'] + '-concept')}\n"
               f"concept_id: {json.dumps(cid)}\nfirst_seen: {json.dumps(review_date)}\n---\n\n"
               f"# {concept['name']}")
    body = ("## 핵심 개념\n\n" + concept["explanation"] + "\n\n## 프로젝트와 연결\n\n"
            + concept["connection"] + "\n\n## 관련 개념\n\n"
            + "\n".join(f"- [[{name}]]" for name in concept["related_concepts"])
            + "\n\n## 실제 사용 기록\n\n" + "\n".join(f"- {ref}" for ref in concept["evidence_refs"]))
    return _safe_write(vault, relative, heading, body)
