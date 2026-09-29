# Learning MCP 개선안 v2

> 목표: **개발자는 평소처럼 Codex로 개발하고, Learning MCP는 개발 흐름을 거의 방해하지 않으면서 증거를 수집한다. 중요한 판단이 필요한 순간에만 사용자에게 질문하고, 하루가 끝나면 Gemini가 실제 개발 기록을 바탕으로 CS 지식·개발 개념·의사결정·디버깅 학습 내용을 정리한다. 최종 결과는 Python 코드가 검증하여 Obsidian에 저장한다.**

---

## 0. 핵심 방향

기존 Learning MCP는 `feature 시작 → 기록 → review → Obsidian` 흐름이지만, 사용자가 학습용 명령을 자주 호출해야 하고 Git 증거가 현재 상태에 의존하는 문제가 있다.

v2에서는 다음 원칙으로 바꾼다.

1. **개발은 Codex가 담당한다.**
2. **기록 수집은 최대한 Python 코드가 담당한다.**
3. **판단이 필요할 때만 Gemini를 사용한다.**
4. **Gemini는 파일을 직접 수정하지 않고 구조화된 JSON만 반환한다.**
5. **Obsidian 파일 작성·병합·중복 제거는 Python 코드가 담당한다.**
6. **기록 작업은 개발 흐름을 막지 않도록 background worker로 처리한다.**
7. **중요한 설계 판단이나 디버깅 가설처럼 사용자 사고가 필요한 순간만 개발 중 동기적으로 질문한다.**
8. **Git 증거는 조회 시점의 working tree가 아니라 immutable snapshot으로 보존한다.**
9. **토큰 사용량은 참고 데이터일 뿐 학습 기여도 판단 근거로 직접 사용하지 않는다.**
10. **최종 목적은 개발 기록이 아니라 실제 CS/개발 지식의 축적과 재학습이다.**

---

# 1. 최종 아키텍처

```text
┌────────────────────────────────────────────┐
│                    User                    │
└──────────────────────┬─────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────┐
│                   Codex                    │
│                                            │
│ - 코드 구현                                │
│ - 코드 수정                                │
│ - 테스트 실행                              │
│ - 현재 개발 문맥 유지                      │
│ - 중요한 판단이 발생하면 사용자에게 질문   │
└──────────────────────┬─────────────────────┘
                       │
                lightweight MCP call
                       │
                       ▼
┌────────────────────────────────────────────┐
│               Learning MCP                 │
│                                            │
│ - feature/project 상태                     │
│ - event enqueue                            │
│ - user decision 저장                       │
│ - learning context 조회                    │
│ - background job 상태                      │
└──────────────────────┬─────────────────────┘
                       │
                 SQLite transaction
                       │
                       ▼
┌────────────────────────────────────────────┐
│                 SQLite                     │
│                                            │
│ projects / features / events / jobs        │
│ evidence / decisions / debug_attempts      │
│ concepts / concept_occurrences             │
│ reviews / learning_state                   │
└──────────────────────┬─────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────┐
│          learning-mcp-worker               │
│                                            │
│ Python deterministic processing            │
│                                            │
│ - Git snapshot                             │
│ - commit range                             │
│ - untracked file detection                 │
│ - conversation incremental parsing         │
│ - test result normalization                │
│ - event deduplication                      │
│ - evidence packet generation               │
│ - Gemini CLI invocation                    │
│ - JSON schema validation                   │
│ - Obsidian merge/write                     │
└──────────────────────┬─────────────────────┘
                       │
             only when semantic judgment
                       │
                       ▼
┌────────────────────────────────────────────┐
│                 Gemini                     │
│                                            │
│ - 중요 결정 판별                           │
│ - 사용자 판단 필요 여부                    │
│ - 기술 개념 추출                           │
│ - CS 원리 연결                             │
│ - 학습 리뷰                                │
│ - 오해/부족한 부분 분석                    │
│ - 복습 후보 선정                           │
│                                            │
│ OUTPUT: structured JSON only               │
└──────────────────────┬─────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────┐
│               Obsidian                     │
│                                            │
│ Daily Development Notes                    │
│ CS Concepts                                │
│ Development Concepts                       │
│ Project / Feature Reviews                  │
│ Debugging Cases                            │
│ Learning State                             │
└────────────────────────────────────────────┘
```

