"""
Model Context Protocol(MCP) 서버 진입점 및 툴(Tool)/리소스(Resource) 정의 모듈입니다.

FastMCP 또는 HighLevelMCPServer SDK를 활용하여 
AI 에이전트(Codex, Claude 등)가 호출할 수 있는 기능 관리, 의사결정 기록, 
디버깅 시도 기록, 토큰 동기화, 매니페스트 조회, 회고 내보내기 툴을 노출합니다.
"""

from __future__ import annotations

from typing import Literal

try:  # MCP Python SDK v2 버전 지원
    from mcp.server import MCPServer as HighLevelMCPServer
except ImportError:  # MCP Python SDK v1.27+ 호환용 FastMCP
    from mcp.server.fastmcp import FastMCP as HighLevelMCPServer

from .service import LearningService, Ownership

# MCP 서버 객체 생성 및 기본 안내(Instructions) 설정
mcp = HighLevelMCPServer(
    "Learning MCP",
    instructions=(
        "Track developer learning by feature. Fetch compact manifests first, then request only needed evidence refs. "
        "Do not equate token volume with learning ownership. For every project-scoped call, pass the current host "
        "workspace Git root explicitly; never reuse a configured default project."
    ),
    log_level="WARNING",
)

# 핵심 학습 서비스 인스턴스 초기화
service = LearningService()


@mcp.tool()
def start_feature(
    project_root: str,
    title: str,
    goal: str,
    success_conditions: list[str],
    user_owned_scope: list[str],
    ai_allowed_scope: list[str],
    project_name: str | None = None,
) -> dict:
    """
    [MCP Tool] 새로운 기능/태스크 학습 추적을 시작합니다.
    호출자의 현재 Git 루트 absolute 경로(project_root)를 명시적으로 전달해야 합니다.
    """
    return service.start_feature(
        title, goal, success_conditions, user_owned_scope, ai_allowed_scope,
        project_name=project_name, project_root=project_root,
    )


@mcp.tool()
def get_project_context(project_root: str) -> dict:
    """
    [MCP Tool] 지정된 project_root 경로의 Git 상태 및 현재 진행 중인 활성 기능(Active Feature)을 조회합니다.
    """
    return service.get_project_context(project_root)


@mcp.tool()
def record_decision(
    feature_id: str,
    question: str,
    chosen_option: str,
    reason: str,
    alternatives: list[str],
    decided_by: Literal["human", "shared", "ai"],
) -> dict:
    """
    [MCP Tool] 아키텍처 또는 구현 방식에 관한 중요한 의사결정 사항과 선택 대안, 결정 주체를 기록합니다.
    """
    return service.record_decision(feature_id, question, chosen_option, reason, alternatives, decided_by)


@mcp.tool()
def record_debug_attempt(
    feature_id: str,
    symptom: str,
    hypotheses: list[str],
    verification: str,
    outcome: str = "",
    status: Literal["open", "confirmed", "rejected", "resolved"] = "open",
) -> dict:
    """
    [MCP Tool] 버그 원인 파악 시 증상, 검증할 가설, 실험 결과 및 디버깅 상태를 기록합니다.
    """
    return service.record_debug_attempt(feature_id, symptom, hypotheses, verification, outcome, status)


@mcp.tool()
def sync_codex_session(
    feature_id: str,
    session_file: str,
    phase: Literal["start", "update", "finish"] = "update",
) -> dict:
    """
    [MCP Tool] Codex CLI 세션 로그(.jsonl)를 기능에 연동하고 소모된 토큰 사용량 차이(Delta)를 계산합니다.
    """
    return service.sync_codex_session(feature_id, session_file, phase)


@mcp.tool()
def get_feature_manifest(feature_id: str, detail: Literal["quick", "standard"] = "quick") -> dict:
    """
    [MCP Tool] 전체 트랜스크립트 대신 토큰 효율적인 압축 매니페스트 및 근거 참짓(Ref) 목록을 조회합니다.
    """
    return service.get_feature_manifest(feature_id, detail)


@mcp.tool()
def get_evidence(feature_id: str, refs: list[str], max_chars: int = 12_000) -> dict:
    """
    [MCP Tool] 매니페스트에서 얻은 특정 근거 참짓(decision, debug, diff, commit 등)의 상세 내역을 선택적으로 가져옵니다.
    """
    return service.get_evidence(feature_id, refs, max_chars)


@mcp.tool()
def save_feature_review(
    feature_id: str,
    summary: str,
    code_flow: str,
    ownership: dict[str, Ownership],
    alternatives: list[str],
    weaknesses: list[str],
    next_topics: list[str],
    verified: bool = False,
    export_to_obsidian: bool = True,
) -> dict:
    """
    [MCP Tool] 기능 구현 완료 후 학습 회고/리뷰 데이터를 저장하고 선택적으로 Obsidian Vault로 내보냅니다.
    """
    return service.save_feature_review(feature_id, summary, code_flow, ownership, alternatives, weaknesses, next_topics, verified, export_to_obsidian)


@mcp.tool()
def finish_feature(feature_id: str) -> dict:
    """
    [MCP Tool] 진행 중인 기능을 완료(completed) 처리하고 연동된 Codex 세션 토큰 사용량을 최종 갱신합니다.
    """
    return service.finish_feature(feature_id)


@mcp.tool()
def get_learning_history(project_slug: str, limit: int = 10) -> dict:
    """
    [MCP Tool] 프로젝트의 최근 학습 리뷰 기록 및 자주 반복되는 약점(Recurring Weaknesses) 상위 목록을 조회합니다.
    """
    return service.get_learning_history(project_slug, limit)


@mcp.resource("learning://feature/{feature_id}/manifest")
def feature_manifest(feature_id: str) -> dict:
    """
    [MCP Resource] URI 형태로 제공되는 기능의 요약 매니페스트 리소스입니다.
    """
    return service.get_feature_manifest(feature_id, "quick")


def main() -> None:
    """MCP 서버 실행 진입점 함수"""
    mcp.run()


if __name__ == "__main__":
    main()

