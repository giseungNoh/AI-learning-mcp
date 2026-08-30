"""
Obsidian 내보내기 및 마크다운 렌더링 모듈입니다.

학습 회고/리뷰 결과를 YAML Frontmatter가 포함된 마크다운 문서로 변환하고,
설정된 Obsidian Vault(보관소) 디렉토리 구조에 맞춰 안전하게 파일(.md)로 저장합니다.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any


def _yaml_list(values: list[str]) -> str:
    """리스트 형태의 문자열을 YAML 대괄호 배열 형태(예: ["item1", "item2"]) 문자열로 변환합니다."""
    if not values:
        return "[]"
    escaped = [value.replace('"', '\\"') for value in values]
    return "[" + ", ".join(f'"{value}"' for value in escaped) + "]"


def _filename_slug(value: str, max_length: int = 80) -> str:
    """한글을 포함한 제목은 유지하고 경로에 부적합한 문자는 하이픈으로 바꿉니다."""
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    slug = re.sub(r"[\W_]+", "-", normalized, flags=re.UNICODE).strip("-")
    return slug[:max_length].rstrip("-") or "feature"


def render_review(feature: dict[str, Any], review: dict[str, Any], token_usage: dict[str, int]) -> str:
    """
    기능(feature) 정보, 회고 리뷰(review), 토큰 사용량(token_usage)을 Obsidian 마크다운 텍스트로 렌더링합니다.

    Args:
        feature: 기능 상세 데이터 딕셔너리
        review: 학습 리뷰 데이터 딕셔너리
        token_usage: 항목별 토큰 사용량 딕셔너리

    Returns:
        YAML Frontmatter 헤더와 마크다운 본문이 결합된 문자열
    """
    ownership = review["ownership"]
    lines = [
        "---",
        "type: feature-learning-review",
        f"project: {feature['project_slug']}",
        f"feature_id: {feature['id']}",
        f"status: {'verified' if review['verified'] else 'needs-confirmation'}",
        f"started: {feature['started_at']}",
        f"finished: {feature.get('finished_at') or ''}",
        f"weaknesses: {_yaml_list(review['weaknesses'])}",
        f"next_topics: {_yaml_list(review['next_topics'])}",
        "tokens:",
    ]
    for key, value in token_usage.items():
        lines.append(f"  {key}: {value}")
    lines.extend(["ownership:"])
    for key, value in ownership.items():
        lines.append(f"  {key}: {value}")
    lines.extend(
        [
            "---",
            "",
            f"# {feature['id']} — {feature['title']}",
            "",
            "## 요청한 기능",
            "",
            feature["goal"],
            "",
            "## 내가 맡기로 한 판단 범위",
            "",
            *[f"- {item}" for item in feature["user_owned_scope"]],
            "",
            "## 리뷰 요약",
            "",
            review["summary"],
            "",
            "## 코드 실행 흐름",
            "",
            review["code_flow"],
            "",
            "## 기여도 판정",
            "",
            "| 영역 | 판정 |",
            "|---|---|",
            *[f"| {key} | {value} |" for key, value in ownership.items()],
            "",
            "## 다른 기술과 대안",
            "",
            *[f"- {item}" for item in review["alternatives"]],
            "",
            "## 반복 약점",
            "",
            *[f"- {item}" for item in review["weaknesses"]],
            "",
            "## 다음 학습 주제",
            "",
            *[f"- {item}" for item in review["next_topics"]],
            "",
            "## 토큰 사용량",
            "",
            "| 항목 | 토큰 |",
            "|---|---:|",
            *[f"| {key} | {value:,} |" for key, value in token_usage.items()],
            "",
        ]
    )
    return "\n".join(lines)


def export_review(vault: Path, feature: dict[str, Any], content: str) -> tuple[str, str]:
    """
    렌더링된 마크다운 텍스트를 Obsidian Vault 내부 디렉토리에 파일로 저장합니다.

    경로 탈출(Directory Traversal)을 검증하여 Vault 바깥에 저장되지 않도록 안전하게 보호합니다.

    Args:
        vault: Obsidian Vault 루트 디렉토리 Path
        feature: 기능 데이터 딕셔너리
        content: 렌더링된 마크다운 문자열

    Returns:
        (Vault 기준 상대 경로, SHA256 해시값) 튜플

    Raises:
        ValueError: 대상 경로가 Vault 내부를 벗어나는 경우
    """
    filename = f"review-{_filename_slug(feature['title'])}.md"
    relative = Path("dev/wiki/projects") / feature["project_slug"] / "features" / feature["id"] / filename
    destination = (vault / relative).resolve()
    vault_resolved = vault.resolve()
    # 상위 경로에 Vault 루트가 포함되어 있는지 검증 (경로 탈출 방지)
    if vault_resolved not in destination.parents:
        raise ValueError("resolved Obsidian path escapes the configured vault")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(content, encoding="utf-8")
    # 내용 검증용 SHA256 다이제스트 계산
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return str(relative), digest