---

# 2. 역할 분리

## 2.1 Codex

Codex는 **개발에 집중**한다.

담당:

- 요구사항을 코드로 구현
- 코드베이스 탐색
- 리팩터링
- 테스트 실행
- 오류 수정
- 사용자와 현재 개발 문맥 논의
- 중요한 결정이 감지되었을 때 사용자 질문

담당하지 않도록 할 것:

- 하루 전체 개발 기록 장문 요약
- Obsidian Markdown 생성
- 과거 전체 학습 기록 반복 조회
- CS 개념 노트 직접 작성
- 반복적인 로그 정리
- 장시간 feature review

Codex의 context를 개발에 필요한 정보 중심으로 유지한다.

---

## 2.2 Learning MCP

Learning MCP는 **빠른 API + 상태 저장 계층**이다.

원칙:

```text
MCP call
→ validation
→ SQLite INSERT / SELECT
→ 즉시 응답
```

MCP 호출 안에서 다음을 수행하지 않는다.

```text
X 긴 Git 분석
X 전체 대화 파싱
X Gemini 실행
X Obsidian 생성
X 장문의 리뷰 생성
```

무거운 작업은 모두 `jobs` 테이블에 넣고 Worker가 처리한다.

---

## 2.3 Python 코드

LLM이 필요 없는 것은 최대한 Python으로 처리한다.

### Python 담당

- Git root 정규화
- stable project ID 계산
- HEAD / branch / remote 확인
- baseline commit 저장
- end commit 저장
- commit range 계산
- changed file 목록 계산
- staged / unstaged / untracked 파일 수집
- diff snapshot 생성
- session JSONL incremental parsing
- test command/result 저장
- event deduplication
- evidence ref 생성
- concept ID 생성
- Obsidian 경로 생성
- 기존 concept note 탐색
- 동일 개념 중복 방지
- YAML frontmatter 생성
- JSON schema validation
- retry
- job state 관리
- daily boundary 계산
- evidence packet 압축
- deterministic statistics

### Gemini에게 보내지 않을 것

```text
"파일 7개가 바뀌었는가?"
"HEAD가 무엇인가?"
"테스트 exit code가 0인가?"
"이 event가 중복인가?"
"이 concept note가 이미 존재하는가?"
```

이런 것은 코드로 결정한다.

---

## 2.4 Gemini

Gemini는 **의미 판단이 필요한 부분만 담당**한다.

### Gemini 담당

1. 지금 발생한 변화가 중요한 기술적 결정인가?
2. 사용자에게 지금 질문해야 하는가?
3. 이 개발 과정에서 핵심 기술 개념은 무엇인가?
4. 해당 기술의 기반 CS 개념은 무엇인가?
5. 사용자 발언에서 실제 사용자 판단은 무엇인가?
6. 사용자가 오해하거나 이해가 부족한 부분은 무엇인가?
7. 어떤 개념을 기존 Obsidian note에 연결해야 하는가?
8. 오늘 학습 내용에서 복습 가치가 높은 항목은 무엇인가?
9. ownership을 어떻게 판단할 수 있는가?
10. review 결과를 어떤 구조로 정리할 것인가?

Gemini는 **직접 파일을 수정하지 않는다.**

항상:

```text
Evidence Packet
→ Gemini
→ JSON
→ Python validation
→ DB / Obsidian
```

순서를 사용한다.

---

# 3. 개발 중 UX

## 목표

사용자는 Learning MCP를 거의 의식하지 않는다.

### 일반적인 흐름

```text
사용자:
상품 검색 API 만들어줘.

Codex:
구현 시작.

[Learning MCP는 feature/event를 기록]

Codex:
Repository에서 정렬을 처리할지 Service에서 처리할지
설계 선택이 필요합니다.

이 부분은 이후 필터 추가 가능성에도 영향을 줍니다.
어느 쪽이 맞다고 생각하세요?

사용자:
Service가 맞는 것 같아.
나중에 다른 Repository로 바뀌어도 로직을 유지할 수 있으니까.

Codex:
그 방향으로 구현하겠습니다.

[Learning MCP에 사용자 판단 저장]

→ 개발 계속
```

사용자는 별도로:

```text
$record-decision
$save-log
$learning-review
```

같은 명령을 계속 입력할 필요가 없어야 한다.

---

