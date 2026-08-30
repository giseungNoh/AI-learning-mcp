# Learning MCP 프로젝트 문맥

## 출처

- ChatGPT 프로젝트: `Learning mcp`
- 프로젝트 ID: `g-p-6a8bd290ac8081919ae36f7bd93654ca`
- 확인한 대화: `Flask와 FastAPI 비교`
- 대화 ID: `6a7bccaf-c454-83e9-9a99-f3a4cf6a92f4`
- 원본: https://chatgpt.com/g/g-p-6a8bd290ac8081919ae36f7bd93654ca

## 사용자가 이해한 기초 개념

- BeautifulSoup/Playwright는 외부 웹페이지를 읽고 필요한 데이터를 추출한다.
- Flask/FastAPI는 Python 내부 기능이나 데이터를 HTTP로 외부에 제공한다.
- JSON은 프로그램끼리 주고받는 데이터 형식이다.
- API는 한 프로그램이 다른 프로그램의 기능이나 데이터를 정해진 방식으로 요청하고 응답받는 통로다.
- 예시 흐름: iPhone 앱 → Flask endpoint → Python 함수 → 필요하면 Playwright로 웹 조회 → Python 결과 → Flask JSON 응답 → iPhone 앱.

## 프로젝트 목표

AI를 활용해 개발하는 동안 작업 로그를 축적하고, feature가 끝날 때마다 AI가 다음을 리뷰하는 개인 개발 학습 도구를 만든다.

- 무엇을 만들었는지
- 어떤 문제와 오류를 만났는지
- 사용자가 직접 판단하고 해결한 부분
- AI 의존도가 높았던 부분
- 코드나 개념상 부족했던 부분
- 다음에 공부할 주제
- 반복해서 나타나는 약점

프로젝트의 성격은 단순 코드리뷰 도구보다 `AI-assisted developer learning tracker`에 가깝다.

## 합의한 아키텍처 방향

```text
Claude Code / Cursor / Codex 등 상위 Agent
                    ↕
              Learning MCP
                    ↕
       개발 로그 / Git / SQLite / 프로젝트
```

- MCP는 데이터 수집과 조회를 담당한다.
- 실제 리뷰와 추론은 Codex 같은 상위 Agent가 담당한다.
- MCP 내부에서 별도 LLM을 호출해 `review_feature` 판단까지 수행하지 않는다.
- GitHub MCP Server는 저장소, commit, diff, PR 등의 GitHub 문맥을 가져오는 기반으로 활용할 수 있다.
- 사용자의 질문, 막힌 지점, 오류, AI 의존도, 반복 약점과 학습 이력은 커스텀 Learning MCP가 맡는다.
- 여러 AI 도구가 같은 개발 학습 기록을 공유할 수 있는 구조를 지향한다.

## 초기 데이터 후보

- Git commit과 diff
- AI 대화 및 질문 로그
- 에러 로그
- 수정 횟수와 시행착오
- feature별 작업 기록
- 과거 학습 추천 및 반복 약점

저장소 후보는 SQLite이며, 초기 단계에서는 Markdown/JSON도 가능하다.

## 제안된 도구 전체 후보

- `log_session()` 또는 `save_dev_log()`
- `get_feature_history()` 또는 `get_feature_logs()`
- `get_git_diff()` 또는 `get_feature_diff()`
- `review_feature()`
- `recommend_study_topics()`
- `get_weakness_history()`
- `get_learning_history()`

## MVP 범위

먼저 다음 4개 tool로 시작한다.

1. `save_dev_log()`
2. `get_feature_logs()`
3. `get_feature_diff()`
4. `get_learning_history()`

feature 리뷰 시 상위 Agent는 다음 원칙을 따른다.

1. diff를 확인한다.
2. 개발 로그를 확인한다.
3. 과거 learning history와 비교한다.
4. 사용자가 직접 해결한 부분과 AI 의존 부분을 구분한다.
5. 학습 주제를 최대 3개 추천한다.
6. 전에 추천했는데 다시 발생한 문제는 반복 약점으로 표시한다.

## 다음 작업

MCP 폴더 구조, SQLite 스키마, MVP tool 4개, feature 로그 포맷을 실제 구현 가능한 수준으로 설계하고 구현한다.

## 2026-08-25 추가 합의

### feature 중심 학습 기록

- 개발 기록과 리뷰의 기본 단위는 `feature`다.
- feature 시작 시 목표, 성공 조건, 사용자가 직접 판단할 범위(`user_owned_scope`), AI에 맡겨도 되는 범위(`ai_allowed_scope`)를 선언한다.
- 요구사항, 아키텍처, 구현, 디버깅, 테스트별 기여도를 `human-led`, `shared`, `ai-led-verified`, `ai-led-unverified`로 구분한다.
- 자동 판정에는 근거와 신뢰도를 붙이고, 최종적으로 사용자가 판정을 수정·확정할 수 있게 한다.

### 토큰 사용량

