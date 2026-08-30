---
name: learning-session
description: Start and finish feature-based developer learning sessions with explicit goals, success conditions, human-owned decisions, and AI-allowed work. Use when the user starts a feature, asks to track a coding task, or wants the Learning MCP to measure a development session.
---

# Learning Session

## Start

1. Determine the current target repository with `git rev-parse --show-toplevel` from the host workspace. Use its absolute result as `project_root`; never substitute the Learning MCP server directory or a remembered project path.
2. Ask the user to state their approach before proposing architecture.
3. Identify the feature goal and observable success conditions.
4. Separate `user_owned_scope` from `ai_allowed_scope`. Put architecture, technical direction, or debugging in the human scope when the user wants to train it.
5. Call `start_feature(project_root=<current Git root>, ...)` once. Keep one active feature per project. If the current path is not a Git worktree, stop and explain that Git initialization or the correct workspace is required.
6. If the exact current Codex rollout JSONL path is known, immediately call `sync_codex_session` with `phase="start"`. Do not guess a path.

## During work

- Call `record_decision` only for meaningful tradeoffs, not routine edits.
- When debugging, use the `debugging-coach` skill and save the hypothesis with `record_debug_attempt`.
- Preserve the user's original reasoning before presenting an answer.

## Finish

1. Run the `feature-review` skill.
2. Let the user correct ownership judgments.
3. Save the review as unverified until the correction or teach-back is complete.
4. Call `finish_feature` after the review is saved.

When the feature ID is unknown, resolve the current Git root again and call `get_project_context(project_root=<current Git root>)`. Do not use another project's active feature.