# 4. 질문해야 하는 순간

모든 것을 질문하면 개발이 방해된다.

따라서 `Decision Gate`를 둔다.

## 즉시 질문 대상

### Architecture

- DB 선택
- 상태 관리 방식
- 계층 분리
- 데이터 흐름
- sync / async 선택
- Queue 도입
- Cache 전략
- API 방식
- 책임 위치
- 중요한 dependency 도입
- data model 변경

### CS / 시스템

- thread / process
- concurrency
- race condition
- locking
- transaction
- isolation
- indexing
- memory / DB tradeoff
- network protocol
- I/O blocking
- event loop

### Debugging

원인이 명확하지 않고 가설 검증이 필요한 오류.

예:

```text
"이 오류 원인이 무엇이라고 예상하세요?"
```

### 이미 반복된 약점

과거 learning history에서 사용자가 어려워했던 개념이 다시 등장한 경우.

---

# 5. 질문하지 않는 순간

- 변수 이름
- 단순 파일 이동
- formatting
- 반복 boilerplate
- import 추가
- 명확한 syntax error
- 단순 typo
- 사용자가 이미 방향을 명확하게 지시한 경우
- 이미 동일 feature에서 충분히 확인한 개념

---

# 6. Decision Importance

초기에는 복잡한 ML 없이 rule + Gemini 조합으로 간다.

## Python rule 기반 candidate

예:

```python
score = 0

if architecture_related:
    score += 30

if hard_to_reverse:
    score += 20

if new_dependency:
    score += 15

if affects_data_model:
    score += 20

if concurrency_related:
    score += 20

if repeated_weakness:
    score += 20
```

### 처리

```text
0 ~ 39
→ 자동 기록만

40 ~ 69
→ daily review에서 다룸

70 이상
→ Gemini로 중요도/질문 필요 여부 최종 판단
```

Gemini 결과:

```json
{
  "should_ask_user": true,
  "importance": 86,
  "reason": "책임 분리와 향후 확장성에 영향을 주는 아키텍처 결정",
  "question": "정렬 로직을 Repository와 Service 중 어디에 두는 게 맞다고 생각하세요? 이유도 함께 설명해주세요."
}
```

---

# 7. 비동기 처리 구조

## 문제

기존 방식:

```text
Codex
→ MCP
→ Git 분석
→ 대화 분석
→ 리뷰 생성
→ Obsidian
→ 응답

사용자는 기다림
```

## 개선

```text
Codex
→ MCP enqueue_event()
→ SQLite INSERT
→ 즉시 응답

사용자는 바로 개발 계속
```

뒤에서는:

```text
learning-mcp-worker
→ pending job 조회
→ 처리
→ 완료
```

---

# 8. Worker

새 실행 진입점:

```bash
uv run learning-mcp-worker
```

구조 예:

```text
src/learning_mcp/
├── server.py
├── service.py
├── db.py
├── worker.py
├── jobs.py
├── git_tools.py
├── evidence.py
├── project_identity.py
├── providers/
│   ├── base.py
│   └── codex.py
├── gemini/
│   ├── client.py
│   ├── schemas.py
│   └── prompts.py
└── obsidian/
    ├── writer.py
    ├── concepts.py
    └── daily.py
```

---

# 9. SQLite Job Queue

Redis / RabbitMQ / Celery는 현재 필요 없다.

개인용 local-first이므로 SQLite로 충분하다.

## jobs

```sql
CREATE TABLE jobs (
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
    finished_at TEXT
);

CREATE INDEX idx_jobs_status_priority
ON jobs(status, priority DESC, created_at);
```

status:

```text
pending
running
completed
failed
```

---

# 10. Event 모델

