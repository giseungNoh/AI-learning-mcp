"""Constrained Gemini web lookup for official technical documentation."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .gemini_client import OfficialDocsClient

OFFICIAL_SOURCES_SCHEMA = {
    "type": "object",
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic_key": {"type": "string"},
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "publisher": {"type": "string"},
                    "source_type": {
                        "type": "string",
                        "enum": ["official-documentation", "standard", "primary-paper"],
                    },
                    "reason": {"type": "string"},
                },
                "required": ["topic_key", "title", "url", "publisher", "source_type", "reason"],
            },
        }
    },
    "required": ["sources"],
}

OFFICIAL_SOURCES_PROMPT = """Search for authoritative sources for each supplied technical topic.
Return {"sources": [...]} using the requested schema. Prefer, in order:
1. the technology owner's official documentation or language/platform reference;
2. a standards body specification such as IETF, W3C, WHATWG, ISO, or ECMA;
3. the primary research paper or canonical project documentation.

Do not return blogs, tutorials, aggregators, SEO pages, Stack Overflow, Reddit, or unofficial mirrors.
Use only titles, publishers, and exact URLs displayed in web-search results; do not open result pages.
Return at most three sources per topic_key. If an authoritative result is not present in the search
results, return no source for that topic. Never guess, reconstruct, or normalize a URL."""


def _public_url(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 2_000:
        raise ValueError("official source URL must be a string of at most 2000 characters")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("official source URL must be a public http(s) URL")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or "." not in hostname:
        raise ValueError("official source URL must have a public hostname")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
            raise ValueError("official source URL cannot target a private address")
    return value.strip()


def validate_official_sources(value: dict[str, Any], allowed_topic_keys: set[str]) -> list[dict[str, str]]:
    raw = value.get("sources")
    if not isinstance(raw, list) or len(raw) > max(30, len(allowed_topic_keys) * 3):
        raise ValueError("official sources must be a bounded list")
    normalized: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    counts: dict[str, int] = {}
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("official source entries must be objects")
        topic_key = str(item.get("topic_key") or "").strip()
        if topic_key not in allowed_topic_keys:
            raise ValueError(f"unknown official source topic: {topic_key}")
        source_type = item.get("source_type")
        if source_type not in {"official-documentation", "standard", "primary-paper"}:
            raise ValueError("invalid official source type")
        url = _public_url(item.get("url"))
        if url in seen_urls or counts.get(topic_key, 0) >= 3:
            continue
        title = str(item.get("title") or "").strip()
        publisher = str(item.get("publisher") or "").strip()
        reason = str(item.get("reason") or "").strip()
        if not title or not publisher or not reason:
            raise ValueError("official source title, publisher, and reason are required")
        if max(len(title), len(publisher), len(reason)) > 500:
            raise ValueError("official source metadata is too long")
        normalized.append({
            "topic_key": topic_key,
            "title": title,
            "url": url,
            "publisher": publisher,
            "source_type": source_type,
            "reason": reason,
        })
        seen_urls.add(url)
        counts[topic_key] = counts.get(topic_key, 0) + 1
    return normalized


def lookup_official_sources(topics: list[dict[str, str]], cwd: Path) -> list[dict[str, str]]:
    if not topics:
        return []
    allowed = {item["key"] for item in topics}
    raw = OfficialDocsClient().generate(
        OFFICIAL_SOURCES_PROMPT,
        {"topics": topics},
        cwd,
        OFFICIAL_SOURCES_SCHEMA,
        web_search=True,
    )
    return validate_official_sources(raw, allowed)


def group_sources(sources: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for source in sources:
        grouped.setdefault(source["topic_key"], []).append(source)
    return grouped
