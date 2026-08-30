"""
Codex CLI 세션 로그(.jsonl) 해석 및 토큰 사용량 계산 모듈입니다.

Codex 대화 기록 이벤트(JSONL 파일)에서 사용된 토큰 수(입력, 출력, 추론 등)를 파싱하고,
세션 간 토큰 차이(Delta)를 구하거나 대화 이벤트(사용자/AI 메시지)를 추출하는 기능을 제공합니다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# 집계 대상 토큰 키 이름 튜플
TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def empty_usage() -> dict[str, int]:
    """모든 토큰 항목이 0으로 초기화된 딕셔너리를 반환합니다."""
    return {key: 0 for key in TOKEN_KEYS}


def latest_usage(path: Path) -> dict[str, int]:
    """
    Codex rollout JSONL 세션 로그 파일에서 가장 최근(최종) 누적 토큰 사용량 스냅샷을 추출합니다.

    Args:
        path: Codex 세션 JSONL 파일 경로

    Returns:
        토큰 종류별 누적 사용량 딕셔너리

    Raises:
        ValueError: 토큰 사용량 이벤트(token_count)를 찾지 못한 경우
    """
    latest: dict[str, int] | None = None
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item: dict[str, Any] = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            payload = item.get("payload", {})
            # token_count 이벤트 메시지만 필터링
            if item.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            usage = payload.get("info", {}).get("total_token_usage", {})
            latest = {key: int(usage.get(key, 0) or 0) for key in TOKEN_KEYS}
    if latest is None:
        raise ValueError(f"no Codex token_count event found in {path}")
    return latest


def usage_delta(baseline: dict[str, int], latest: dict[str, int]) -> dict[str, int]:
    """
    기준 시점(baseline)과 최근 시점(latest) 사이의 토큰 사용량 차이(Delta)를 계산합니다.
    음수가 나오지 않도록 max(0, diff)를 적용합니다.
    """
    return {key: max(0, int(latest.get(key, 0)) - int(baseline.get(key, 0))) for key in TOKEN_KEYS}


def line_count(path: Path) -> int:
    """파일의 전체 줄(Line) 수를 반환합니다."""
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def conversation_events(path: Path, after_line: int = 0) -> list[dict[str, Any]]:
    """
    Codex 세션 JSONL 파일에서 지정한 줄 번호(after_line) 이후의 사용자 및 보조자(AI) 대화 이벤트를 추출합니다.

    Args:
        path: Codex 세션 JSONL 파일 경로
        after_line: 이 줄 번호(1-based) 이후의 대화만 읽습니다 (기본값: 0)

    Returns:
        대화 이벤트 딕셔너리 리스트 (줄번호, 역할, 요약, 상세내용, 타임스탬프)
    """
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line_number <= after_line:
                continue
            try:
                item: dict[str, Any] = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            payload = item.get("payload", {})
            role = ""
            text = ""
            # 형식 1: event_msg 형태의 user_message / agent_message
            if item.get("type") == "event_msg" and payload.get("type") in {"user_message", "agent_message"}:
                role = "user" if payload.get("type") == "user_message" else "assistant"
                text = str(payload.get("message", ""))
            # 형식 2: response_item 형태의 message
            elif item.get("type") == "response_item" and payload.get("type") == "message":
                role = str(payload.get("role", ""))
                parts = payload.get("content", [])
                if isinstance(parts, list):
                    text = "\n".join(
                        str(part.get("text", ""))
                        for part in parts
                        if isinstance(part, dict) and part.get("type") in {"input_text", "output_text", "text"}
                    )
            # 유효한 역할이나 메시지 내용이 없는 경우 스킵
            if role not in {"user", "assistant"} or not text.strip():
                continue
            clean = text.strip()
            events.append(
                {
                    "line": line_number,
                    "role": role,
                    "summary": clean.replace("\n", " ")[:240], # 검색/목록용 240자 요약
                    "content": clean[:4_000],                 # 상세 내용 (최대 4,000자)
                    "timestamp": item.get("timestamp"),
                }
            )
    return events

