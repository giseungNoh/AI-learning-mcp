"""Build bounded evidence packets and persist validated learning results."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .db import Database
from .redaction import ignored, redact
from .schemas import validate_daily


DAILY_PROMPT = """Analyze the day's development evidence. Return JSON with keys:
summary (string), decisions (array of {title, summary, user_reasoning, evidence_refs}),
development_concepts and cs_concepts (arrays of {name, canonical_id, explanation,
why_it_appeared or connection_to_today, related_concepts, evidence_refs}),
weaknesses (array of {concept, reason, confidence, evidence_refs}),
review_candidates (array of strings). Cite only supplied refs. Do not infer a user weakness
from AI-authored text or token counts. Use empty arrays when evidence is insufficient."""

FEATURE_PROMPT = """Review this completed feature using only supplied evidence. Return JSON with
summary, code_flow, ownership (requirements, architecture, implementation, debugging, testing;
each {label, confidence, reason, evidence_refs}), alternatives, weaknesses, next_topics.
Ownership labels: human-led, shared, ai-led-verified, ai-led-unverified. Do not infer ownership
from token counts. Cite only supplied refs. If evidence is weak, use ai-led-unverified and low confidence."""


def _safe_git_listing(content: str, root: Path | None) -> str:
    lines = []
    for line in content.splitlines():
        path = line.split("\t")[-1].strip().removeprefix("?? ")
        if not ignored(path, root):
            lines.append(line)
    return "\n".join(lines)


def daily_packet(db: Database, project_id: str, review_date: str) -> tuple[dict[str, Any], set[str]]:
    date.fromisoformat(review_date)
    with db.connect() as connection:
        project = connection.execute("SELECT id, name FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            raise ValueError("unknown project")
        alias = connection.execute("SELECT local_root FROM project_roots WHERE project_id=? "
                                   "ORDER BY last_seen_at DESC LIMIT 1", (project_id,)).fetchone()
        root = Path(alias["local_root"]) if alias else None
        features = connection.execute(
            "SELECT id, title, goal, baseline_commit, end_commit FROM features "
            "WHERE project_id = ? AND (substr(started_at, 1, 10) = ? OR substr(finished_at, 1, 10) = ?) "
            "ORDER BY started_at LIMIT 30", (project_id, review_date, review_date)).fetchall()
        events = connection.execute(
            "SELECT id, event_type, payload_json, feature_id FROM events "
            "WHERE project_id = ? AND substr(created_at, 1, 10) = ? ORDER BY id LIMIT 100",
            (project_id, review_date)).fetchall()
        decisions = connection.execute(
            "SELECT d.id, d.feature_id, d.question, d.chosen_option, d.reason, d.decided_by "
            "FROM decisions d JOIN features f ON f.id=d.feature_id "
            "WHERE f.project_id=? AND substr(d.created_at, 1, 10)=? ORDER BY d.id LIMIT 50",
            (project_id, review_date)).fetchall()
        debugging = connection.execute(
            "SELECT d.id, d.feature_id, d.symptom, d.hypotheses_json, d.verification, d.outcome "
            "FROM debug_attempts d JOIN features f ON f.id=d.feature_id "
            "WHERE f.project_id=? AND substr(d.created_at, 1, 10)=? ORDER BY d.id LIMIT 50",
            (project_id, review_date)).fetchall()
        evidence = connection.execute(
            "SELECT e.id, e.kind, e.summary, e.content, e.source_ref, e.feature_id "
            "FROM evidence e JOIN features f ON f.id=e.feature_id "
            "WHERE f.project_id=? AND substr(e.created_at, 1, 10)=? "
            "AND e.kind IN ('conversation-user', 'git-snapshot', 'scope') ORDER BY e.id LIMIT 80",
            (project_id, review_date)).fetchall()
    refs: set[str] = set()
    packed_events = []
    for row in events:
        ref = f"event:{row['id']}"
        refs.add(ref)
        packed_events.append({"ref": ref, "type": row["event_type"], "feature_id": row["feature_id"],
                              "payload": row["payload_json"][:1000]})
    packed_decisions = []
    for row in decisions:
        ref = f"decision:{row['id']}"
        refs.add(ref)
        packed_decisions.append({key: (value[:1000] if isinstance(value, str) else value)
                                 for key, value in dict(row).items()} | {"ref": ref})
    packed_debugging = []
    for row in debugging:
        ref = f"debug:{row['id']}"
        refs.add(ref)
        packed_debugging.append({key: (value[:1000] if isinstance(value, str) else value)
                                 for key, value in dict(row).items()} | {"ref": ref})
    packed_evidence = []
    for row in evidence:
        if row["kind"] == "git-snapshot" and row["summary"] not in {
            "git:commits", "git:changed-files", "git:status-final", "git:untracked-final"}:
            continue
        if ignored(row["summary"], root):
            continue
        ref = row["source_ref"] or f"evidence:{row['id']}"
        refs.add(ref)
        content = row["content"]
        if row["summary"] in {"git:changed-files", "git:status-final", "git:untracked-final"}:
            content = _safe_git_listing(content, root)
        packed_evidence.append({"ref": ref, "kind": row["kind"], "summary": row["summary"][:240],
                                "content": content[:1000], "feature_id": row["feature_id"]})
    packet = {"date": review_date, "project": dict(project),
              "features": [dict(row) for row in features], "events": packed_events,
              "decisions": packed_decisions, "debugging": packed_debugging,
              "evidence": packed_evidence}
    return redact(packet), refs


def feature_packet(db: Database, feature_id: str) -> tuple[dict[str, Any], set[str]]:
    with db.connect() as connection:
        feature = connection.execute("SELECT id, title, goal, baseline_commit, end_commit, project_id "
                                     "FROM features WHERE id=?", (feature_id,)).fetchone()
        if feature is None:
            raise ValueError("unknown feature")
        alias = connection.execute("SELECT local_root FROM project_roots WHERE project_id=? "
                                   "ORDER BY last_seen_at DESC LIMIT 1", (feature["project_id"],)).fetchone()
        root = Path(alias["local_root"]) if alias else None
        decisions = connection.execute("SELECT id, question, chosen_option, reason, decided_by FROM decisions "
                                       "WHERE feature_id=? ORDER BY id LIMIT 50", (feature_id,)).fetchall()
        debugging = connection.execute("SELECT id, symptom, hypotheses_json, verification, outcome FROM debug_attempts "
                                       "WHERE feature_id=? ORDER BY id LIMIT 50", (feature_id,)).fetchall()
        events = connection.execute("SELECT id, event_type, payload_json FROM events WHERE feature_id=? "
                                    "ORDER BY id LIMIT 100", (feature_id,)).fetchall()
        evidence = connection.execute("SELECT id, kind, summary, content, source_ref FROM evidence "
                                      "WHERE feature_id=? ORDER BY id LIMIT 100", (feature_id,)).fetchall()
    refs: set[str] = set()
    items = []
    for row in evidence:
        if row["kind"] == "git-snapshot" and row["summary"] not in {
            "git:commits", "git:changed-files", "git:status-final", "git:untracked-final"}:
            continue
        ref = row["source_ref"] or f"evidence:{row['id']}"
        refs.add(ref)
        content = row["content"]
        if row["summary"] in {"git:changed-files", "git:status-final", "git:untracked-final"}:
            content = _safe_git_listing(content, root)
        items.append({"ref": ref, "kind": row["kind"], "summary": row["summary"],
                      "content": content[:1000]})
    decision_items = []
    for row in decisions:
        ref = f"decision:{row['id']}"
        refs.add(ref)
        decision_items.append(dict(row) | {"ref": ref})
    debug_items = []
    for row in debugging:
        ref = f"debug:{row['id']}"
        refs.add(ref)
        debug_items.append(dict(row) | {"ref": ref})
    event_items = []
    for row in events:
        ref = f"event:{row['id']}"
        refs.add(ref)
        event_items.append({"ref": ref, "type": row["event_type"], "payload": row["payload_json"][:1000]})
    return redact({"feature": dict(feature), "decisions": decision_items,
                   "debugging": debug_items, "events": event_items, "evidence": items}), refs


def store_daily(db: Database, project_id: str, review_date: str,
                raw: dict[str, Any], allowed_refs: set[str], vault: Path | None,
                official_sources: list[dict[str, str]] | None = None,
                obsidian_base_dir: Path = Path("dev/wiki")) -> dict[str, Any]:
    from .learning_notes import write_daily, write_concept
    from .official_sources import group_sources

    result = validate_daily(raw, allowed_refs)
    sources_by_topic = group_sources(official_sources or [])
    for concept in result["concepts"]:
        concept["official_sources"] = sources_by_topic.get(concept["id"], [])
    with db.connect() as connection:
        existing = connection.execute("SELECT id, obsidian_path FROM daily_reviews "
                                      "WHERE project_id=? AND review_date=?", (project_id, review_date)).fetchone()
        if existing:
            return {"review_id": existing["id"], "obsidian_path": existing["obsidian_path"], "deduplicated": True}
        project = connection.execute("SELECT name FROM projects WHERE id=?", (project_id,)).fetchone()
        if project is None:
            raise ValueError("unknown project")
        from .jobs import now
        timestamp = now()
        path = write_daily(vault, project["name"], review_date, result, obsidian_base_dir) if vault else None
        cursor = connection.execute(
            "INSERT INTO daily_reviews(project_id, review_date, result_json, obsidian_path, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, review_date, json.dumps(result, ensure_ascii=False), path, timestamp))
        for concept in result["concepts"]:
            concept_path = write_concept(vault, concept, review_date, obsidian_base_dir) if vault else None
            connection.execute(
                "INSERT INTO concepts(id, canonical_name, concept_type, category, obsidian_path, first_seen_at, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET last_seen_at=excluded.last_seen_at, "
                "obsidian_path=COALESCE(concepts.obsidian_path, excluded.obsidian_path)",
                (concept["id"], concept["name"], concept["type"],
                 concept["id"].split(".")[1], concept_path, timestamp, timestamp))
            for ref in concept["evidence_refs"]:
                connection.execute(
                    "INSERT OR IGNORE INTO concept_occurrences "
                    "(concept_id, project_id, feature_id, evidence_ref, role, created_at) "
                    "VALUES (?, ?, NULL, ?, 'discussed', ?)",
                    (concept["id"], project_id, ref, timestamp))
        return {"review_id": cursor.lastrowid, "obsidian_path": path, "concepts": len(result["concepts"])}
