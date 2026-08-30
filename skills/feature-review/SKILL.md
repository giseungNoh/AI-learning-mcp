---
name: feature-review
description: Review a Learning MCP feature or staged commit using compact evidence, separating human and AI ownership, tracing code flow, challenging architecture choices, and recommending up to three study topics. Use for feature completion, commit review, learning review, or AI-dependence assessment.
---

# Feature Review

1. Identify the feature explicitly. If no feature ID was supplied, resolve the host workspace with `git rev-parse --show-toplevel`, then call `get_project_context(project_root=<current Git root>)`. Call `get_feature_manifest(detail="quick")` for that feature first.
2. Check the declared human scope, success conditions, Git stats, decisions, debugging attempts, and token measurement quality.
3. Fetch only necessary refs with `get_evidence`. Start with `diff:staged`; use `diff:working` only when staged is empty or the user asks. Keep the evidence request small.
4. Review in this order:
   - changed behavior and code flow;
   - correctness, tests, and risks;
   - responsibility and dependency direction;
   - simpler and more scalable alternatives;
   - ownership by requirements, architecture, implementation, debugging, and testing.
5. Use only `human-led`, `shared`, `ai-led-verified`, or `ai-led-unverified`. Cite evidence and state uncertainty; token volume is never ownership evidence.
6. Recommend at most three topics. Mark a weakness recurring only when learning history supports it.
7. Ask for a short teach-back about code flow or the main decision. Incorporate the user's correction.
8. Call `save_feature_review`. Set `verified=true` only after confirmation; otherwise save it as false.

Do not modify code during a review unless the user separately requests implementation.
