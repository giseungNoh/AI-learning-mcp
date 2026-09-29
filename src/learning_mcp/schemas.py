"""Strict validation at the model-to-storage boundary."""

from __future__ import annotations

import re
from typing import Any

CONCEPT_ID = re.compile(r"^(cs|dev|tech|pattern|tool)\.[a-z0-9]+(?:[.-][a-z0-9]+)*$")

_STR = {"type": "string"}
_STR_LIST = {"type": "array", "items": _STR}
_REFS = _STR_LIST
DAILY_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": _STR,
        "decisions": {"type": "array", "items": {"type": "object", "properties": {
            "title": _STR, "summary": _STR, "user_reasoning": _STR, "evidence_refs": _REFS},
            "required": ["title", "summary", "user_reasoning", "evidence_refs"]}},
        "development_concepts": {"type": "array", "items": {"type": "object", "properties": {
            "name": _STR, "canonical_id": _STR, "explanation": _STR, "why_it_appeared": _STR,
            "related_cs_concepts": _STR_LIST, "evidence_refs": _REFS},
            "required": ["name", "canonical_id", "explanation", "why_it_appeared", "related_cs_concepts", "evidence_refs"]}},
        "cs_concepts": {"type": "array", "items": {"type": "object", "properties": {
            "name": _STR, "canonical_id": _STR, "explanation": _STR, "connection_to_today": _STR,
            "related_concepts": _STR_LIST, "evidence_refs": _REFS},
            "required": ["name", "canonical_id", "explanation", "connection_to_today", "related_concepts", "evidence_refs"]}},
        "weaknesses": {"type": "array", "items": {"type": "object", "properties": {
            "concept": _STR, "reason": _STR, "confidence": {"type": "number"}, "evidence_refs": _REFS},
            "required": ["concept", "reason", "confidence", "evidence_refs"]}},
        "review_candidates": _STR_LIST,
    },
    "required": ["summary", "decisions", "development_concepts", "cs_concepts", "weaknesses", "review_candidates"],
}

_OWNERSHIP_ENTRY = {"type": "object", "properties": {
    "label": _STR, "confidence": {"type": "number"}, "reason": _STR, "evidence_refs": _REFS},
    "required": ["label", "confidence", "reason", "evidence_refs"]}
FEATURE_JSON_SCHEMA = {"type": "object", "properties": {
    "summary": _STR, "code_flow": _STR,
    "ownership": {"type": "object", "properties": {area: _OWNERSHIP_ENTRY for area in
                  ("requirements", "architecture", "implementation", "debugging", "testing")},
                  "required": ["requirements", "architecture", "implementation", "debugging", "testing"]},
    "alternatives": _STR_LIST, "weaknesses": _STR_LIST, "next_topics": _STR_LIST},
    "required": ["summary", "code_flow", "ownership", "alternatives", "weaknesses", "next_topics"]}
JUDGMENT_JSON_SCHEMA = {"type": "object", "properties": {
    "should_ask_user": {"type": "boolean"}, "importance": {"type": "integer"},
    "reason": _STR, "question": _STR},
    "required": ["should_ask_user", "importance", "reason", "question"]}


