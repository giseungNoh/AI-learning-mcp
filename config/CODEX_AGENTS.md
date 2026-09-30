# Learning MCP automatic tracking

For every substantive code-changing task in a Git worktree, use the `learning-session` skill even when the user does not mention Learning MCP. This includes features, bug fixes, refactors, performance work, data or architecture changes, and meaningful test-system changes.

Do not start a feature for read-only investigation, explanations, tiny typos, formatting-only changes, or trivial documentation edits.

Automatic tracking rules:

1. Resolve the current Git root and call `ensure_feature` before making substantive changes.
2. Continue an active feature when the new request serves the same observable outcome.
3. When the user moves to a clearly different outcome, complete the prior feature only if its acceptance evidence is sufficient; otherwise ask one concise boundary question.
4. Record meaningful decisions and evidence-backed debugging attempts, not routine edits.
5. Checkpoint unfinished work. Never treat inactivity alone as completion.
6. On a real completion signal, call `complete_feature` to preserve final Git evidence and queue an unverified draft review.
7. Never automatically mark a review verified or a concept mastered. Those require user explanation and later reuse.
8. Only attach an exact Codex rollout path; never guess `latest` when sessions may run in parallel.