## events

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    feature_id TEXT,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    fingerprint TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_events_fingerprint
ON events(fingerprint)
WHERE fingerprint IS NOT NULL;
```

event 예:

```text
feature_started
git_changed
commit_created
test_run
test_failed
error_observed
decision_candidate
user_decision
debug_hypothesis
conversation_sync
feature_finished
session_inactive
daily_digest_requested
```

---

# 11. Immutable Git Evidence

이 부분은 v2의 최우선 개선점이다.

## Feature 시작

저장:

```text
baseline_commit
baseline_branch
baseline_status
baseline_untracked_files
```

## Feature 종료

저장:

```text
end_commit
commit_range
changed_files
committed_diff
staged_diff
working_diff
untracked_files
```

그리고 결과를 `evidence`에 snapshot으로 저장한다.

즉 이후:

```text
diff:feature
```

를 요청하면 현재 Git 상태를 다시 읽는 것이 아니라 저장된 immutable evidence를 반환한다.

## 신규 evidence refs

```text
git:baseline
git:feature-diff
git:commits
git:working-final
git:staged-final
git:untracked-final
test:<id>
conversation:<id>
decision:<id>
debug:<id>
```

---

# 12. Project identity 개선

현재 absolute path와 한글 slug 중심 식별은 제거한다.

## projects

```sql
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    git_remote TEXT,
    repository_key TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

project id 예:

```text
P-a83f9c12
```

identity 우선순위:

```text
normalized git remote
→ git repository metadata
→ fallback generated UUID
```

local path는 별도 alias로 관리:

```sql
CREATE TABLE project_roots (
    project_id TEXT NOT NULL,
    local_root TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);
```

프로젝트 폴더를 이동해도 동일 project로 인식 가능하게 한다.

---

# 13. Feature lifecycle 강제

Skill prompt가 아니라 서버가 강제한다.

권장 상태:

```text
active
↓
review_pending
↓
reviewed
↓
completed
```

별도로:

```text
review_verified = true / false
```

를 둔다.

## 예

`finish_feature()` 조건:

```text
- active feature인지
- final Git snapshot 생성 완료
- pending critical job이 없는지
```

검사.

`verified=true`는 단순 bool 입력을 그대로 믿지 않는다.

최소한 사용자 teach-back evidence 또는 user confirmation ref가 있어야 한다.

---

# 14. Ownership 개선

현재:

```json
{
  "architecture": "shared"
}
```

형태를 변경한다.

## 개선

```json
{
  "architecture": {
    "label": "ai-led-verified",
    "confidence": 0.84,
    "reason": "AI가 Repository Pattern을 최초 제안했고 사용자는 최종 구조를 선택하고 코드 흐름을 설명함",
    "evidence_refs": [
      "conversation:218",
      "decision:42",
      "teachback:7"
    ]
  }
}
```

영역:

```text
requirements
architecture
implementation
debugging
testing
```

---

# 15. Conversation Sync 개선

현재 baseline 이후의 전체 JSONL을 매번 다시 읽지 않는다.

## Adapter 구조

```python
class SessionAdapter:
    def sync(self, source_path, after_cursor):
        ...
```

```text
providers/
├── base.py
├── codex.py
└── future/
```

sessions에 추가:

```text
provider
provider_schema_version
parser_version
cursor
```

Codex는 현재 `latest_line`을 cursor로 활용.

```text
sync #1
100 → 500

sync #2
500 → 800

sync #3
800 → 950
```

---

# 16. Concept 시스템

## 핵심 목표

단순히 "FastAPI를 사용했다"가 아니라:

```text
실제 코드
↓
개발 기술
↓
개발 개념
↓
CS 원리
```

로 연결한다.

예:

```text
FastAPI async endpoint
        ↓
Python async/await
        ↓
Event Loop
        ↓
Concurrency
        ↓
I/O Bound vs CPU Bound
```

---

# 17. concepts 테이블

```sql
CREATE TABLE concepts (
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
```

concept_type:

```text
cs
development
technology
pattern
tool
```

예:

```text
cs.concurrency.event-loop
dev.python.async-await
tech.fastapi.async-endpoint
pattern.repository
```

---

# 18. Concept occurrence

```sql
CREATE TABLE concept_occurrences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    feature_id TEXT,
    evidence_ref TEXT,
    role TEXT,
    created_at TEXT NOT NULL
);
```

role:

```text
used
discussed
debugged
decided
misunderstood
explained
tested
```

---

# 19. Concept 학습 상태

단순 점수 대신 상태 기반으로 간다.

```text
discovered
↓
explained
↓
applied
↓
recalled
↓
mastered
```

초기에는 자동 `mastered` 판정을 하지 않는다.

예:

```text
discovered
= 코드/대화에서 처음 등장

explained
= 사용자가 자기 말로 설명

applied
= 다른 feature에서 실제 사용

recalled
= 일정 시간이 지난 뒤 AI 도움 없이 설명/적용

mastered
= 여러 context에서 반복적으로 성공
```