def _string(value: Any, name: str, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be a nonempty string of at most {limit} characters")
    return value.strip()


def _list(value: Any, name: str, limit: int = 30) -> list[Any]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{name} must be a list with at most {limit} items")
    return value


def validate_daily(value: dict[str, Any], allowed_refs: set[str]) -> dict[str, Any]:
    summary = _string(value.get("summary"), "summary")
    decisions = []
    for item in _list(value.get("decisions"), "decisions"):
        decisions.append({
            "title": _string(item.get("title"), "decision.title", 200),
            "summary": _string(item.get("summary"), "decision.summary"),
            "user_reasoning": str(item.get("user_reasoning") or "")[:2000],
            "evidence_refs": _refs(item.get("evidence_refs", []), allowed_refs),
        })
    concepts = []
    seen = set()
    for group, prefix in (("development_concepts", "dev"), ("cs_concepts", "cs")):
        for item in _list(value.get(group), group):
            raw_id = _string(item.get("canonical_id"), "canonical_id", 120)
            if not re.fullmatch(r"[A-Za-z0-9._ -]+", raw_id) or ".." in raw_id:
                raise ValueError(f"invalid concept id: {raw_id}")
            cid = re.sub(r"[-_ ]+", "-", raw_id.lower()).strip("-.")
            if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", cid):
                cid = f"{prefix}.{cid}"
            if not CONCEPT_ID.fullmatch(cid) or not cid.startswith(prefix + "."):
                raise ValueError(f"invalid concept id: {cid}")
            if cid in seen:
                continue
            seen.add(cid)
            concepts.append({
                "id": cid, "type": prefix,
                "name": _string(item.get("name"), "concept.name", 200),
                "explanation": _string(item.get("explanation"), "concept.explanation"),
                "connection": str(item.get("connection_to_today") or item.get("why_it_appeared") or "")[:2000],
                "related_concepts": [_string(x, "related concept", 200) for x in
                                     _list(item.get("related_concepts", item.get("related_cs_concepts", [])), "related_concepts")],
                "evidence_refs": _refs(item.get("evidence_refs", []), allowed_refs),
            })
    weaknesses = []
    for item in _list(value.get("weaknesses"), "weaknesses"):
        confidence = item.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("weakness confidence must be between 0 and 1")
        refs = _refs(item.get("evidence_refs", []), allowed_refs)
        if not refs:
            raise ValueError("weakness must cite evidence")
        weaknesses.append({"concept": _string(item.get("concept"), "weakness.concept", 200),
                           "reason": _string(item.get("reason"), "weakness.reason"),
                           "confidence": float(confidence), "evidence_refs": refs})
    return {"summary": summary, "decisions": decisions, "concepts": concepts,
            "weaknesses": weaknesses,
            "review_candidates": [_string(x, "review candidate", 200) for x in
                                  _list(value.get("review_candidates", []), "review_candidates")]}


def _refs(value: Any, allowed: set[str]) -> list[str]:
    refs = _list(value, "evidence_refs", 20)
    if any(not isinstance(ref, str) or ref not in allowed for ref in refs):
        raise ValueError("unknown evidence ref")
    return list(dict.fromkeys(refs))


def validate_judgment(value: dict[str, Any]) -> dict[str, Any]:
    importance = value.get("importance")
    if not isinstance(importance, int) or not 0 <= importance <= 100:
        raise ValueError("importance must be 0..100")
    should_ask = value.get("should_ask_user")
    if not isinstance(should_ask, bool):
        raise ValueError("should_ask_user must be boolean")
    return {"should_ask_user": should_ask, "importance": importance,
            "reason": _string(value.get("reason"), "reason", 1000),
            "question": _string(value.get("question"), "question", 1000) if should_ask else ""}


def validate_feature_review(value: dict[str, Any], allowed_refs: set[str]) -> dict[str, Any]:
    areas = {"requirements", "architecture", "implementation", "debugging", "testing"}
    ownership = value.get("ownership")
    if not isinstance(ownership, dict) or set(ownership) != areas:
        raise ValueError("ownership must contain all five areas")
    normalized = {}
    for area, entry in ownership.items():
        if not isinstance(entry, dict) or entry.get("label") not in {
            "human-led", "shared", "ai-led-verified", "ai-led-unverified"}:
            raise ValueError(f"invalid ownership for {area}")
        confidence = entry.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("ownership confidence must be 0..1")
        normalized[area] = {"label": entry["label"], "confidence": float(confidence),
                            "reason": _string(entry.get("reason"), "ownership.reason", 1000),
                            "evidence_refs": _refs(entry.get("evidence_refs", []), allowed_refs)}
    return {"summary": _string(value.get("summary"), "summary"),
            "code_flow": _string(value.get("code_flow"), "code_flow"),
            "ownership": normalized,
            "alternatives": [_string(x, "alternative", 500) for x in
                             _list(value.get("alternatives", []), "alternatives")],
            "weaknesses": [_string(x, "weakness", 200) for x in
                           _list(value.get("weaknesses", []), "weaknesses")],
            "next_topics": [_string(x, "next topic", 200) for x in
                            _list(value.get("next_topics", []), "next_topics", 3)]}