- Codex/Claude 등 provider별 session을 feature에 연결한다.
- input, cached input, output, reasoning, total token을 가능한 범위에서 수집하고 `exact`, `estimated`, `unavailable`을 구분한다.
- 누적 토큰 스냅샷은 feature 시작/종료 값의 차이로 계산해 중복 합산을 피한다.
- 토큰 수를 AI 의존도 점수로 직접 사용하지 않는다. 피처별 사용 규모와 반복 문제에서의 변화 관찰용으로 사용한다.

### Obsidian과 책 집필 연결

- 프로젝트별 feature 리뷰는 `dev/wiki/projects/<project>/features/`에 둔다.
- 재사용 가능한 개념과 디버깅 사례만 각각 `dev/wiki/concepts/`, `dev/wiki/debugging/`으로 승격한다.
- 검증된 feature 리뷰만 `promote-feature-to-book` 단계를 거쳐 `dev/raw/<project>-book/`의 책 집필 입력으로 사용한다.
- 책 집필 흐름은 `learning-evidence-curator -> chapter-writer -> read-only chapter-reviewer`로 확장한다.
- 모든 경험·설계·코드 인용에는 feature/debug/decision ID, commit SHA, 파일 경로 같은 실제 증거를 연결한다.

### 토큰 절약 아키텍처

- MVP에는 LangGraph를 넣지 않는다.
- 수집, 정규화, diff 축약, token 집계, Obsidian 저장은 LLM 없이 결정적 코드로 처리한다.
- MCP는 전체 대화·전체 diff를 기본 반환하지 않고 작은 manifest와 evidence reference를 먼저 반환한다.
- 상위 Agent가 필요한 evidence만 두 번째 호출로 가져오는 2단계 조회를 사용한다.
- feature 리뷰는 여러 전문 Agent 호출보다 구조화된 증거 패킷을 사용하는 1회의 주 리뷰 호출을 기본으로 한다.
- LangGraph는 향후 중단·재개, 사용자 승인 분기, 재검토 루프가 복잡해질 때 선택적으로 도입한다.

## MVP 구현 상태 (2026-08-25)

- Python 로컬 stdio MCP 서버와 SQLite 저장소를 구현했다.
- tool 10개: 프로젝트 문맥 확인, feature 시작, 결정/디버깅 기록, Codex session 동기화, compact manifest, 선택 evidence, 리뷰 저장, feature 종료, 학습 이력.
- resource 1개: feature별 quick manifest.
- Codex rollout JSONL의 누적 token snapshot을 feature 시작/종료 delta로 계산한다.
- feature 시작 이후 사용자/AI 대화를 SQLite evidence로 자동 인덱싱하며 manifest에는 요약과 ref만 노출한다.
- Git working/staged diff와 commit을 선택 evidence로 조회한다.
- Obsidian `dev/wiki/projects/<project>/features/<feature>/review-<feature-title>.md` exporter를 구현했다. 한글·영문·숫자를 유지한 설명형 파일명을 사용한다.
- learning-session, feature-review, debugging-coach, architecture-critic, promote-feature-to-book 스킬을 `skills/`에 구현했다.
- 설치·사용법은 `docs/USAGE_KO.md`, 구조 설명은 `docs/ARCHITECTURE.md`에 정리했다.

## 다중 프로젝트 개선 (2026-08-25)

- Learning MCP 서버와 SQLite DB는 모든 개발 프로젝트가 하나를 공유한다.
- `learning-session`이 host의 현재 작업에서 `git rev-parse --show-toplevel`을 실행하고 절대경로를 `start_feature.project_root`에 필수로 전달한다.
- 서버는 전달받은 경로를 실제 Git 최상위 경로로 정규화·검증하고 feature에 저장한다.
- 잘못된 프로젝트 증거가 섞이지 않도록 MCP tool은 `LEARNING_MCP_PROJECT_ROOT` 기본값으로 feature를 시작하지 않는다.
- `get_project_context(project_root)`로 현재 프로젝트의 정규화된 경로와 활성 feature를 조회한다.
- Codex 전역 MCP 등록에서는 `LEARNING_MCP_PROJECT_ROOT`를 제거했다.
- 다섯 Learning skill을 `~/.codex/skills/`에 전역 설치했다.

## Obsidian Vault 설정 완료 (2026-08-25)

- Vault의 `dev/wiki/learning-dashboard.md`에 Dataview 기반 Learning MCP 대시보드를 추가했다.
- `dev/wiki/projects/_feature-review-guide.md`에 자동 생성 리뷰와 수동 승격 노트의 경계를 정리했다.
- `templates/learning-mcp/`에 feature review 수동 복구, concept, debugging, book evidence 템플릿 4종을 추가했다.
- `.obsidian/templates.json`의 core Templates 폴더를 `templates`로 설정했다.
- `skill and agent/learning-evidence-curator.md`를 추가했다.
- 기존 `write-book`, `book-chapter-writer`, `book-chapter-reviewer`가 verified evidence bundle을 선택적으로 사용하고 실제 경험 주장과 historical/current/proposed code를 검증하도록 확장했다.
- `dev/CLAUDE.md`, `dev/index.md`, `dev/log.md`에 Learning MCP 운영 규칙과 진입점을 연결했다.
