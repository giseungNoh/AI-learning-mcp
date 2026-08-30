"""
Learning MCP 핵심 비즈니스 로직 및 서비스 구현 모듈입니다.

기능(Feature) 생성 및 상태 관리, 아키텍처 판단 기록(Decision),
버그 디버깅 기록(Debug Attempt), Codex 토큰/대화 동기화(Codex Sync),
압축 매니페스트 및 근거(Evidence) 데이터 제공, 회고 리뷰 저장 및 Obsidian 내보내기 
기능을 총괄 수행합니다.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from . import git_tools
from .codex_usage import TOKEN_KEYS, conversation_events, empty_usage, latest_usage, line_count, usage_delta
from .config import Settings
from .db import Database
from .obsidian import export_review, render_review

# 개발 주도권/기여도 분류 타입 (사용자 주도, 공동 주도, AI 주도-검증됨, AI 주도-검증안됨)
Ownership = Literal["human-led", "shared", "ai-led-verified", "ai-led-unverified"]


def now_iso() -> str:
    """현재 로컬 타임스탬프를 ISO 8601 문자열 형식(초 단위)으로 반환합니다."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def dumps(value: Any) -> str:
    """JSON 직렬화 헬퍼 (한글 등 유니코드 문자를 탈출하지 않고 그대로 유지)."""
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default: Any) -> Any:
    """JSON 역직렬화 헬퍼 (값이 없거나 빈 문자열이면 default 반환)."""
    if not value:
        return default
    return json.loads(value)


