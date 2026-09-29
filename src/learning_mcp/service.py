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

from . import git_tools, git_snapshot, jobs
from .codex_usage import TOKEN_KEYS, empty_usage, scan_incremental, usage_delta
from .config import Settings
from .db import Database
from .obsidian import export_review, render_review
from .projects import ensure_project

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
        with self.db.connect() as connection:
            legacy = connection.execute("SELECT id, project_root, project_name FROM features "
                                        "WHERE project_id IS NULL").fetchall()
        for row in legacy:
            root = Path(row["project_root"])
            if root.is_dir():
                project_id = ensure_project(self.db, root, row["project_name"], now_iso())
                with self.db.connect() as connection:
                    connection.execute("UPDATE features SET project_id = ? WHERE id = ?",
                                       (project_id, row["id"]))

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
        project_id = ensure_project(self.db, Path(root), Path(root).name, now_iso())
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT id FROM features WHERE project_id = ? AND status = 'active' ORDER BY started_at DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            if row:
                connection.execute("UPDATE features SET project_root = ? WHERE id = ?", (root, row["id"]))
        return self._feature(row["id"]) if row else None

    def get_project_context(self, project_root: str) -> dict[str, Any]:
        """
        프로젝트 루트 경로를 해석하여 Git 브랜치, 커밋 HEAD, 현재 활성 기능을 묶어 반환합니다.
        """
        root = git_tools.resolve_root(project_root)
        active = self.current_feature(str(root))
        project_id = ensure_project(self.db, root, root.name, now_iso())
        return {
            "project_id": project_id,
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
        name = project_name or root.name
        project_id = ensure_project(self.db, root, name, now_iso())
        active = self.current_feature(str(root))
        if active:
            raise ValueError(f"feature {active['id']} is already active for {root}")
        starting_snapshot = git_snapshot.baseline(root)
        date = datetime.now().astimezone().strftime("%Y%m%d")
        with self.db.connect() as connection:
            # 오늘 생성된 기능 개수를 기반으로 세 자리 시퀀스 생성
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM features WHERE id LIKE ?", (f"F-{date}-%",)
            ).fetchone()["count"]
            feature_id = f"F-{date}-{count + 1:03d}"
            timestamp = now_iso()
            connection.execute(
                """
                INSERT INTO features (
                    id, project_name, project_slug, project_root, title, goal,
                    success_conditions_json, user_owned_scope_json, ai_allowed_scope_json,
                    baseline_commit, branch, started_at, project_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    starting_snapshot["git:baseline"],
                    starting_snapshot["git:baseline-branch"],
                    timestamp,
                    project_id,
                ),
            )
            # 최초 범위 선언 근거(Evidence) 등록
            connection.execute(
                "INSERT INTO evidence(feature_id, kind, summary, content, source_ref, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (feature_id, "scope", "Feature scope declared", goal, f"feature:{feature_id}", timestamp),
            )
            for ref, content in starting_snapshot.items():
                connection.execute(
                    "INSERT INTO evidence(feature_id, kind, summary, content, source_ref, created_at) "
                    "VALUES (?, 'git-snapshot', ?, ?, ?, ?)",
                    (feature_id, ref, content, f"{feature_id}:{ref}", timestamp),
                )
        self.capture_event(str(root), "feature_started", {"title": title, "goal": goal},
                           feature_id, fingerprint=f"feature-start:{feature_id}")
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
        if self._feature(feature_id)["status"] != "active":
            raise ValueError("decisions require an active feature")
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
        feature = self._feature(feature_id)
        self.capture_event(feature["project_root"], "user_decision" if decided_by == "human" else "decision_candidate",
                           {"question": question, "chosen": chosen_option, "reason": reason}, feature_id,
                           fingerprint=f"decision:{decision_id}")
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
        if self._feature(feature_id)["status"] != "active":
            raise ValueError("debug attempts require an active feature")
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
        feature = self._feature(feature_id)
        self.capture_event(feature["project_root"], "debug_hypothesis",
                           {"symptom": symptom, "hypotheses": hypotheses, "outcome": outcome}, feature_id,
                           fingerprint=f"debug:{attempt_id}")
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

        external_id = path.stem
        timestamp = now_iso()
        with self.db.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM sessions WHERE feature_id = ? AND provider = 'codex' AND external_id = ?",
                (feature_id, external_id),
            ).fetchone()
        after_byte = existing["latest_byte"] if existing else 0
        after_line = existing["latest_line"] if existing and after_byte else 0
        previous = loads(existing["latest_usage_json"], empty_usage()) if existing and after_byte else None
        current, current_line, current_byte, events = scan_incremental(path, after_byte, after_line, previous)
        with self.db.connect() as connection:
            if existing is None:
                # 최초 세션 연동인 경우
                baseline = current if phase == "start" else empty_usage()
                baseline_line = current_line if phase == "start" else 0
                measurement = "exact-feature-delta" if phase == "start" else "whole-session"
                connection.execute(
                    """INSERT INTO sessions
                    (feature_id, provider, external_id, source_path, baseline_usage_json,
                     latest_usage_json, baseline_line, latest_line, latest_byte, measurement, attached_at, updated_at)
                    VALUES (?, 'codex', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        feature_id,
                        external_id,
                        str(path),
                        dumps(baseline),
                        dumps(current),
                        baseline_line,
                        current_line,
                        current_byte,
                        measurement,
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                # 기존 세션 정보 업데이트
                baseline = loads(existing["baseline_usage_json"], empty_usage())
                measurement = existing["measurement"]
                connection.execute(
                    "UPDATE sessions SET latest_usage_json = ?, latest_line = ?, latest_byte = ?, "
                    "source_path = ?, updated_at = ? WHERE id = ?",
                    (dumps(current), current_line, current_byte, str(path), timestamp, existing["id"]),
                )
            
            # 대화 이벤트 가져와서 근거(evidence) 데이터로 등록
            imported = 0
            if phase != "start":
                for event in events:
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

    def request_session_sync(self, feature_id: str, session_file: str,
                             phase: Literal["start", "update", "finish"] = "update") -> dict[str, Any]:
        feature = self._feature(feature_id)
        if feature["status"] != "active":
            raise ValueError("session sync requires an active feature")
        job_id = jobs.enqueue(self.db, "session_sync", {"session_file": session_file, "phase": phase},
                              project_id=feature["project_id"], feature_id=feature_id,
                              dedupe_key=f"session:{feature_id}:{session_file}:{phase}")
        return {"queued": True, "job_id": job_id}

    def capture_event(self, project_root: str, event_type: str, payload: dict[str, Any],
                      feature_id: str | None = None, source: str = "codex",
                      fingerprint: str | None = None) -> dict[str, Any]:
        if not event_type or len(event_type) > 80 or len(dumps(payload)) > 8_000:
            raise ValueError("event type or payload exceeds recording limits")
        root = git_tools.resolve_root(project_root)
        project_id = ensure_project(self.db, root, root.name, now_iso())
        if feature_id and self._feature(feature_id)["project_id"] != project_id:
            raise ValueError("feature belongs to another project")
        with self.db.connect() as connection:
            connection.execute("INSERT OR IGNORE INTO events "
                               "(project_id, feature_id, event_type, source, payload_json, fingerprint, created_at) "
                               "VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (project_id, feature_id, event_type, source, dumps(payload), fingerprint, now_iso()))
            row = connection.execute("SELECT id FROM events WHERE fingerprint = ?", (fingerprint,)).fetchone() if fingerprint else None
            event_id = row["id"] if row else connection.execute("SELECT last_insert_rowid()").fetchone()[0]
        return {"event_id": event_id, "project_id": project_id}

    def request_daily_review(self, project_root: str, review_date: str | None = None) -> dict[str, Any]:
        from datetime import date
        root = git_tools.resolve_root(project_root)
        day = review_date or datetime.now().astimezone().date().isoformat()
        date.fromisoformat(day)
        project_id = ensure_project(self.db, root, root.name, now_iso())
        with self.db.connect() as connection:
            existing = connection.execute("SELECT id FROM daily_reviews WHERE project_id=? AND review_date=?",
                                          (project_id, day)).fetchone()
        if existing:
            return {"queued": False, "review_id": existing["id"], "review_date": day}
        job_id = jobs.enqueue(self.db, "daily_review", {"review_date": day}, project_id=project_id,
                              dedupe_key=f"daily:{project_id}:{day}")
        return {"queued": True, "job_id": job_id, "review_date": day}

    def request_feature_review(self, feature_id: str) -> dict[str, Any]:
        feature = self._feature(feature_id)
        if feature["status"] != "completed" or not feature["snapshot_at"]:
            raise ValueError("feature must have a final Git snapshot before review")
        if feature["review_state"] == "reviewed":
            return {"queued": False, "review_exists": True}
        job_id = jobs.enqueue(self.db, "feature_review", {}, project_id=feature["project_id"],
                              feature_id=feature_id, dedupe_key=f"feature-review:{feature_id}")
        return {"queued": True, "job_id": job_id}

    def evaluate_decision_candidate(self, feature_id: str, description: str, *,
                                    architecture_related: bool = False, hard_to_reverse: bool = False,
                                    new_dependency: bool = False, affects_data_model: bool = False,
                                    concurrency_related: bool = False, repeated_weakness: bool = False,
                                    concept_id: str | None = None) -> dict[str, Any]:
        feature = self._feature(feature_id)
        if feature["status"] != "active":
            raise ValueError("decision candidate requires an active feature")
        score = min(100, sum((30 if architecture_related else 0, 20 if hard_to_reverse else 0,
                              15 if new_dependency else 0, 20 if affects_data_model else 0,
                              20 if concurrency_related else 0, 20 if repeated_weakness else 0)))
        if score < 70:
            return {"importance": score, "should_ask_user": False,
                    "handling": "daily-review" if score >= 40 else "record-only"}
        from .gemini_client import GeminiClient
        from .schemas import JUDGMENT_JSON_SCHEMA, validate_judgment
        import tempfile
        try:
            with tempfile.TemporaryDirectory() as scratch:
                raw = GeminiClient().generate(
                    "Judge whether this architectural decision requires the user's reasoning now. "
                    "Return {should_ask_user:boolean, importance:integer, reason:string, question:string}.",
                    {"description": description[:2000], "rule_score": score},
                    Path(scratch), JUDGMENT_JSON_SCHEMA)
            judgment = validate_judgment(raw)
        except (RuntimeError, ValueError):
            judgment = {"should_ask_user": True, "importance": score,
                        "reason": "high-impact decision identified by deterministic rules",
                        "question": f"{description.strip()} 어떤 선택이 맞다고 생각하시나요? 이유도 설명해주세요."}
        if judgment["should_ask_user"]:
            with self.db.connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO pending_questions(project_id, feature_id, question, reason, importance, concept_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (feature["project_id"], feature_id, judgment["question"], judgment["reason"],
                     judgment["importance"], concept_id, now_iso()))
                judgment["question_id"] = cursor.lastrowid
        return judgment

    def get_pending_questions(self, feature_id: str) -> list[dict[str, Any]]:
        self._feature(feature_id)
        with self.db.connect() as connection:
            rows = connection.execute("SELECT id, question, reason, importance, concept_id "
                                      "FROM pending_questions WHERE feature_id=? AND status='pending' ORDER BY id",
                                      (feature_id,)).fetchall()
        return [dict(row) for row in rows]

    def record_user_answer(self, question_id: int, answer: str) -> dict[str, Any]:
        if not answer.strip():
            raise ValueError("answer is required")
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM pending_questions WHERE id=? AND status='pending'",
                                     (question_id,)).fetchone()
            if row is None:
                raise ValueError("unknown or already answered question")
            timestamp = now_iso()
            connection.execute("UPDATE pending_questions SET status='answered', answer=?, answered_at=? WHERE id=?",
                               (answer.strip(), timestamp, question_id))
            ref = f"answer:{question_id}"
            if row["feature_id"]:
                connection.execute("INSERT INTO evidence(feature_id, kind, summary, content, source_ref, created_at) "
                                   "VALUES (?, 'user-answer', ?, ?, ?, ?)",
                                   (row["feature_id"], row["question"], answer.strip(), ref, timestamp))
            if row["concept_id"]:
                concept = connection.execute("SELECT id FROM concepts WHERE id=?", (row["concept_id"],)).fetchone()
                if concept:
                    next_status = "recalled" if row["reason"] == "delayed recall" else "explained"
                    connection.execute(
                        "UPDATE concepts SET status=CASE "
                        "WHEN ?='recalled' AND status IN ('explained', 'applied') THEN 'recalled' "
                        "WHEN status='discovered' THEN 'explained' ELSE status END, last_seen_at=? WHERE id=?",
                        (next_status, timestamp, row["concept_id"]))
                    connection.execute("INSERT OR IGNORE INTO concept_occurrences "
                                       "(concept_id, project_id, feature_id, evidence_ref, role, created_at) "
                                       "VALUES (?, ?, ?, ?, ?, ?)",
                                       (row["concept_id"], row["project_id"], row["feature_id"], ref,
                                        next_status, timestamp))
        return {"saved": True, "ref": ref}

    def record_review_confirmation(self, feature_id: str, explanation: str) -> dict[str, Any]:
        if not explanation.strip():
            raise ValueError("review confirmation explanation is required")
        self._feature(feature_id)
        with self.db.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO evidence(feature_id, kind, summary, content, created_at) "
                "VALUES (?, 'review-confirmation', 'User confirmed understanding', ?, ?)",
                (feature_id, explanation.strip(), now_iso()))
            ref = f"review-confirmation:{cursor.lastrowid}"
            connection.execute("UPDATE evidence SET source_ref=? WHERE id=?", (ref, cursor.lastrowid))
        return {"saved": True, "ref": ref}

    def get_learning_context(self, feature_id: str) -> dict[str, Any]:
        feature = self._feature(feature_id)
        with self.db.connect() as connection:
            rows = connection.execute(
                "SELECT c.id, c.canonical_name, c.status, COUNT(DISTINCT o.feature_id) AS feature_count "
                "FROM concepts c JOIN concept_occurrences o ON o.concept_id=c.id "
                "WHERE o.project_id=? GROUP BY c.id ORDER BY c.last_seen_at DESC LIMIT 12",
                (feature["project_id"],)).fetchall()
            review_rows = connection.execute(
                "SELECT r.weaknesses_json FROM reviews r JOIN features f ON f.id=r.feature_id "
                "WHERE f.project_id=? AND r.verified=1 AND r.id IN "
                "(SELECT MAX(id) FROM reviews WHERE verified=1 GROUP BY feature_id) ORDER BY r.id DESC LIMIT 10",
                (feature["project_id"],)).fetchall()
            daily_rows = connection.execute(
                "SELECT result_json FROM daily_reviews WHERE project_id=? ORDER BY review_date DESC LIMIT 14",
                (feature["project_id"],)).fetchall()
        weaknesses: Counter[str] = Counter()
        for row in review_rows:
            weaknesses.update(set(loads(row["weaknesses_json"], [])))
        for row in daily_rows:
            weaknesses.update({item["concept"] for item in loads(row["result_json"], {}).get("weaknesses", [])})
        return {"concepts": [dict(row) for row in rows], "repeated_weaknesses": weaknesses.most_common(5)}

    def record_concept_use(self, feature_id: str, concept_id: str, evidence_ref: str) -> dict[str, Any]:
        from datetime import timedelta
        feature = self._feature(feature_id)
        with self.db.connect() as connection:
            concept = connection.execute("SELECT id FROM concepts WHERE id=?", (concept_id,)).fetchone()
            if concept is None:
                raise ValueError("unknown concept")
            evidence = connection.execute("SELECT 1 FROM evidence WHERE feature_id=? AND "
                                          "(source_ref=? OR ('evidence:' || id)=?)",
                                          (feature_id, evidence_ref, evidence_ref)).fetchone()
            if evidence is None:
                raise ValueError("evidence ref does not belong to feature")
            connection.execute("INSERT OR IGNORE INTO concept_occurrences "
                               "(concept_id, project_id, feature_id, evidence_ref, role, created_at) "
                               "VALUES (?, ?, ?, ?, 'used', ?)",
                               (concept_id, feature["project_id"], feature_id, evidence_ref, now_iso()))
            count = connection.execute("SELECT COUNT(DISTINCT feature_id) FROM concept_occurrences "
                                       "WHERE concept_id=? AND role='used'", (concept_id,)).fetchone()[0]
            if count >= 2:
                connection.execute("UPDATE concepts SET status=CASE WHEN status IN ('discovered', 'explained') "
                                   "THEN 'applied' ELSE status END, last_seen_at=? WHERE id=?",
                                   (now_iso(), concept_id))
            prior = connection.execute("SELECT MAX(created_at) FROM concept_occurrences "
                                       "WHERE concept_id=? AND role='explained'", (concept_id,)).fetchone()[0]
            pending = connection.execute("SELECT 1 FROM pending_questions WHERE feature_id=? AND concept_id=? "
                                         "AND reason='delayed recall' AND status='pending'",
                                         (feature_id, concept_id)).fetchone()
            if prior and not pending and datetime.fromisoformat(prior) <= datetime.now().astimezone() - timedelta(days=7):
                name = connection.execute("SELECT canonical_name FROM concepts WHERE id=?", (concept_id,)).fetchone()[0]
                connection.execute("INSERT INTO pending_questions "
                                   "(project_id, feature_id, question, reason, importance, concept_id, created_at) "
                                   "VALUES (?, ?, ?, 'delayed recall', 70, ?, ?)",
                                   (feature["project_id"], feature_id,
                                    f"{name}를 지금 코드와 연결해 본인 말로 설명해 보세요.", concept_id, now_iso()))
        return {"concept_id": concept_id, "distinct_features_used": count}

    def record_mastery_confirmation(self, feature_id: str, concept_id: str, explanation: str) -> dict[str, Any]:
        if not explanation.strip():
            raise ValueError("explanation is required")
        feature = self._feature(feature_id)
        with self.db.connect() as connection:
            concept = connection.execute("SELECT status FROM concepts WHERE id=?", (concept_id,)).fetchone()
            if concept is None or concept["status"] != "recalled":
                raise ValueError("concept must be recalled before mastery confirmation")
            count = connection.execute("SELECT COUNT(DISTINCT feature_id) FROM concept_occurrences "
                                       "WHERE concept_id=? AND role='used'", (concept_id,)).fetchone()[0]
            if count < 2:
                raise ValueError("mastery requires use in at least two features")
            cursor = connection.execute("INSERT INTO evidence(feature_id, kind, summary, content, created_at) "
                                        "VALUES (?, 'mastery-confirmation', ?, ?, ?)",
                                        (feature_id, concept_id, explanation.strip(), now_iso()))
            ref = f"mastery:{cursor.lastrowid}"
            connection.execute("UPDATE evidence SET source_ref=? WHERE id=?", (ref, cursor.lastrowid))
            connection.execute("INSERT INTO concept_occurrences "
                               "(concept_id, project_id, feature_id, evidence_ref, role, created_at) "
                               "VALUES (?, ?, ?, ?, 'mastered', ?)",
                               (concept_id, feature["project_id"], feature_id, ref, now_iso()))
            connection.execute("UPDATE concepts SET status='mastered', last_seen_at=? WHERE id=?",
                               (now_iso(), concept_id))
        return {"concept_id": concept_id, "status": "mastered", "ref": ref}

    def request_delayed_recall(self, feature_id: str, concept_id: str, days: int = 7) -> dict[str, Any]:
        from datetime import timedelta
        feature = self._feature(feature_id)
        with self.db.connect() as connection:
            concept = connection.execute("SELECT canonical_name, status FROM concepts WHERE id=?",
                                         (concept_id,)).fetchone()
            previous = connection.execute("SELECT MAX(created_at) FROM concept_occurrences "
                                          "WHERE concept_id=? AND role='explained'", (concept_id,)).fetchone()[0]
            if concept is None or previous is None:
                raise ValueError("concept needs a prior user explanation")
            if datetime.fromisoformat(previous) > datetime.now().astimezone() - timedelta(days=days):
                raise ValueError("delayed recall interval has not elapsed")
            cursor = connection.execute("INSERT INTO pending_questions "
                                        "(project_id, feature_id, question, reason, importance, concept_id, created_at) "
                                        "VALUES (?, ?, ?, 'delayed recall', 70, ?, ?)",
                                        (feature["project_id"], feature_id,
                                         f"{concept['canonical_name']}를 지금 코드와 연결해 본인 말로 설명해 보세요.",
                                         concept_id, now_iso()))
        return {"question_id": cursor.lastrowid, "question": f"{concept['canonical_name']}를 지금 코드와 연결해 본인 말로 설명해 보세요."}

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
                "end_commit": feature["end_commit"],
                "status": (git_tools.status(root) if feature["status"] == "active" else "")[:2_000],
                "working_stat": (git_tools.diff_stat(root) if feature["status"] == "active" else "")[:2_000],
                "staged_stat": (git_tools.diff_stat(root, staged=True) if feature["status"] == "active" else "")[:2_000],
                "evidence_refs": ["diff:working", "diff:staged"] if feature["status"] == "active" else
                                 ["git:feature-diff", "git:commits", "git:working-final", "git:staged-final", "git:untracked-final"],
            },
            "token_usage": token_totals,
            "sessions": sessions,
            "decisions": [dict(row) | {"ref": f"decision:{row['id']}"} for row in decisions],
            "debug_attempts": [dict(row) | {"ref": f"debug:{row['id']}"} for row in debug],
            "evidence_index": [dict(row) | {"ref": f"evidence:{row['id']}"} for row in evidence],
        }
        if detail == "standard":
            manifest["recent_learning"] = self.get_learning_history(feature["project_id"], limit=5)
        
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
                if ref.startswith("git:"):
                    row = connection.execute(
                        "SELECT content FROM evidence WHERE feature_id = ? AND source_ref = ?", (feature_id, f"{feature_id}:{ref}")
                    ).fetchone()
                    content = row["content"] if row else ""
                elif ref == "diff:working" and feature["status"] != "active":
                    raise ValueError("live diff is unavailable after feature completion; use git:working-final")
                elif ref == "diff:staged" and feature["status"] != "active":
                    raise ValueError("live diff is unavailable after feature completion; use git:staged-final")
                elif ref == "diff:working":
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
        verification_ref: str | None = None,
    ) -> dict[str, Any]:
        """
        기능 개발 완료 후 종합 회고 리뷰를 DB에 저장하고, Obsidian Vault가 설정된 경우 마크다운 파일로 내보냅니다.
        """
        feature = self._feature(feature_id)
        if verified:
            if not verification_ref:
                raise ValueError("verified review requires a user confirmation ref")
            with self.db.connect() as connection:
                confirmation = connection.execute(
                    "SELECT 1 FROM evidence WHERE feature_id=? AND source_ref=? AND kind='review-confirmation'",
                    (feature_id, verification_ref)).fetchone()
            if confirmation is None:
                raise ValueError("verified review requires a valid user confirmation ref")
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
                 weaknesses_json, next_topics_json, verified, obsidian_path, created_at, verification_ref)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    verification_ref,
                ),
            )
            review_id = cursor.lastrowid
            connection.execute("UPDATE features SET review_state='reviewed' WHERE id=?", (feature_id,))
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
        if feature["status"] != "active":
            raise ValueError("feature is already completed")
        root = Path(feature["project_root"])
        snapshot = git_snapshot.capture(root, feature["baseline_commit"])
        with self.db.connect() as connection:
            session_rows = connection.execute(
                "SELECT source_path FROM sessions WHERE feature_id = ? AND provider = 'codex'",
                (feature_id,),
            ).fetchall()
        queued_sessions = []
        for row in session_rows:
            path = Path(row["source_path"])
            if path.is_file():
                queued_sessions.append(jobs.enqueue(
                    self.db, "session_sync", {"session_file": str(path), "phase": "finish"},
                    project_id=feature["project_id"], feature_id=feature_id, priority=70,
                    dedupe_key=f"session:{feature_id}:{path}:finish"))
        timestamp = now_iso()
        with self.db.connect() as connection:
            for ref, content in snapshot.items():
                connection.execute(
                    "INSERT INTO evidence(feature_id, kind, summary, content, source_ref, created_at) "
                    "VALUES (?, 'git-snapshot', ?, ?, ?, ?)",
                    (feature_id, ref, content, f"{feature_id}:{ref}", timestamp),
                )
            connection.execute(
                "UPDATE features SET status = 'completed', finished_at = ?, end_commit = ?, snapshot_at = ?, "
                "review_state = CASE WHEN review_state='reviewed' THEN 'reviewed' ELSE 'review_pending' END WHERE id = ?",
                (timestamp, snapshot["git:end"], timestamp, feature_id),
            )
        tokens, _ = self._token_totals(feature_id)
        self.capture_event(str(root), "feature_finished", {"end_commit": snapshot["git:end"]}, feature_id,
                           fingerprint=f"feature-finish:{feature_id}")
        return {"feature_id": feature_id, "status": "completed", "finished_at": timestamp,
                "token_usage": tokens, "sessions_queued": len(queued_sessions)}

    def get_learning_history(self, project_slug: str, limit: int = 10) -> dict[str, Any]:
        """
        해당 프로젝트의 최근 회고 리뷰 기록을 가져오고, 자주 발생하는 약점 패턴 상위 5개를 집계합니다.
        """
        limit = max(1, min(limit, 30))
        with self.db.connect() as connection:
            rows = connection.execute(
                """SELECT r.*, f.title, f.id AS feature_id FROM reviews r
                JOIN features f ON f.id = r.feature_id
                WHERE (f.project_slug = ? OR f.project_id = ?) ORDER BY r.created_at DESC LIMIT ?""",
                (project_slug, project_slug, limit),
            ).fetchall()
            verified_rows = connection.execute(
                "SELECT r.weaknesses_json FROM reviews r JOIN features f ON f.id=r.feature_id "
                "WHERE (f.project_slug=? OR f.project_id=?) AND r.verified=1 AND r.id IN "
                "(SELECT MAX(id) FROM reviews WHERE verified=1 GROUP BY feature_id)",
                (project_slug, project_slug),
            ).fetchall()
        weakness_counts: Counter[str] = Counter()
        for row in verified_rows:
            weakness_counts.update(set(loads(row["weaknesses_json"], [])))
        reviews = []
        for row in rows:
            weaknesses = loads(row["weaknesses_json"], [])
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

