# Obsidian × Learning MCP 운영 가이드

## 목적

이 연결의 목적은 노트를 많이 만드는 것이 아니다. 개발 중 생긴 경험을 다음 네 단계로 좁혀서, 다시 설명하고 다른 기능에 재사용할 수 있게 만드는 것이다.

```text
Feature 증거 → 검증된 리뷰 → 재사용할 개념/디버깅 사례 → 지연 회상과 재적용
```

## 권장 폴더 경계

```text
Obsidian Vault/
├── HOME.md                         # 사람이 여는 단일 시작점
├── daily-notes/                    # 생활·실행 계획
│   └── eisenhower/                 # 계획에서 파생된 우선순위 기록
├── weekly-notes/                   # 주간 계획과 회고
├── monthly-notes/                  # 월간 계획과 회고
├── dev/
│   ├── raw/                        # 원본 자료, LLM 수정 금지
│   └── wiki/                       # LLM이 관리하는 개발 지식
│       ├── learning-dashboard.md   # Learning MCP 진입점
│       ├── learning/daily/         # MCP가 만든 일일 개발 회고
│       ├── projects/<project>/
│       │   └── features/<id>/      # MCP가 만든 feature 리뷰
│       ├── concepts/               # 여러 기능에 재사용할 지식
│       └── debugging/              # 증상-가설-실험-결과가 있는 사례
└── books/                          # 독서 LLM Wiki
```

자동 생성 리뷰는 직접 고치지 않는다. 보충 설명은 같은 파일의 생성 마커 밖에 쓰거나, 가치가 반복 확인되면 `concepts/` 또는 `debugging/`으로 승격한다.

## 가장 작은 학습 루프

### Feature 시작 전 — 3분

다음 세 가지만 정한다.

1. 사용자가 실제로 확인할 수 있는 성공 조건 1~3개
2. 이번에 직접 판단할 영역 하나(예: 아키텍처 또는 디버깅)
3. AI에 맡겨도 되는 반복 작업

### 개발 중

- 큰 선택만 `record_decision`으로 남긴다. 사소한 편집은 기록하지 않는다.
- 오류가 나면 바로 답을 받기 전에 증상과 첫 가설을 한 번 말한다.
- 개념을 읽는 것보다 실제 코드에서 어디에 쓰였는지 연결한다.
- 자동으로 붙은 공식 문서는 개념의 기준점으로만 쓰고, 읽은 뒤 자기 말 설명이나 실제 적용을 남긴다.

### Feature 종료 — 10분

1. 테스트 결과를 확인한다.
2. 코드 흐름을 자기 말로 3~5문장 설명한다.
3. 리뷰의 사람/AI 기여도 판정을 확인한다.
4. 다음 학습 주제는 최대 하나만 이번 주 큐에 넣는다.

### 주간 회고 — 20분

새 노트를 더 만들기 전에 다음 순서로 처리한다.

1. `needs-confirmation` 리뷰를 먼저 확인한다.
2. 이번 주에 두 번 이상 등장한 개념 하나만 evergreen 개념으로 승격한다.
3. 실제 가설과 검증이 있었던 오류 하나만 debugging 사례로 승격한다.
4. 지난 개념 하나를 노트 없이 설명하고 실제 코드 위치를 찾는다.
5. 설명하지 못한 항목은 삭제하지 말고 다음 회상 날짜만 정한다.

## 학습 부채를 막는 제한

- 진행 중 Feature: 프로젝트당 1개
- 검증 대기 리뷰: 최대 3개. 넘으면 새 리뷰보다 확인을 우선한다.
- 이번 주 학습 주제: 최대 1개
- 개념 승격: 같은 개념이 두 Feature에서 쓰였거나, 한 달 안에 다시 쓸 예정일 때만
- 계획 체크리스트: 하루 핵심 목표 3개 이하
- 읽기만 한 자료는 지식으로 간주하지 않는다. 설명 또는 실제 적용 증거가 있어야 한다.
- 공식 문서 링크가 없다는 이유만으로 비공식 URL을 임의로 추가하지 않는다. 필요하면 다음 회고에서 직접 검증한다.

## 권장 명령 예시

```text
$learning-session 이 기능을 기록하면서 개발하자.
성공 조건은 내가 확인하고, 아키텍처 판단은 내가 하며 반복 구현은 AI가 도와줘.
```

```text
$debugging-coach 이 오류를 바로 고치기 전에 내가 가설을 세우도록 질문해줘.
```

```text
$feature-review 현재 feature를 리뷰해줘. 내가 코드 흐름을 설명한 뒤 verified로 저장해줘.
```

```text
이번 주 Learning MCP 리뷰에서 반복된 개념 하나만 골라 인출 질문을 내줘.
```

## 연결 확인

Codex MCP 설정에 아래 값이 있어야 한다.

```text
LEARNING_MCP_OBSIDIAN_VAULT=/Users/juks86/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Vault
```

서버나 경로를 바꾼 뒤에는 새 Codex 작업에서 확인한다. 테스트용 Feature를 하나 완료한 뒤 리뷰 파일이 `dev/wiki/projects/<project>/features/<feature-id>/`에 생기면 연결이 완료된 것이다.