---

# 20. Gemini 호출 정책

Gemini는 이벤트마다 호출하지 않는다.

## 실시간 호출

정말 중요한 decision candidate만.

```text
candidate
→ Python rule
→ threshold 이상
→ Gemini decision judge
```

## 비실시간 호출

다음은 worker에서 batch 처리.

```text
feature review
daily learning review
CS concept extraction
development concept extraction
weakness analysis
concept relationship
```

---

# 21. Evidence Packet

Gemini에게 DB 전체나 원본 대화 전체를 주지 않는다.

Python이 먼저 압축된 Packet을 만든다.

예:

```json
{
  "date": "2026-09-29",
  "project": {
    "id": "P-a83f9c12",
    "name": "AI-learning-mcp"
  },
  "features": [
    {
      "id": "F-20260929-001",
      "title": "Background learning worker",

      "goal": "개발을 막지 않고 학습 기록을 비동기로 처리한다",

      "git": {
        "baseline_commit": "abc123",
        "end_commit": "def456",
        "commits": 3,
        "changed_files": [
          "worker.py",
          "db.py",
          "service.py"
        ]
      },

      "decisions": [
        {
          "id": 12,
          "question": "Redis와 SQLite 중 어떤 queue를 사용할 것인가?",
          "user_reasoning": "개인용 local app이라 Redis는 과하다",
          "chosen": "SQLite"
        }
      ],

      "debugging": [
        {
          "symptom": "session sync가 중복 실행",
          "hypotheses": [
            "baseline부터 다시 읽고 있음"
          ],
          "result": "latest_line으로 변경 후 해결"
        }
      ],

      "tests": [
        {
          "name": "worker job integration",
          "result": "passed"
        }
      ],

      "conversation_highlights": [
        "..."
      ]
    }
  ]
}
```

---

# 22. Gemini Daily Review Output Schema

Gemini는 Markdown을 만들지 않는다.

JSON만 반환한다.

예:

```json
{
  "summary": "오늘은 Learning MCP의 비동기 기록 구조를 설계하고 SQLite 기반 job queue를 구현했다.",

  "decisions": [
    {
      "title": "SQLite Queue 선택",
      "summary": "Redis 대신 SQLite를 선택했다.",
      "user_reasoning": "개인용 local-first 프로젝트이므로 별도 인프라를 추가할 필요가 없다고 판단했다.",
      "related_concepts": [
        "Message Queue",
        "SQLite",
        "YAGNI"
      ]
    }
  ],

  "development_concepts": [
    {
      "name": "Background Worker",
      "canonical_id": "dev.background-worker",
      "why_it_appeared": "MCP 기록 작업이 개발 흐름을 막지 않게 하기 위해 사용",
      "explanation": "...",
      "related_cs_concepts": [
        "Producer Consumer",
        "Concurrency"
      ],
      "evidence_refs": [
        "decision:12",
        "git:feature-diff"
      ]
    }
  ],

  "cs_concepts": [
    {
      "name": "Producer-Consumer Pattern",
      "canonical_id": "cs.concurrency.producer-consumer",
      "explanation": "...",
      "connection_to_today": "...",
      "related_concepts": [
        "Queue",
        "Concurrency"
      ]
    }
  ],

  "weaknesses": [
    {
      "concept": "Event Loop",
      "reason": "async와 background worker의 차이를 혼동한 흔적이 있음",
      "confidence": 0.71,
      "evidence_refs": [
        "conversation:..."
      ]
    }
  ],

  "review_candidates": [
    "Event Loop",
    "SQLite WAL"
  ]
}
```

Python이 반드시 schema validation을 수행한다.

---

# 23. Gemini가 파일을 직접 작성하지 않는 이유

직접 Obsidian을 쓰게 하면:

- 잘못된 파일명
- 동일 concept 중복 생성
- 기존 note overwrite
- frontmatter 형식 변경
- link 불일치
- hallucinated path

문제가 발생할 수 있다.

따라서:

```text
Gemini JSON
↓
Pydantic/JSON Schema validation
↓
Concept resolver
↓
Obsidian writer
```

순서를 사용한다.

---

# 24. Obsidian 구조

권장:

```text
dev/
├── daily/
│   └── 2026/
│       └── 2026-09-29.md
│
├── concepts/
│   ├── cs/
│   │   ├── concurrency/
│   │   │   ├── event-loop.md
│   │   │   └── producer-consumer.md
│   │   ├── database/
│   │   │   ├── transaction.md
│   │   │   └── index.md
│   │   └── network/
│   │
│   └── development/
│       ├── python/
│       │   └── async-await.md
│       ├── fastapi/
│       └── git/
│
├── projects/
│   └── ai-learning-mcp/
│       ├── index.md
│       └── features/
│
├── debugging/
│
└── learning/
    ├── weaknesses.md
    └── review-queue.md
```

---

# 25. Daily Note

예:

```markdown
---
type: daily-development-learning
date: 2026-09-29
projects:
  - ai-learning-mcp
---

# 2026-09-29 개발 학습

## 오늘 개발한 것

- Learning MCP background worker 설계
- SQLite job queue 추가
- Git immutable evidence 구조 설계

## 내가 직접 내린 결정

### Redis 대신 SQLite Queue

개인용 local-first 시스템이라 별도 Redis 인프라는 현재 단계에서 과하다고 판단했다.

관련:
- [[SQLite]]
- [[Message Queue]]
- [[YAGNI]]

## 디버깅

### Codex session 중복 parsing

원인:
`baseline_line`부터 반복해서 읽고 있었다.

개선:
`latest_line` 기준 incremental parsing.

관련:
- [[Incremental Processing]]

## 오늘 등장한 개발 개념

- [[Background Worker]]
- [[Job Queue]]
- [[Incremental Processing]]

## 연결된 CS 개념

- [[Producer Consumer Pattern]]
- [[Concurrency]]
- [[Event Loop]]

## 다시 볼 내용

- Event Loop와 Worker Process의 차이
- SQLite WAL 동작 방식
```

---

# 26. Concept Note

```markdown
---
type: cs-concept
concept_id: cs.concurrency.event-loop
status: explained
first_seen: 2026-09-29
last_seen: 2026-09-29
---

# Event Loop

## 왜 알게 되었나

Learning MCP의 background processing과 async 처리의 차이를 이해하는 과정에서 등장했다.

## 핵심 개념

...

## 오늘 프로젝트와 연결

...

## 관련 기술

- [[Python async-await]]
- [[FastAPI]]
- [[Background Worker]]

## 실제 사용 기록

- [[2026-09-29 개발 학습]]
- [[F-20260929-001]]

## 내가 설명한 내용

...

## 아직 헷갈리는 부분

...
```

---

# 27. 하루 종료 처리

사용자가 매번 `$finish`를 입력하지 않아도 된다.

초기 구현 권장:

```text
A. 명시적 finish_feature
+
B. 하루 inactivity 기반 daily digest
```

추후:

```text
Codex session 종료 이벤트
```

를 안정적으로 감지할 수 있으면 추가한다.

daily digest 조건 예:

```text
해당 날짜 event 존재
AND
daily digest 미생성
AND
최근 N분간 새 event 없음
```

또는 정해진 시간에 worker가 생성.

---

# 28. 즉시 질문과 비동기 작업 분리

## 동기적으로 해야 하는 것

사용자의 사고가 필요한 것:

```text
"왜 이 기술을 선택했나요?"
"이 오류 원인은 뭐라고 생각하세요?"
"이 책임은 어디에 두는 게 맞다고 생각하세요?"
```

사용자의 답변 자체가 학습 evidence이므로 즉시 질문한다.

## 비동기로 해야 하는 것

```text
Git snapshot
diff 분석
commit range
session parsing
event 정리
개념 추출
CS 연결
daily review
Obsidian 저장
통계
```

개발을 막을 이유가 없다.

---

# 29. MCP Tool 개편안

현재 10개 tool을 유지해도 되지만 역할을 단순화한다.

## 유지

```text
get_project_context
start_feature
record_decision
record_debug_attempt
get_feature_manifest
get_evidence
finish_feature
get_learning_history
```

## 변경

### sync_codex_session

동기 parser 실행 대신:

```text
request_session_sync()
```

또는 내부적으로 job enqueue 후 즉시 return.

응답:

```json
{
  "queued": true,
  "job_id": 182
}
```

### save_feature_review

외부 Agent가 직접 자유형 review를 저장하는 방식보다:

```text
request_feature_review()
```

로 job 생성.

