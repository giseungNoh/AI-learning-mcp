---
name: promote-feature-to-book
description: Turn verified Learning MCP feature reviews into evidence bundles for the existing book writer and read-only reviewer. Use when the user wants to convert development experience, architecture decisions, or debugging cases into an Obsidian book chapter candidate.
---

# Promote Feature to Book

1. Use only reviews marked verified.
2. Group related feature reviews, decisions, and debugging cases by one teachable concept. Do not create one chapter per feature by default.
3. Recheck every experience claim against feature/debug/decision IDs and every code claim against a commit SHA and source path.
4. Separate historical code, current code, and proposed code explicitly.
5. Produce a chapter evidence bundle containing:
   - title and concepts;
   - source files and symbols;
   - feature review paths;
   - decision and debugging refs;
   - commits;
   - verified human reasoning;
   - unresolved uncertainty.
6. Pass the bundle to the existing chapter writer as optional learning evidence.
7. Require the read-only chapter reviewer to verify both source code and evidence refs.

Never present generated scenarios as events the user actually experienced.

