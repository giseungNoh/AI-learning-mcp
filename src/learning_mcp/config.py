"""
애플리케이션 환경설정 관리 모듈입니다.

환경 변수(Environment Variables)에서 설정값을 읽어와 
SQLite DB 경로, 프로젝트 루트, Obsidian 보관소 경로, Codex 세션 위치, 
그리고 응답 글자 수 제한 등의 설정을 데이터 클래스(Settings)로 관리합니다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 현재 파일 위치 기준으로 최상위 패키지 루트 디렉토리 계산 (learning-mcp 루트)
PACKAGE_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    """
    Learning MCP 서비스 전체에서 사용되는 불변(Immutable) 설정 데이터 클래스.

    Attributes:
        home: 애플리케이션 기본 홈 디렉토리
        db_path: SQLite 데이터베이스 파일 (.db) 경로
        project_root: 대상 프로젝트의 작업 루트 디렉토리
        obsidian_vault: 학습 리뷰를 내보낼 Obsidian Vault(보관소) 경로 (선택)
        obsidian_base_dir: Vault 안에서 Learning MCP 생성물을 저장할 상대 경로
        codex_session_root: Codex CLI 세션 로그(.jsonl)가 저장되는 루트 디렉토리
        max_manifest_chars: 기능 매니페스트 생성 시 최대 응답 문자 수 (기본: 8,000자)
        max_evidence_chars: 근거(Evidence) 데이터 조회 시 최대 응답 문자 수 (기본: 12,000자)
    """
    home: Path
    db_path: Path
    project_root: Path
    obsidian_vault: Path | None
    codex_session_root: Path | None = None
    max_manifest_chars: int = 8_000
    max_evidence_chars: int = 12_000
    obsidian_base_dir: Path = Path("dev/wiki")

    @classmethod
    def from_env(cls) -> "Settings":
        """
        환경 변수에서 설정을 읽어와 Settings 객체를 생성합니다.
        지정되지 않은 경우 기본값을 자동으로 적용합니다.
        """
        # 홈 디렉토리: LEARNING_MCP_HOME 미지정 시 PACKAGE_ROOT 사용
        home = Path(os.getenv("LEARNING_MCP_HOME", PACKAGE_ROOT)).expanduser().resolve()
        
        # 데이터베이스 파일 경로: 기본값은 home/data/learning.db
        db_path = Path(
            os.getenv("LEARNING_MCP_DB", str(home / "data" / "learning.db"))
        ).expanduser().resolve()
        
        # 현재 작업 대상 프로젝트 루트: 기본값은 현재 작업 디렉토리(os.getcwd())
        project_root = Path(
            os.getenv("LEARNING_MCP_PROJECT_ROOT", os.getcwd())
        ).expanduser().resolve()
        
        # Obsidian Vault 경로 (비어있으면 None 처리)
        raw_vault = os.getenv("LEARNING_MCP_OBSIDIAN_VAULT", "").strip()
        obsidian_vault = Path(raw_vault).expanduser().resolve() if raw_vault else None

        raw_base_dir = os.getenv("LEARNING_MCP_OBSIDIAN_BASE_DIR", "dev/wiki").strip() or "."
        obsidian_base_dir = Path(raw_base_dir)
        if obsidian_base_dir.is_absolute() or ".." in obsidian_base_dir.parts:
            raise ValueError("LEARNING_MCP_OBSIDIAN_BASE_DIR must stay inside the Obsidian Vault")
        
        # Codex 세션 파일 경로: 기본값은 ~/.codex/sessions
        codex_session_root = Path(
            os.getenv("LEARNING_MCP_CODEX_SESSION_ROOT", str(Path.home() / ".codex" / "sessions"))
        ).expanduser().resolve()
        
        return cls(
            home=home,
            db_path=db_path,
            project_root=project_root,
            obsidian_vault=obsidian_vault,
            codex_session_root=codex_session_root,
            max_manifest_chars=int(os.getenv("LEARNING_MCP_MAX_MANIFEST_CHARS", "8000")),
            max_evidence_chars=int(os.getenv("LEARNING_MCP_MAX_EVIDENCE_CHARS", "12000")),
            obsidian_base_dir=obsidian_base_dir,
        )