Gemini 결과는 Worker가 validation 후 저장.

---

# 30. 신규 Tool

## capture_event

```python
capture_event(
    project_root,
    feature_id,
    event_type,
    payload
)
```

가벼운 event 기록.

## queue_feature_analysis

```python
queue_feature_analysis(feature_id)
```

## get_pending_questions

중요 판단 candidate 중 아직 사용자 답변이 없는 것 조회.

## record_user_answer

사용자의 결정/teach-back을 evidence와 연결.

## get_learning_context

현재 feature에서 과거 반복 약점/관련 concept만 작은 context로 반환.

Codex에게 전체 Obsidian을 읽히지 않는다.

---

# 31. Daily Gemini 호출

권장:

```text
1일 1회 / 프로젝트 또는 전체 개발 기록 batch
```

feature 종료 시 별도의 feature review가 필요하면 추가 가능.

Gemini에 보낼 데이터는 Python이 압축한다.

절대로:

```text
전체 repo
전체 JSONL
전체 Obsidian
```

을 매번 주지 않는다.

---

# 32. Privacy / Secret Redaction

Gemini로 데이터를 보내기 전에 Python redaction layer를 둔다.

검출 후보:

```text
API keys
Bearer tokens
password
.env
private key
database URL
AWS credential
GitHub token
personal access token
cookie
session secret
```

## 추가 설정

```text
.learningignore
```

예:

```gitignore
.env
.env.*
secrets/
credentials/
*.pem
*.key
private/
```

Gemini에는 원본 secret 대신:

```text
[REDACTED_SECRET]
```

으로 전달.

---

# 33. Review 통계 개선

반복 약점 계산 시:

```text
X 모든 review row
```

가 아니라:

```text
feature당 최신 verified review
```

만 사용.

또한 같은 weakness가 같은 feature에서 여러 번 저장되어도 1회로 계산한다.

---

# 34. 테스트 전략

반드시 추가.

## Git Evidence

- feature 중간 commit 후 working tree가 clean인 경우
- 여러 commit 포함
- staged 변경
- unstaged 변경
- untracked file
- rename
- deleted file
- binary file
- branch 변경
- project path 이동

## Lifecycle

- completed feature에 decision 추가 차단
- review 없이 완료 정책
- double finish
- verified evidence validation

## Job Queue

- pending → running → completed
- worker crash
- retry
- max retries
- duplicate job
- concurrent worker

## Gemini

- valid JSON
- malformed JSON
- missing field
- timeout
- process failure
- hallucinated concept id
- duplicated concept

## Obsidian

- duplicate concept merge
- Korean filename
- frontmatter escaping
- path traversal
- existing note preservation

## Session

- incremental cursor
- malformed JSONL
- schema version difference
- duplicate event

---

# 35. 구현 순서

## Phase 1 — Evidence 신뢰성 + 비동기 기반

가장 먼저 한다.

### 1-1. Project identity

- `projects`
- `project_roots`
- stable project id

### 1-2. Immutable Git Evidence

- baseline snapshot
- final snapshot
- commit range
- untracked
- `git:feature-diff`

### 1-3. Event / Job Queue

- `events`
- `jobs`
- enqueue
- worker loop

### 1-4. 기존 무거운 MCP 처리 enqueue 방식으로 변경

- session sync
- final snapshot
- review request

완료 조건:

```text
MCP 기록 때문에 개발이 기다리지 않는다.
과거 feature Git 증거가 이후 작업으로 변하지 않는다.
```

---

# 36. Phase 2 — Gemini 분리

### 2-1. Gemini client

```text
gemini/client.py
```

입력:

```text
JSON evidence packet
```

출력:

```text
JSON only
```

### 2-2. schema validation

Pydantic 또는 jsonschema 사용.

### 2-3. decision judge

중요한 판단 후보에서만 Gemini 호출.

### 2-4. daily learning analyzer

하루 핵심 evidence를 Gemini가 분석.

완료 조건:

```text
Codex가 feature review / daily review를 하지 않아도 됨.
Gemini가 structured JSON으로 학습 결과를 반환.
```

---

# 37. Phase 3 — Concept Graph + Obsidian

### 3-1. concepts

### 3-2. concept_occurrences

### 3-3. CS ↔ development 연결

### 3-4. Python Obsidian writer

### 3-5. Daily Note 자동 생성

