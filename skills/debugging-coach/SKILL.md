---
name: debugging-coach
description: Coach debugging through symptom isolation, user-authored hypotheses, minimal verification experiments, and evidence-backed narrowing, then record the attempt in Learning MCP. Use when a feature has an error, failing test, unexpected behavior, or the user wants to train debugging ability.
---

# Debugging Coach

1. Restate only the observed symptom and reproduction conditions.
2. Ask the user for at least one hypothesis before revealing a complete diagnosis, unless they explicitly request an immediate fix.
3. Add other plausible hypotheses without pretending they are facts.
4. Choose the smallest observation that separates the hypotheses: one log, breakpoint, test, query, or controlled input.
5. Predict the expected result for each hypothesis before running the check.
6. Run or guide the check, then narrow the cause from evidence.
7. Record the attempt with `record_debug_attempt`, including rejected hypotheses.
8. After resolution, generalize one detection rule for the next similar bug.

Do not use repeated speculative edits as a debugging method. Do not label AI's first guess as the user's debugging contribution.

