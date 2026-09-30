"""
Learning MCP 커맨드라인 인터페이스(CLI) 도구 모듈입니다.

터미널에서 직접 DB 초기화(init), 현재 활성 기능 조회(current), 
기능 매니페스트 출력(manifest), Codex 세션 동기화(sync-codex) 등의 유틸리티 명령어를 실행할 수 있습니다.
"""

from __future__ import annotations

import argparse
import json

from .service import LearningService


def _print(value: object) -> None:
    """객체/딕셔너리 데이터를 예쁘게 포맷팅된 JSON 형태로 표준 출력(stdout)합니다."""
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main() -> None:
    """CLI 인자를 파싱하고 요청된 명령어(subcommand)에 따라 LearningService 메소드를 호출합니다."""
    parser = argparse.ArgumentParser(description="Learning MCP local utility")
    sub = parser.add_subparsers(dest="command", required=True)

    # 1. DB 초기화 명령어 (init)
    sub.add_parser("init", help="Initialize the SQLite database")

    # 2. 현재 프로젝트의 활성 기능 조회 명령어 (current)
    current = sub.add_parser("current", help="Show the active feature")
    current.add_argument("--project-root", help="프로젝트 Git 루트 경로")

    # 3. 기능 매니페스트 조회 명령어 (manifest)
    manifest = sub.add_parser("manifest", help="Print a compact feature manifest")
    manifest.add_argument("feature_id", help="조회할 기능 ID (예: F-20260825-001)")
    manifest.add_argument("--detail", choices=("quick", "standard"), default="quick", help="상세 수준 선택")

    # 4. Codex 세션 연동 및 동기화 명령어 (sync-codex)
    sync = sub.add_parser("sync-codex", help="Attach or refresh a Codex token session")
    sync.add_argument("feature_id", help="연동할 기능 ID")
    sync.add_argument("--session-file", default="latest", help="Codex 세션 파일 경로 (기본: 'latest')")
    sync.add_argument("--phase", choices=("start", "update", "finish"), default="update", help="동기화 단계")

    status = sub.add_parser("status", help="Show worker, queue, and active feature health")
    status.add_argument("--project-root", help="프로젝트 Git 루트 경로")

    install_worker = sub.add_parser("install-worker-autostart", help="Install and load the macOS worker LaunchAgent")
    install_worker.add_argument("--no-load", action="store_true", help="plist만 설치하고 즉시 시작하지 않음")

    args = parser.parse_args()
    service = LearningService()
    
    if args.command == "init":
        # DB 인스턴스 생성 및 스키마 초기화 결과 출력
        _print({"initialized": True, "db": str(service.settings.db_path)})
    elif args.command == "current":
        # 현재 활성 기능 정보 출력
        project_root = args.project_root or str(service.settings.project_root)
        _print(service.current_feature(project_root) or {"active": False})
    elif args.command == "manifest":
        # 기능 매니페스트 요약 출력
        _print(service.get_feature_manifest(args.feature_id, args.detail))
    elif args.command == "sync-codex":
        # Codex 세션 동기화 결과 출력
        _print(service.sync_codex_session(args.feature_id, args.session_file, args.phase))
    elif args.command == "status":
        _print(service.get_system_status(args.project_root))
    elif args.command == "install-worker-autostart":
        from .autostart import install_worker_launch_agent
        _print(install_worker_launch_agent(service.settings, load=not args.no_load))


if __name__ == "__main__":
    main()