완료 조건:

```text
하루 개발 후 자동으로:
- 오늘 개발한 것
- 사용자 결정
- 디버깅
- 개발 개념
- CS 개념
- 다시 볼 내용

이 Obsidian에 생성됨.
```

---

# 38. Phase 4 — 학습 추적

### 4-1. concept state

```text
discovered
explained
applied
recalled
mastered
```

### 4-2. teach-back

중요 개념은 사용자가 자기 말로 설명.

### 4-3. repeated weakness

이전 약점이 실제 개발에서 다시 등장하면 Codex에 작은 learning context 전달.

### 4-4. delayed recall

며칠 후 동일 개념이 등장하면 바로 답을 주기 전에 질문.

완료 조건:

```text
Learning MCP가 노트 작성기를 넘어
개인 개발 학습 시스템으로 동작.
```

---

# 39. 지금 구현하지 않을 것

초기에는 넣지 않는다.

- LangGraph
- Redis
- RabbitMQ
- Kafka
- Celery
- Vector DB
- 별도 로컬 LLM
- multi-agent swarm
- line-by-line AI authorship detection
- 복잡한 점수 기반 실력 평가

필요성이 실제로 생겼을 때 추가한다.

---

# 40. 추천 디렉터리 최종안

```text
AI-learning-mcp/
├── src/
│   └── learning_mcp/
│       ├── server.py
│       ├── service.py
│       ├── cli.py
│       ├── config.py
│       ├── db.py
│       │
│       ├── projects.py
│       ├── events.py
│       ├── jobs.py
│       ├── worker.py
│       │
│       ├── git/
│       │   ├── repository.py
│       │   └── snapshot.py
│       │
│       ├── evidence/
│       │   ├── packet.py
│       │   └── redaction.py
│       │
│       ├── providers/
│       │   ├── base.py
│       │   └── codex.py
│       │
│       ├── gemini/
│       │   ├── client.py
│       │   ├── prompts.py
│       │   └── schemas.py
│       │
│       ├── concepts/
│       │   ├── service.py
│       │   └── resolver.py
│       │
│       └── obsidian/
│           ├── writer.py
│           ├── daily.py
│           ├── concept.py
│           └── feature.py
│
├── tests/
│   ├── test_git_snapshot.py
│   ├── test_jobs.py
│   ├── test_projects.py
│   ├── test_session_adapter.py
│   ├── test_gemini_schema.py
│   ├── test_concepts.py
│   └── test_obsidian_writer.py
│
└── docs/
    └── IMPROVEMENT_PLAN_V2.md
```

---

# 41. 최종 사용자 경험

이 프로젝트가 완성되면 사용자는 이렇게 느껴야 한다.

```text
나는 그냥 평소처럼 개발한다.

Codex가 구현한다.

중요한 선택이 나오면
가끔 내 생각을 묻는다.

나는 이유를 설명한다.

개발은 계속된다.

기록 저장 때문에 기다리지 않는다.

하루가 끝난다.

Obsidian을 열면:

- 오늘 무엇을 만들었는지
- 왜 그렇게 설계했는지
- 어떤 오류를 해결했는지
- 어떤 개발 기술을 썼는지
- 그 기술과 연결되는 CS 원리가 무엇인지
- 내가 직접 이해한 것은 무엇인지
- 아직 부족한 것은 무엇인지

자동으로 정리되어 있다.

며칠 뒤 비슷한 개념이 다시 나오면
AI가 내가 전에 배웠던 것을 기억하고
바로 정답을 주기보다 먼저 생각하게 만든다.
```

---

# 42. 최종 원칙

```text
Codex = Developer

Learning MCP = Evidence / Learning Data Platform

Python Worker = Collector + Processor + Writer

Gemini = Reviewer + Teacher

Obsidian = Long-term Knowledge Base

User = Final Decision Maker
```

가장 중요한 설계 원칙:

> **코드로 확정할 수 있는 것은 코드로 처리하고, 의미 판단이 필요한 것만 Gemini에게 맡긴다.**

그리고:

> **Learning MCP 때문에 개발 흐름이 멈추면 안 된다.**

그리고:

> **학습 기록은 반드시 실제 Git·대화·테스트·사용자 판단 evidence에 연결되어야 한다.**

이 세 가지를 v2의 핵심 invariant로 둔다.