def slugify(value: str) -> str:
    """문자열을 알파벳 소문자와 숫자, 하이픈(-) 조합의 슬러그 형태로 변환합니다."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def _row_dict(row: Any) -> dict[str, Any]:
    """SQLite Row 객체를 딕셔너리로 변환합니다."""
    return dict(row) if row is not None else {}


class LearningService:
    """
    기능 개발 기반 개발자 학습 추적 및 관리를 위한 핵심 서비스 클래스입니다.
    """
    def __init__(self, settings: Settings | None = None):
        """환경설정(Settings) 및 데이터베이스(Database) 인스턴스를 초기화합니다."""
        self.settings = settings or Settings.from_env()
        self.db = Database(self.settings.db_path)

    def _feature(self, feature_id: str) -> dict[str, Any]:
        """
        데이터베이스에서 기능 ID에 해당하는 레코드를 조회하고, 
        JSON 문자열 필드들을 Python 리스트로 변환하여 반환합니다.
        """
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM features WHERE id = ?", (feature_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown feature: {feature_id}")
        feature = _row_dict(row)
        # JSON 문자열 저장 필드를 딕셔너리 리스트로 변환
        for key in ("success_conditions", "user_owned_scope", "ai_allowed_scope"):
            feature[key] = loads(feature.pop(f"{key}_json"), [])
        return feature

    def current_feature(self, project_root: str) -> dict[str, Any] | None:
        """
        해당 Git 프로젝트 루트에서 현재 진행 중인(status='active') 가장 최근 기능 정보를 반환합니다.
        """
        root = str(git_tools.resolve_root(project_root))
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT id FROM features WHERE project_root = ? AND status = 'active' ORDER BY started_at DESC LIMIT 1",
                (root,),
            ).fetchone()
        return self._feature(row["id"]) if row else None

    def get_project_context(self, project_root: str) -> dict[str, Any]:
        """
        프로젝트 루트 경로를 해석하여 Git 브랜치, 커밋 HEAD, 현재 활성 기능을 묶어 반환합니다.
        """
        root = git_tools.resolve_root(project_root)
        active = self.current_feature(str(root))
        return {
            "project_root": str(root),
            "project_name": root.name,
            "branch": git_tools.branch(root),
            "head": git_tools.head(root),
            "active_feature": active,
        }

    def start_feature(
        self,
        title: str,
        goal: str,
        success_conditions: list[str],
        user_owned_scope: list[str],
        ai_allowed_scope: list[str],
        project_name: str | None = None,
        project_root: str | None = None,
    ) -> dict[str, Any]:
        """
        새로운 기능(Feature) 추적을 시작합니다.

        1. project_root 필수 전달 검증 및 Git 루트 계산
        2. 이미 활성화된 기능이 있는지 확인 (중복 시작 방지)
        3. F-YYYYMMDD-001 형태의 고유 기능 ID 생성
        4. features 및 initial evidence 레코드 저장
        """
        if not project_root:
            raise ValueError(
                "project_root is required; pass the current workspace Git root "
                "(for example: git rev-parse --show-toplevel)"
            )
        root = git_tools.resolve_root(project_root)
        active = self.current_feature(str(root))
        if active:
            raise ValueError(f"feature {active['id']} is already active for {root}")
        date = datetime.now().astimezone().strftime("%Y%m%d")
        with self.db.connect() as connection:
            # 오늘 생성된 기능 개수를 기반으로 세 자리 시퀀스 생성
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM features WHERE id LIKE ?", (f"F-{date}-%",)
            ).fetchone()["count"]
            feature_id = f"F-{date}-{count + 1:03d}"
            name = project_name or root.name
            timestamp = now_iso()
            connection.execute(
                """
                INSERT INTO features (
                    id, project_name, project_slug, project_root, title, goal,
                    success_conditions_json, user_owned_scope_json, ai_allowed_scope_json,
                    baseline_commit, branch, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feature_id,
                    name,
                    slugify(name),
                    str(root),
                    title,
                    goal,
                    dumps(success_conditions),
                    dumps(user_owned_scope),
                    dumps(ai_allowed_scope),
                    git_tools.head(root),
                    git_tools.branch(root),
                    timestamp,
                ),
            )
            # 최초 범위 선언 근거(Evidence) 등록
            connection.execute(
                "INSERT INTO evidence(feature_id, kind, summary, content, source_ref, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (feature_id, "scope", "Feature scope declared", goal, f"feature:{feature_id}", timestamp),
            )
        return self._feature(feature_id)

    def record_decision(
        self,
        feature_id: str,
        question: str,
        chosen_option: str,
        reason: str,
        alternatives: list[str],
        decided_by: Literal["human", "shared", "ai"],
    ) -> dict[str, Any]:
        """
        기능 구현 중 내려진 주요 의사결정을 기록하고 근거(evidence) 인덱스에 추가합니다.
        """
        self._feature(feature_id)
        timestamp = now_iso()
        with self.db.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO decisions
                (feature_id, question, chosen_option, reason, alternatives_json, decided_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (feature_id, question, chosen_option, reason, dumps(alternatives), decided_by, timestamp),
            )
            decision_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO evidence(feature_id, kind, summary, content, source_ref, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    feature_id,
                    "decision",
                    f"{question} → {chosen_option}",
                    reason,
                    f"decision:{decision_id}",
                    timestamp,
                ),
            )
        return {"id": decision_id, "ref": f"decision:{decision_id}", "saved": True}

    def record_debug_attempt(
        self,
        feature_id: str,
        symptom: str,
        hypotheses: list[str],
        verification: str,
        outcome: str = "",
        status: Literal["open", "confirmed", "rejected", "resolved"] = "open",
    ) -> dict[str, Any]:
        """
        버그 해결 시도(증상, 가설, 검증 시도, 결과 및 상태)를 기록합니다.
        """
        self._feature(feature_id)
        timestamp = now_iso()
        with self.db.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO debug_attempts
                (feature_id, symptom, hypotheses_json, verification, outcome, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (feature_id, symptom, dumps(hypotheses), verification, outcome, status, timestamp),
            )
            attempt_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO evidence(feature_id, kind, summary, content, source_ref, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    feature_id,
                    "debug",
                    symptom,
                    f"Verification: {verification}\nOutcome: {outcome}",
                    f"debug:{attempt_id}",
                    timestamp,
                ),
            )
        return {"id": attempt_id, "ref": f"debug:{attempt_id}", "saved": True}

    def sync_codex_session(
        self,
        feature_id: str,
        session_file: str,
        phase: Literal["start", "update", "finish"] = "update",
    ) -> dict[str, Any]:
        """
        Codex 세션 로그 파일(.jsonl)을 파싱하여 기능에 연동하고, 토큰 사용량 및 대화 이벤트를 가져옵니다.

        Args:
            feature_id: 대상 기능 ID
            session_file: 연동할 JSONL 파일 경로 또는 'latest'
            phase: 동기화 시점 ('start': 시작 기준점 설정, 'update': 중간 갱신, 'finish': 최종 갱신)
        """
        self._feature(feature_id)
        # 'latest' 전달 시 가장 최근에 수정된 세션 파일 탐색
        if session_file == "latest":
            session_root = self.settings.codex_session_root or (Path.home() / ".codex" / "sessions")
            candidates = list(session_root.glob("**/*.jsonl"))
            if not candidates:
                raise ValueError("no Codex rollout JSONL found")
            path = max(candidates, key=lambda candidate: candidate.stat().st_mtime).resolve()
        else:
            path = Path(session_file).expanduser().resolve()
        
        # 파일 존재 및 세션 루트 디렉토리 내부 경로인지 안전성 검증
        if path.suffix != ".jsonl" or not path.is_file():
            raise ValueError("session_file must be a readable Codex .jsonl file")
        session_root = (self.settings.codex_session_root or (Path.home() / ".codex" / "sessions")).resolve()
        if path != session_root and session_root not in path.parents:
            raise ValueError(f"session_file must be under {session_root}")

        current = latest_usage(path)
        current_line = line_count(path)
        external_id = path.stem
        timestamp = now_iso()

        with self.db.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM sessions WHERE feature_id = ? AND provider = 'codex' AND external_id = ?",
                (feature_id, external_id),
            ).fetchone()
            if existing is None:
                # 최초 세션 연동인 경우
                baseline = current if phase == "start" else empty_usage()
                baseline_line = current_line if phase == "start" else 0
                measurement = "exact-feature-delta" if phase == "start" else "whole-session"
                connection.execute(
                    """INSERT INTO sessions
                    (feature_id, provider, external_id, source_path, baseline_usage_json,
                     latest_usage_json, baseline_line, latest_line, measurement, attached_at, updated_at)
                    VALUES (?, 'codex', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        feature_id,
                        external_id,
                        str(path),
                        dumps(baseline),
                        dumps(current),
                        baseline_line,
                        current_line,
                        measurement,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                # 기존 세션 정보 업데이트
                baseline = loads(existing["baseline_usage_json"], empty_usage())
                baseline_line = existing["baseline_line"]
                measurement = existing["measurement"]
                connection.execute(
                    "UPDATE sessions SET latest_usage_json = ?, latest_line = ?, source_path = ?, updated_at = ? WHERE id = ?",
                    (dumps(current), current_line, str(path), timestamp, existing["id"]),
                )
            
            # 대화 이벤트 가져와서 근거(evidence) 데이터로 등록
            imported = 0
            if phase != "start":
                for event in conversation_events(path, after_line=baseline_line):
                    cursor = connection.execute(
                        """INSERT OR IGNORE INTO evidence
                        (feature_id, kind, summary, content, source_ref, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            feature_id,
                            f"conversation-{event['role']}",
                            event["summary"],
                            event["content"],
                            f"codex:{external_id}:line:{event['line']}",
                            event["timestamp"] or timestamp,
                        ),
                    )
                    imported += max(0, cursor.rowcount)

        delta = usage_delta(baseline, current)
        return {
            "feature_id": feature_id,
            "session_id": external_id,
            "phase": phase,
            "measurement": measurement,
            "source_path": str(path),
            "conversation_events_imported": imported,
            "usage": delta,
        }

    def _token_totals(self, feature_id: str) -> tuple[dict[str, int], list[dict[str, Any]]]:
        """기능에 연동된 모든 세션의 토큰 사용량 차이(Delta) 합계를 계산합니다."""
        totals = empty_usage()
        sessions: list[dict[str, Any]] = []
        with self.db.connect() as connection:
            rows = connection.execute("SELECT * FROM sessions WHERE feature_id = ?", (feature_id,)).fetchall()
        for row in rows:
            baseline = loads(row["baseline_usage_json"], empty_usage())
            latest = loads(row["latest_usage_json"], empty_usage())
            delta = usage_delta(baseline, latest)
            for key in TOKEN_KEYS:
                totals[key] += delta[key]
            sessions.append(
                {
                    "provider": row["provider"],
                    "session_id": row["external_id"],
                    "measurement": row["measurement"],
                    "usage": delta,
                }
            )
        return totals, sessions

    def get_feature_manifest(self, feature_id: str, detail: Literal["quick", "standard"] = "quick") -> dict[str, Any]:
        """
        AI 모델이 효율적으로 컨텍스트를 파악할 수 있도록 
        전체 트랜스크립트 대신 요약된 기능 매니페스트 및 근거 참짓(Ref) 인덱스를 반환합니다.
        문자 수 제한(max_manifest_chars)을 조절하여 예산 초과 시 자동 조절(Truncate)합니다.
        """
        feature = self._feature(feature_id)
        root = Path(feature["project_root"])
        token_totals, sessions = self._token_totals(feature_id)
        with self.db.connect() as connection:
            decisions = connection.execute(
                "SELECT id, question, chosen_option, decided_by FROM decisions WHERE feature_id = ? ORDER BY id",
                (feature_id,),
            ).fetchall()
            debug = connection.execute(
                "SELECT id, symptom, status FROM debug_attempts WHERE feature_id = ? ORDER BY id",
                (feature_id,),
            ).fetchall()
            evidence = connection.execute(
                "SELECT id, kind, summary, source_ref FROM evidence WHERE feature_id = ? ORDER BY id DESC LIMIT 20",
                (feature_id,),
            ).fetchall()
        manifest: dict[str, Any] = {
            "feature": {
                "id": feature["id"],
                "title": feature["title"],
                "goal": feature["goal"][:1_000],
                "status": feature["status"],
                "success_conditions": [item[:300] for item in feature["success_conditions"][:12]],
                "user_owned_scope": [item[:300] for item in feature["user_owned_scope"][:12]],
                "ai_allowed_scope": [item[:300] for item in feature["ai_allowed_scope"][:12]],
            },
            "git": {
                "branch": feature["branch"],
                "baseline_commit": feature["baseline_commit"],
                "status": git_tools.status(root)[:2_000],
                "working_stat": git_tools.diff_stat(root)[:2_000],
                "staged_stat": git_tools.diff_stat(root, staged=True)[:2_000],
                "evidence_refs": ["diff:working", "diff:staged"],
            },
            "token_usage": token_totals,
            "sessions": sessions,
            "decisions": [dict(row) | {"ref": f"decision:{row['id']}"} for row in decisions],
            "debug_attempts": [dict(row) | {"ref": f"debug:{row['id']}"} for row in debug],
            "evidence_index": [dict(row) | {"ref": f"evidence:{row['id']}"} for row in evidence],
        }
        if detail == "standard":
            manifest["recent_learning"] = self.get_learning_history(feature["project_slug"], limit=5)
        
        # 글자 수 예산 제한에 맞춰 오래된 참짓 목록부터 순차적으로 Truncate 처리
        encoded = dumps(manifest)
        for key in ("evidence_index", "debug_attempts", "decisions"):
            while len(encoded) > self.settings.max_manifest_chars and manifest.get(key):
                manifest[key].pop()
                encoded = dumps(manifest)
        if len(encoded) > self.settings.max_manifest_chars and "recent_learning" in manifest:
            manifest.pop("recent_learning")
            encoded = dumps(manifest)
        manifest["truncated"] = len(encoded) > self.settings.max_manifest_chars
        manifest["response_budget"] = {
            "characters": len(encoded),
            "estimated_tokens": max(1, len(encoded) // 4),
            "note": "Estimate only; fetch evidence refs selectively.",
        }
        return manifest

    def get_evidence(self, feature_id: str, refs: list[str], max_chars: int | None = None) -> dict[str, Any]:
        """
        매니페스트에서 제공된 참짓(ref) 목록을 기반으로 실제 상세 근거 내역(Git Diff, 커밋 내용, 결정사항 등)을 가져옵니다.

        Args:
            feature_id: 기능 ID
            refs: 조회할 근거 참조 리스트 (최대 10개)
            max_chars: 응답 글자 수 제한
        """
        feature = self._feature(feature_id)
        root = Path(feature["project_root"])
        budget = max(500, min(max_chars or self.settings.max_evidence_chars, self.settings.max_evidence_chars))
        if len(refs) > 10:
            raise ValueError("request at most 10 evidence refs")
        items: list[dict[str, str]] = []
        remaining = budget
        with self.db.connect() as connection:
            for ref in refs:
                if remaining <= 0:
                    break
                content = ""
                if ref == "diff:working":
                    content = git_tools.diff(root, max_chars=remaining)
                elif ref == "diff:staged":
                    content = git_tools.diff(root, staged=True, max_chars=remaining)
                elif ref.startswith("commit:"):
                    content = git_tools.commit_show(root, ref.split(":", 1)[1], max_chars=remaining)
                elif ref.startswith("decision:"):
                    row = connection.execute(
                        "SELECT * FROM decisions WHERE id = ? AND feature_id = ?",
                        (int(ref.split(":", 1)[1]), feature_id),
                    ).fetchone()
                    if row:
                        content = dumps(dict(row))
                elif ref.startswith("debug:"):
                    row = connection.execute(
                        "SELECT * FROM debug_attempts WHERE id = ? AND feature_id = ?",
                        (int(ref.split(":", 1)[1]), feature_id),
                    ).fetchone()
                    if row:
                        content = dumps(dict(row))
                elif ref.startswith("evidence:"):
                    row = connection.execute(
                        "SELECT * FROM evidence WHERE id = ? AND feature_id = ?",
                        (int(ref.split(":", 1)[1]), feature_id),
                    ).fetchone()
                    if row:
                        content = dumps(dict(row))
                else:
                    raise ValueError(f"unsupported evidence ref: {ref}")
                if not content:
                    content = "[no content]"
                content = content[:remaining]
                items.append({"ref": ref, "content": content})
                remaining -= len(content)
        return {
            "feature_id": feature_id,
            "items": items,
            "characters": budget - remaining,
            "truncated": remaining <= 0,
        }

    def save_feature_review(
        self,
        feature_id: str,
        summary: str,
        code_flow: str,
        ownership: dict[str, Ownership],
        alternatives: list[str],
        weaknesses: list[str],
        next_topics: list[str],
        verified: bool = False,
        export_to_obsidian: bool = True,
    ) -> dict[str, Any]:
        """
        기능 개발 완료 후 종합 회고 리뷰를 DB에 저장하고, Obsidian Vault가 설정된 경우 마크다운 파일로 내보냅니다.
        """
        feature = self._feature(feature_id)
        # 허용된 기여도 영역 검증
        valid_areas = {"requirements", "architecture", "implementation", "debugging", "testing"}
        invalid = set(ownership) - valid_areas
        if invalid:
            raise ValueError(f"unsupported ownership areas: {sorted(invalid)}")
        review = {
            "summary": summary,
            "code_flow": code_flow,
            "ownership": ownership,
            "alternatives": alternatives,
            "weaknesses": weaknesses,
            "next_topics": next_topics[:3],
            "verified": verified,
        }
        token_totals, _ = self._token_totals(feature_id)
        obsidian_path: str | None = None
        digest: str | None = None
        # Obsidian 내보내기 처리
        if export_to_obsidian and self.settings.obsidian_vault:
            content = render_review(feature, review, token_totals)
            obsidian_path, digest = export_review(self.settings.obsidian_vault, feature, content)
        timestamp = now_iso()
        with self.db.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO reviews
                (feature_id, summary, code_flow, ownership_json, alternatives_json,
                 weaknesses_json, next_topics_json, verified, obsidian_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    feature_id,
                    summary,
                    code_flow,
                    dumps(ownership),
                    dumps(alternatives),
                    dumps(weaknesses),
                    dumps(next_topics[:3]),
                    int(verified),
                    obsidian_path,
                    timestamp,
                ),
            )
            review_id = cursor.lastrowid
        return {
            "saved": True,
            "review_id": review_id,
            "verified": verified,
            "obsidian_path": obsidian_path,
            "content_hash": digest,
        }

    def finish_feature(self, feature_id: str) -> dict[str, Any]:
        """
        기능 개발을 완료(completed) 상태로 변경하고, 연동된 Codex 세션의 토큰 사용량을 최종 갱신합니다.
        """
        feature = self._feature(feature_id)
        with self.db.connect() as connection:
            session_rows = connection.execute(
                "SELECT source_path FROM sessions WHERE feature_id = ? AND provider = 'codex'",
                (feature_id,),
            ).fetchall()
        synced = []
        for row in session_rows:
            path = Path(row["source_path"])
            if path.is_file():
                synced.append(self.sync_codex_session(feature_id, str(path), phase="finish"))
        timestamp = now_iso()
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE features SET status = 'completed', finished_at = ? WHERE id = ?",
                (timestamp, feature_id),
            )
        tokens, _ = self._token_totals(feature_id)
        return {"feature_id": feature_id, "status": "completed", "finished_at": timestamp, "token_usage": tokens, "sessions_synced": len(synced)}

    def get_learning_history(self, project_slug: str, limit: int = 10) -> dict[str, Any]:
        """
        해당 프로젝트의 최근 회고 리뷰 기록을 가져오고, 자주 발생하는 약점 패턴 상위 5개를 집계합니다.
        """
        limit = max(1, min(limit, 30))
        with self.db.connect() as connection:
            rows = connection.execute(
                """SELECT r.*, f.title, f.id AS feature_id FROM reviews r
                JOIN features f ON f.id = r.feature_id
                WHERE f.project_slug = ? ORDER BY r.created_at DESC LIMIT ?""",
                (project_slug, limit),
            ).fetchall()
        weakness_counts: Counter[str] = Counter()
        reviews = []
        for row in rows:
            weaknesses = loads(row["weaknesses_json"], [])
            weakness_counts.update(weaknesses)
            reviews.append(
                {
                    "feature_id": row["feature_id"],
                    "title": row["title"],
                    "summary": row["summary"][:500],
                    "weaknesses": weaknesses,
                    "next_topics": loads(row["next_topics_json"], []),
                    "verified": bool(row["verified"]),
                    "created_at": row["created_at"],
                }
            )
        return {"project": project_slug, "reviews": reviews, "recurring_weaknesses": weakness_counts.most_common(5)}

