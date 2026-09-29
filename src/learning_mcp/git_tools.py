"""
Git 저장소 연동 및 명령어 실행 헬퍼 모듈입니다.

Git 루트 디렉토리 결정, 현재 커밋 SHA, 브랜치명, Git 상태(Status),
diff(수정 내역) 통계 및 상세 내역, 커밋 조회 기능 등을 안전하게 수행합니다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def resolve_root(path: str | Path) -> Path:
    """
    Git 작업 영역(Worktree) 내 임의의 경로를 전달받아 최상위 Git 루트 디렉토리의 절대 경로를 구합니다.

    Args:
        path: 검사할 디렉토리 또는 파일 경로

    Returns:
        최상위 Git 루트 디렉토리 Path 객체

    Raises:
        ValueError: 경로나 디렉토리가 존재하지 않거나 Git 저장소 내부가 아닌 경우
    """
    candidate = Path(path).expanduser().resolve()
    if not candidate.is_dir():
        raise ValueError(f"project_root must be an existing directory: {candidate}")
    result = subprocess.run(
        ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError(f"project_root must be inside a Git worktree: {candidate}")
    return Path(result.stdout.strip()).expanduser().resolve()


def _git(root: Path, *args: str, limit: int = 80_000) -> str:
    """
    내부 헬퍼: 지정한 Git 루트에서 외부 git 명령어를 안전하게 실행합니다.

    Args:
        root: Git 프로젝트 루트 경로
        *args: git 하위 명령어 및 인자들
        limit: 응답 문자열의 최대 길이 제한 (기본: 80,000자)

    Returns:
        명령어 실행 결과 표준 출력(stdout) 문자열 (실패 시 빈 문자열)
    """
    if not (root / ".git").exists():
        return ""
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout[:limit]


def head(root: Path) -> str | None:
    """현재 HEAD 커밋의 SHA 해시값을 반환합니다. (없을 경우 None)"""
    return _git(root, "rev-parse", "HEAD").strip() or None


def branch(root: Path) -> str | None:
    """현재 작업 중인 Git 브랜치 이름을 반환합니다. (없을 경우 None)"""
    return _git(root, "branch", "--show-current").strip() or None


def status(root: Path) -> str:
    """git status --short 결과를 반환합니다."""
    return _git(root, "status", "--short")


def diff_stat(root: Path, staged: bool = False) -> str:
    """
    변경 사항 파일 통계(git diff --stat)를 반환합니다.
    staged=True일 경우 스테이징된 변경 사항(--cached)을 조회합니다.
    """
    args = ("diff", "--cached", "--stat") if staged else ("diff", "--stat")
    return _git(root, *args)


def diff(root: Path, staged: bool = False, max_chars: int = 12_000) -> str:
    """
    Git diff 패치 상세 내용을 반환합니다. max_chars 초과 시 잘라냅니다(truncated).
    staged=True일 경우 스테이징 영역(--cached)의 diff를 조회합니다.
    """
    args = ("diff", "--cached", "--unified=2") if staged else ("diff", "--unified=2")
    value = _git(root, *args, limit=max_chars + 1)
    if len(value) > max_chars:
        return value[:max_chars] + "\n…[truncated]"
    return value


def commit_show(root: Path, sha: str, max_chars: int = 12_000) -> str:
    """
    특정 커밋 SHA의 상세 정보(git show)를 반환합니다.
    16진수 SHA 검증을 거치며, max_chars 초과 시 잘라냅니다.
    """
    if not sha or any(ch not in "0123456789abcdefABCDEF" for ch in sha):
        raise ValueError("commit ref must be a hexadecimal SHA")
    value = _git(root, "show", "--stat", "--format=fuller", "--no-ext-diff", sha, limit=max_chars + 1)
    if len(value) > max_chars:
        return value[:max_chars] + "\n…[truncated]"
    return value

