---
title: 홈
created: 2026-09-30
updated: 2026-09-30
tags: [dashboard, home]
---

# 홈

이 페이지 하나만 시작점으로 사용한다. 계획은 `daily-notes`, 개발 경험은 Learning MCP, 오래 쓸 지식은 LLM Wiki에서 찾는다.

## 오늘

- [[dev/wiki/learning-dashboard|Learning MCP 학습 대시보드]]

```dataview
TABLE WITHOUT ID file.link AS "최근 일일 노트"
FROM "daily-notes"
WHERE file.extension = "md"
SORT file.name DESC
LIMIT 1
```

```dataview
TABLE WITHOUT ID file.link AS "최근 주간 노트"
FROM "weekly-notes"
WHERE file.extension = "md"
SORT file.name DESC
LIMIT 1
```

## 기록의 목적지

| 생긴 것 | 저장 위치 | 처리 원칙 |
|---|---|---|
| 오늘 할 일·회고 | `daily-notes/` | 핵심 목표 3개 이하 |
| 개발 중 원본 자료 | `dev/raw/` | 원본 보존, LLM 수정 금지 |
| Feature 경험 | `dev/wiki/projects/<project>/features/` | MCP 자동 생성, 설명 후 verified |
| 일일 개발 회고 | `dev/wiki/learning/daily/` | 읽고 행동 하나만 선택 |
| 재사용할 개념 | `dev/wiki/concepts/` | 두 Feature 이상에서 쓰일 때 승격 |
| 실제 오류 해결 | `dev/wiki/debugging/` | 증상·가설·실험·결과가 있을 때만 |
| 독서 지식 | `books/wiki/` | 책 요약보다 내 질문과 연결 중심 |

## 이번 주 학습 규칙

1. 새 학습 주제는 한 번에 하나만 잡는다.
2. 검증 대기 Feature 리뷰가 3개면 새 노트보다 확인을 먼저 한다.
3. Feature 종료 때 코드 흐름을 노트 없이 3~5문장으로 설명한다.
4. 주말에는 지난 개념 하나를 실제 코드와 연결해 다시 설명한다.
5. 설명하거나 적용하지 않은 자료는 아직 내 지식으로 세지 않는다.

## 주요 입구

- [[00-overview/index|전체 위키 인덱스]]
- [[dev/index|개발 위키 인덱스]]
- [[books/index|독서 위키 인덱스]]
- [[dev/wiki/learning/README|Obsidian × Learning MCP 사용법]]

## 최근 Learning MCP 리뷰

```dataview
TABLE WITHOUT ID
  file.link AS "리뷰",
  project AS "프로젝트",
  status AS "상태",
  started AS "시작"
FROM "dev/wiki/projects"
WHERE type = "feature-learning-review"
SORT started DESC
LIMIT 8
```

## 확인이 먼저인 리뷰

```dataview
TABLE WITHOUT ID
  file.link AS "리뷰",
  project AS "프로젝트",
  feature_id AS "Feature"
FROM "dev/wiki/projects"
WHERE type = "feature-learning-review" AND status = "needs-confirmation"
SORT started ASC
```
