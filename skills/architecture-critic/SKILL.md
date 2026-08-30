---
name: architecture-critic
description: Critically compare a feature architecture with a simpler option and a more scalable option, checking responsibility boundaries, dependency direction, testability, operational cost, and premature abstraction. Use for architecture reviews, technology choices, ADRs, or “is there another way?” questions.
---

# Architecture Critic

1. Read the feature manifest and selected decision/diff evidence; avoid loading full history by default.
2. State the current design as system, flow, and responsibility.
3. Compare exactly three useful options when possible: current, simpler, and scale-oriented.
4. Evaluate each option against current constraints, failure modes, testing, migration cost, and reversibility.
5. Challenge both under-design and premature abstraction.
6. Recommend one option for the present stage and state the condition that should trigger reconsideration.
7. Record the final user-confirmed choice with `record_decision`.

Prefer evidence from current code and requirements. Do not recommend a framework merely because it is popular.

