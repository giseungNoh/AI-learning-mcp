# Learning MCP 설치 및 사용법

## 1. 요구 사항

- macOS 또는 Linux
- Git
- `uv`
- Python 3.10 이상 (`uv`가 프로젝트 환경을 관리)
- MCP를 지원하는 Codex, Claude Code 등의 host

프로젝트 경로 예시:

```text
/Users/juks86/Documents/Codex/2026-08-24/learning-mcp
```

## 2. 설치

```bash
cd /Users/juks86/Documents/Codex/2026-08-24/learning-mcp
uv sync
uv run learning-mcp-cli init
```

기본 DB는 다음 위치에 생성됩니다.

```text
learning-mcp/data/learning.db
```

현재 구현은 MCP Python SDK v1.27+와 v2 import 경로를 모두 지원합니다. 새 환경에서는 `uv sync`가 호환 버전을 설치합니다.

## 3. 환경 변수

| 변수 | 의미 | 기본값 |
|---|---|---|
| `LEARNING_MCP_HOME` | 서버 데이터 기준 폴더 | 저장소 루트 |
| `LEARNING_MCP_DB` | SQLite 파일 | `<home>/data/learning.db` |
| `LEARNING_MCP_PROJECT_ROOT` | CLI `current` 명령의 레거시 기본값(MCP tool은 사용 안 함) | MCP 실행 cwd |
| `LEARNING_MCP_OBSIDIAN_VAULT` | Obsidian Vault 절대경로 | 미설정 시 export 안 함 |
| `LEARNING_MCP_CODEX_SESSION_ROOT` | 읽을 수 있는 Codex rollout 루트 | `~/.codex/sessions` |
| `LEARNING_MCP_MAX_MANIFEST_CHARS` | manifest 상한 설정 | 8000 |
| `LEARNING_MCP_MAX_EVIDENCE_CHARS` | evidence 본문 상한 | 12000 |

Vault 예시:

```text
/Users/juks86/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Vault
```

## 4. Codex에 MCP 등록

현재 설치된 Codex CLI는 로컬 stdio 서버를 다음 형식으로 등록할 수 있습니다.

```bash
codex mcp add learning-mcp \
  --env LEARNING_MCP_HOME=/Users/juks86/Documents/Codex/2026-08-24/learning-mcp \
  --env LEARNING_MCP_DB=/Users/juks86/Documents/Codex/2026-08-24/learning-mcp/data/learning.db \
  --env 'LEARNING_MCP_OBSIDIAN_VAULT=/Users/juks86/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Vault' \
  -- /Users/juks86/.local/bin/uv run \
  --directory /Users/juks86/Documents/Codex/2026-08-24/learning-mcp \
  learning-mcp
```

등록 확인:

```bash
codex mcp list
codex mcp get learning-mcp
```

Codex를 다시 시작하거나 새 thread를 연 다음 Learning MCP tools가 보이는지 확인합니다.

직접 `config.toml`에 넣는다면 같은 의미는 다음과 같습니다.

```toml
[mcp_servers.learning-mcp]
command = "/Users/juks86/.local/bin/uv"
args = [
  "run",
  "--directory",
  "/Users/juks86/Documents/Codex/2026-08-24/learning-mcp",
  "learning-mcp",
]

[mcp_servers.learning-mcp.env]
LEARNING_MCP_HOME = "/Users/juks86/Documents/Codex/2026-08-24/learning-mcp"
LEARNING_MCP_DB = "/Users/juks86/Documents/Codex/2026-08-24/learning-mcp/data/learning.db"
LEARNING_MCP_OBSIDIAN_VAULT = "/Users/juks86/Library/Mobile Documents/iCloud~md~obsidian/Documents/Obsidian Vault"
```

MCP 서버는 하나만 등록합니다. `learning-session` skill이 각 Codex 작업의 현재 Git 최상위 경로를 구해 `start_feature.project_root`로 전달합니다. 서버는 이 경로를 다시 Git 루트로 정규화한 뒤 feature에 영구 저장하므로 여러 프로젝트가 같은 DB를 안전하게 공유합니다. 경로가 없거나 Git 저장소가 아니면 기본 프로젝트로 대체하지 않고 요청을 거부합니다.

## 5. Skills 설치

저장소의 `skills/`에는 다음 5개가 있습니다.

- `learning-session`
- `feature-review`
- `debugging-coach`
- `architecture-critic`
- `promote-feature-to-book`

Codex 프로젝트에서 사용하려면 개발 대상 저장소 안에 복사합니다.

```bash
mkdir -p /path/to/project-being-developed/.codex/skills
cp -R /Users/juks86/Documents/Codex/2026-08-24/learning-mcp/skills/* \
  /path/to/project-being-developed/.codex/skills/
```

여러 프로젝트에서 서버 하나를 사용할 때는 `~/.codex/skills/`에 개인 전역 skill로 설치하는 방식을 권장합니다. `learning-session`이 호출 시점의 현재 Git 루트를 전달하므로 skill을 프로젝트마다 복제할 필요가 없습니다. 특정 프로젝트만 다른 학습 정책을 써야 할 때만 그 저장소의 `.codex/skills/`에 별도 버전을 둡니다.

Claude Code에서는 같은 skill 폴더를 대상 프로젝트의 `.claude/skills/`에 둘 수 있습니다. MCP 실행 명령과 환경 변수는 Claude Code의 로컬 stdio MCP 설정에 동일하게 전달합니다.

