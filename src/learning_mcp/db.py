"""
SQLite 데이터베이스 스키마 및 접속 관리 모듈입니다.

기능(features), 결정 사항(decisions), 디버깅 시도(debug_attempts),
Codex 세션(sessions), 학습 리뷰(reviews), 근거/증거 데이터(evidence) 테이블을 정의하고
데이터베이스 초기화 및 마이그레이션(컬럼 추가 등) 및 컨텍스트 매니저 기반 커넥션을 처리합니다.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# SQLite 데이터베이스 테이블 및 인덱스 생성 DDL 스키마
SCHEMA = """
-- 외래 키(Foreign Key) 제약 조건 활성화
PRAGMA foreign_keys = ON;

-- 1. 기능(features) 테이블: 개발자가 진행하는 각 기능/태스크 정보 관리
CREATE TABLE IF NOT EXISTS features (
    id TEXT PRIMARY KEY,                       -- 기능 고유 ID (예: F-20260825-001)
    project_name TEXT NOT NULL,                -- 프로젝트명
    project_slug TEXT NOT NULL,                -- URL/파일명 식별용 슬러그명
    project_root TEXT NOT NULL,                -- 프로젝트 Git 루트 absolute 경로
    title TEXT NOT NULL,                       -- 기능 제목
    goal TEXT NOT NULL,                        -- 기능의 상세 목표
    success_conditions_json TEXT NOT NULL,     -- 성공 조건 목록 (JSON)
    user_owned_scope_json TEXT NOT NULL,       -- 개발자(사용자) 담당 범위 (JSON)
    ai_allowed_scope_json TEXT NOT NULL,       -- AI 지원 허용 범위 (JSON)
    status TEXT NOT NULL DEFAULT 'active',     -- 상태 ('active' 또는 'completed')
    baseline_commit TEXT,                      -- 기능 시작 시점의 Git 커밋 SHA
    branch TEXT,                               -- 작업 Git 브랜치명
    started_at TEXT NOT NULL,                  -- 시작 일시 (ISO 형식)
    finished_at TEXT                           -- 완료 일시 (ISO 형식)
);

-- 프로젝트 루트 및 상태별 빠른 조회를 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_features_project_status
ON features(project_root, status);

-- 2. 결정 사항(decisions) 테이블: 아키텍처 및 구현 관련 중요 판단 기록
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,      -- 결정 고유 ID
    feature_id TEXT NOT NULL REFERENCES features(id) ON DELETE CASCADE,  -- 참조 기능 ID
    question TEXT NOT NULL,                    -- 고민했던 문제/질문
    chosen_option TEXT NOT NULL,               -- 선택한 대안
    reason TEXT NOT NULL,                      -- 선택 이유
    alternatives_json TEXT NOT NULL,           -- 검토했던 다른 대안들 (JSON)
    decided_by TEXT NOT NULL,                  -- 결정 주체 ('human', 'shared', 'ai')
    created_at TEXT NOT NULL                   -- 생성 일시
);

-- 3. 디버깅 시도(debug_attempts) 테이블: 문제 해결 시도 기록
CREATE TABLE IF NOT EXISTS debug_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,      -- 디버깅 시도 ID
    feature_id TEXT NOT NULL REFERENCES features(id) ON DELETE CASCADE,  -- 참조 기능 ID
    symptom TEXT NOT NULL,                     -- 발생한 버그/증상
    hypotheses_json TEXT NOT NULL,             -- 가설 목록 (JSON)
    verification TEXT NOT NULL,                -- 검증 방법 및 실행 내용
    outcome TEXT NOT NULL,                     -- 검증 결과
    status TEXT NOT NULL,                      -- 상태 ('open', 'confirmed', 'rejected', 'resolved')
    created_at TEXT NOT NULL                   -- 생성 일시
);

