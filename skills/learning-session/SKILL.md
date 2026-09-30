---
name: learning-session
description: Automatically track substantive code-changing work as Learning MCP features, including goals, Git evidence, decisions, debugging, checkpoints, draft review, and completion. Use by default for feature work, bug fixes, refactors, performance changes, and test-system changes even when the user does not mention Learning MCP. Skip read-only questions, tiny typos, formatting-only edits, and trivial documentation changes.
---

# Learning Session

## Automatic start or continue

1. Determine the current target repository with `git rev-parse --show-toplevel` from the host workspace. Use its absolute result as `project_root`; never substitute the Learning MCP server directory or a remembered project path.
2. Treat a request as substantive when it changes runtime behavior, fixes a bug, changes architecture or data, improves performance, or adds meaningful tests. Do not create a feature for read-only analysis, tiny typos, formatting-only edits, or trivial docs.
3. Infer a short title, goal, and observable success conditions from the request. Preserve any approach or acceptance criteria already stated by the user; do not make the user repeat them.
4. Separate `user_owned_scope` from `ai_allowed_scope`. Keep product intent, hard-to-reverse architecture, ambiguous feature boundaries, and final verification in the human scope. Repetitive implementation and mechanical tests may be AI-allowed.
5. Call `ensure_feature`, not `start_feature`, so retries continue the existing active feature instead of creating duplicates.
6. If `ensure_feature` returns an active feature whose outcome clearly differs from the new request, do not silently merge them. If the prior success conditions are demonstrably complete, call `complete_feature` and then ensure the new feature. If completion is ambiguous, ask one concise boundary question.
7. Pass `session_file` only when the exact current Codex rollout JSONL path is known. Never use or guess `latest` when parallel sessions may exist.
8. If the current path is not a Git worktree, continue the user's task without Learning MCP and briefly report that automatic tracking was skipped.

## During work

- Call `record_decision` only for meaningful tradeoffs, not routine edits.
- When debugging, use the `debugging-coach` skill and save the hypothesis with `record_debug_attempt`.
- Preserve the user's original reasoning before presenting an answer.
- Use `checkpoint_feature` after a meaningful tested milestone or when the user pauses unfinished work. Inactivity is a checkpoint signal, never proof of completion.
- Do not interrupt the user merely to report routine tracking calls.

## Automatic completion and review

1. Treat explicit completion, moving to a clearly different feature, successful acceptance tests followed by handoff, commit/PR preparation, or a direct review request as completion signals. A passing unit test alone is not sufficient.
2. Call `complete_feature` with the observed completion summary and test evidence. This captures final Git evidence and queues an unverified draft review.
3. Never automatically mark a review `verified` or a concept `mastered`.
4. When the user asks for a review or has time for teach-back, run the `feature-review` skill, let the user correct ownership, and save verified only after the user's explanation.
5. If the task stops unfinished, checkpoint it and leave the feature active.

When the feature ID is unknown, resolve the current Git root again and call `get_project_context(project_root=<current Git root>)`. Do not use another project's active feature.