## 6. 실제 사용 흐름

### 피처 시작

사용자:

```text
$learning-session
Codex 세션의 토큰 사용량을 feature별로 집계하는 기능을 만들자.
이번에는 집계 규칙과 저장 구조는 내가 판단하고, 반복 코드는 AI가 작성해도 돼.
```

Skill은 먼저 현재 작업에서 `git rev-parse --show-toplevel`을 실행하고, 사용자 생각을 받은 뒤 절대경로를 포함해 `start_feature`를 호출합니다.

```text
start_feature(
  project_root="/absolute/path/to/current-project",
  ...
)
```

생성 예:

```text
F-20260825-001
```

병렬 Codex thread가 없다면 token 기준점을 바로 연결할 수 있습니다.

```text
sync_codex_session(
  feature_id="F-20260825-001",
  session_file="latest",
  phase="start"
)
```

병렬 thread가 있다면 `latest`를 사용하지 말고 정확한 rollout JSONL 경로를 전달합니다.

### 판단 기록

중요한 설계 선택을 한 뒤:

```text
record_decision(
  feature_id="F-20260825-001",
  question="토큰 snapshot을 그대로 합산할 것인가?",
  chosen_option="시작과 종료 누적값의 delta를 저장",
  reason="누적 snapshot을 합하면 중복 계산되기 때문",
  alternatives=["모든 snapshot 합산", "turn별 usage만 저장"],
  decided_by="human"
)
```

### 디버깅

```text
$debugging-coach 토큰 수가 예상보다 두 배로 집계돼
```

가설과 확인 결과는 `record_debug_attempt`에 저장됩니다.

### 빠른 커밋 리뷰

```text
$feature-review F-20260825-001 quick으로 staged 변경을 리뷰해줘
```

Agent는 다음 순서를 따라야 합니다.

```text
get_feature_manifest(quick)
→ 필요한 경우 get_evidence(["diff:staged", "decision:..."])
→ 리뷰
→ 사용자 teach-back과 기여도 확인
→ save_feature_review
```

### 피처 종료

```text
finish_feature(feature_id="F-20260825-001")
```

연결된 Codex session을 다시 읽어 token delta와 feature 시작 이후 대화를 가져온 뒤 feature를 완료 처리합니다.

## 7. Tool 목록

| Tool | 용도 |
|---|---|
| `start_feature` | 목표·성공 조건·사용자/AI 범위 선언 |
| `get_project_context` | 현재 경로를 Git 루트로 정규화하고 해당 프로젝트 활성 feature 조회 |
| `record_decision` | 기술 선택과 대안 기록 |
| `record_debug_attempt` | 증상·가설·검증·결과 기록 |
| `sync_codex_session` | 대화 인덱스와 token delta 동기화 |
| `get_feature_manifest` | 작은 리뷰 문맥과 evidence ref 조회 |
| `get_evidence` | 선택한 diff·결정·디버깅·대화만 조회 |
| `save_feature_review` | 기여도·흐름·대안·학습 주제 저장 |
| `finish_feature` | session 최종 동기화 후 완료 |
| `get_learning_history` | 최근 리뷰와 반복 약점 상위 항목 조회 |

Resource:

```text
learning://feature/{feature_id}/manifest
```

## 8. Obsidian 결과

설정한 Vault 아래에 자동 생성됩니다.

```text
dev/wiki/projects/<project>/features/<feature-id>/review-<feature-title>.md
```

예: `F-20260825-001`의 제목이 `상품 키워드 검색 API`이면 `review-상품-키워드-검색-api.md`로 저장됩니다. 본문 H1에는 `F-20260825-001 — 상품 키워드 검색 API`처럼 원래 ID와 제목이 표시됩니다.

재사용할 개념과 디버깅 사례는 검토 후 각각 다음으로 승격합니다.

```text
dev/wiki/concepts/
dev/wiki/debugging/
```

책으로 만들 때:

```text
$promote-feature-to-book F-20260825-001 리뷰를 챕터 후보로 검토해줘
```

검증된 feature만 기존 `chapter-writer → read-only chapter-reviewer` 흐름에 전달합니다.

## 9. CLI 보조 명령

MCP host 없이 상태를 확인할 수 있습니다.

```bash
uv run learning-mcp-cli current --project-root /path/to/project
uv run learning-mcp-cli manifest F-20260825-001 --detail quick
uv run learning-mcp-cli sync-codex F-20260825-001 --session-file latest --phase update
```

## 10. 테스트와 Inspector

```bash
uv run python -m unittest discover -s tests -v
uv run mcp dev src/learning_mcp/server.py:mcp
```

Inspector는 Node.js의 `npx`가 필요합니다.

## 11. 토큰을 적게 사용하는 규칙

- 평소에는 `quick` manifest만 사용합니다.
- full diff와 full transcript를 요청하지 않습니다.
- `get_evidence` ref는 필요한 것만 최대 2~4개 선택합니다.
- `standard` 리뷰는 feature 완료 시에만 사용합니다.
- `deep` 분석은 architecture critic이 필요한 경우에만 수행합니다.
- Obsidian 저장 결과는 경로와 hash만 받습니다.
- token 수를 실력이나 AI 의존도 점수로 해석하지 않습니다.