-- 4. 세션(sessions) 테이블: Codex 세션 토큰 사용량 연동 관리
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,      -- 세션 ID
    feature_id TEXT NOT NULL REFERENCES features(id) ON DELETE CASCADE,  -- 참조 기능 ID
    provider TEXT NOT NULL,                    -- 프로바이더 ('codex')
    external_id TEXT NOT NULL,                 -- 외부 세션 ID (파일 스템명)
    source_path TEXT NOT NULL,                 -- JSONL 세션 로그 파일 경로
    baseline_usage_json TEXT NOT NULL,         -- 시작 시점 토큰 사용량 (JSON)
    latest_usage_json TEXT NOT NULL,           -- 최근 시점 토큰 사용량 (JSON)
    baseline_line INTEGER NOT NULL DEFAULT 0,  -- 시작 시점 JSONL 줄 번호
    latest_line INTEGER NOT NULL DEFAULT 0,    -- 최근 시점 JSONL 줄 번호
    measurement TEXT NOT NULL,                 -- 측정 방식 ('exact-feature-delta' / 'whole-session')
    attached_at TEXT NOT NULL,                 -- 연동 일시
    updated_at TEXT NOT NULL,                  -- 갱신 일시
    UNIQUE(feature_id, provider, external_id)
);

-- 5. 학습 리뷰(reviews) 테이블: 기능 완료 후 회고 및 평가
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,      -- 리뷰 ID
    feature_id TEXT NOT NULL REFERENCES features(id) ON DELETE CASCADE,  -- 참조 기능 ID
    summary TEXT NOT NULL,                     -- 학습 리뷰 요약
    code_flow TEXT NOT NULL,                   -- 구현한 코드의 실행 흐름 설명
    ownership_json TEXT NOT NULL,              -- 영역별 기여도 판정 (JSON)
    alternatives_json TEXT NOT NULL,           -- 대안 기술 목록 (JSON)
    weaknesses_json TEXT NOT NULL,             -- 도출된 약점 목록 (JSON)
    next_topics_json TEXT NOT NULL,            -- 후속 학습 주제 목록 (JSON)
    verified INTEGER NOT NULL DEFAULT 0,       -- 리뷰 검증 여부 (0: false, 1: true)
    obsidian_path TEXT,                        -- Obsidian 내보내기 상대 경로
    official_sources_json TEXT NOT NULL DEFAULT '[]', -- 공식 기술 문서 링크
    created_at TEXT NOT NULL                   -- 생성 일시
);

-- 6. 근거/증거(evidence) 테이블: 세션 대화, 디버깅, 결정 사항 등 모든 원본 근거 인덱싱
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,      -- 근거 ID
    feature_id TEXT NOT NULL REFERENCES features(id) ON DELETE CASCADE,  -- 참조 기능 ID
    kind TEXT NOT NULL,                        -- 근거 종류 ('scope', 'decision', 'debug', 'conversation-user', 등)
    summary TEXT NOT NULL,                     -- 요약 문구
    content TEXT NOT NULL,                     -- 상세 내용
    source_ref TEXT,                           -- 원본 참조 태그 (예: decision:1, codex:session:line:10)
    created_at TEXT NOT NULL                   -- 생성 일시
);

-- 근거 검색 최적화 인덱스
CREATE INDEX IF NOT EXISTS idx_evidence_feature_kind
ON evidence(feature_id, kind);

-- 원본 참조 중복 방지 유니크 인덱스
CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_source_ref
ON evidence(source_ref) WHERE source_ref IS NOT NULL;

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    repository_key TEXT UNIQUE,
    git_remote TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_roots (
    project_id TEXT NOT NULL REFERENCES projects(id),
    local_root TEXT NOT NULL PRIMARY KEY,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    feature_id TEXT,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    fingerprint TEXT UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    project_id TEXT,
    feature_id TEXT,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 50,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    dedupe_key TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_priority ON jobs(status, priority DESC, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_dedupe_active ON jobs(dedupe_key)
WHERE dedupe_key IS NOT NULL AND status IN ('pending', 'running');

CREATE TABLE IF NOT EXISTS daily_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id),
    review_date TEXT NOT NULL,
    result_json TEXT NOT NULL,
    obsidian_path TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, review_date)
);
CREATE TABLE IF NOT EXISTS concepts (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    concept_type TEXT NOT NULL,
    category TEXT,
    parent_concept_id TEXT,
    obsidian_path TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS concept_occurrences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL REFERENCES concepts(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    feature_id TEXT,
    evidence_ref TEXT,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(concept_id, project_id, feature_id, evidence_ref, role)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_concept_occurrences_unique ON concept_occurrences(
    concept_id, project_id, COALESCE(feature_id, ''), COALESCE(evidence_ref, ''), role
);
CREATE TABLE IF NOT EXISTS pending_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id),
    feature_id TEXT REFERENCES features(id),
    question TEXT NOT NULL,
    reason TEXT NOT NULL,
    importance INTEGER NOT NULL,
    concept_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    answer TEXT,
    created_at TEXT NOT NULL,
    answered_at TEXT
);

CREATE TABLE IF NOT EXISTS runtime_state (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Database:
    """
    SQLite 데이터베이스 접속 및 테이블 생성을 담당하는 래퍼 클래스입니다.
    """
    def __init__(self, path: Path):
        """
        데이터베이스 파일 경로를 받아 디렉토리를 생성하고 테이블 및 마이그레이션을 수행합니다.
        """
        self.path = path
        # 데이터베이스 저장 폴더가 없으면 생성
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            # 테이블 및 인덱스 스키마 실행
            connection.executescript(SCHEMA)
            # 마이그레이션: sessions 테이블에 baseline_line, latest_line 컬럼이 없으면 추가
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}
            if "baseline_line" not in columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN baseline_line INTEGER NOT NULL DEFAULT 0")
            if "latest_line" not in columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN latest_line INTEGER NOT NULL DEFAULT 0")
            if "latest_byte" not in columns:
                connection.execute("ALTER TABLE sessions ADD COLUMN latest_byte INTEGER NOT NULL DEFAULT 0")
            feature_columns = {row["name"] for row in connection.execute("PRAGMA table_info(features)")}
            for name in ("project_id", "end_commit", "snapshot_at"):
                if name not in feature_columns:
                    connection.execute(f"ALTER TABLE features ADD COLUMN {name} TEXT")
            if "review_state" not in feature_columns:
                connection.execute("ALTER TABLE features ADD COLUMN review_state TEXT NOT NULL DEFAULT 'unreviewed'")
            review_columns = {row["name"] for row in connection.execute("PRAGMA table_info(reviews)")}
            if "verification_ref" not in review_columns:
                connection.execute("ALTER TABLE reviews ADD COLUMN verification_ref TEXT")
            if "official_sources_json" not in review_columns:
                connection.execute("ALTER TABLE reviews ADD COLUMN official_sources_json TEXT NOT NULL DEFAULT '[]'")
            connection.execute("UPDATE features SET review_state='reviewed' WHERE review_state='unreviewed' "
                               "AND EXISTS (SELECT 1 FROM reviews WHERE reviews.feature_id=features.id)")
            connection.execute("UPDATE features SET review_state='review_pending' "
                               "WHERE review_state='unreviewed' AND status='completed'")
            connection.execute("PRAGMA busy_timeout = 5000")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """
        안전한 데이터베이스 커넥션을 제공하는 컨텍스트 매니저입니다.
        정상 종료 시 자동 commit, 예외 발생 시 rollback 및 close를 보장합니다.
        """
        connection = sqlite3.connect(self.path)
        # 딕셔너리처럼 컬럼명으로 접근 가능하도록 row_factory 설정
        connection.row_factory = sqlite3.Row
        # FK(외래키) 지원 명시적 활성화
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
