"""Background entry point for queued session and review work."""

from __future__ import annotations

import json
import os
import time
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

from . import jobs
from .service import LearningService
from .gemini_client import GeminiClient
from .learning import DAILY_PROMPT, FEATURE_PROMPT, daily_packet, feature_packet, store_daily
from .official_sources import lookup_official_sources
from .schemas import DAILY_JSON_SCHEMA, FEATURE_JSON_SCHEMA, validate_daily, validate_feature_review


def run_once(service: LearningService) -> bool:
    job = jobs.claim(service.db)
    if job is None:
        return False
    try:
        payload = json.loads(job["payload_json"])
        if job["job_type"] == "session_sync":
            service.sync_codex_session(job["feature_id"], payload["session_file"], payload["phase"])
        elif job["job_type"] == "daily_review":
            packet, refs = daily_packet(service.db, job["project_id"], payload["review_date"])
            with tempfile.TemporaryDirectory() as scratch:
                scratch_path = Path(scratch)
                raw = GeminiClient().generate(DAILY_PROMPT, packet, scratch_path, DAILY_JSON_SCHEMA)
                preview = validate_daily(raw, refs)
                official_sources = lookup_official_sources(
                    [{"key": concept["id"], "name": concept["name"], "kind": concept["type"]}
                     for concept in preview["concepts"]],
                    scratch_path,
                )
            store_daily(service.db, job["project_id"], payload["review_date"],
                        raw, refs, service.settings.obsidian_vault, official_sources,
                        service.settings.obsidian_base_dir)
        elif job["job_type"] == "feature_review":
            packet, refs = feature_packet(service.db, job["feature_id"])
            with tempfile.TemporaryDirectory() as scratch:
                scratch_path = Path(scratch)
                raw = GeminiClient().generate(FEATURE_PROMPT, packet, scratch_path, FEATURE_JSON_SCHEMA)
                review = validate_feature_review(raw, refs)
                official_sources = lookup_official_sources(
                    [{"key": f"next-topic:{index}", "name": topic, "kind": "learning-topic"}
                     for index, topic in enumerate(review["next_topics"])],
                    scratch_path,
                )
            service.save_feature_review(job["feature_id"], review["summary"], review["code_flow"],
                                        review["ownership"], review["alternatives"], review["weaknesses"],
                                        review["next_topics"], verified=False,
                                        official_sources=official_sources)
        else:
            raise ValueError(f"unsupported job type: {job['job_type']}")
    except Exception as exc:
        jobs.fail(service.db, job["id"], str(exc))
    else:
        jobs.complete(service.db, job["id"])
    return True


def main() -> None:
    service = LearningService()
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
    jobs.recover_stale(service.db, stale)
    try:
        last_schedule = 0.0
        last_heartbeat = 0.0
        while True:
            if time.monotonic() - last_heartbeat >= 10:
                jobs.write_runtime_state(service.db, "worker-heartbeat", {
                    "pid": os.getpid(), "state": "running",
                })
                last_heartbeat = time.monotonic()
            if time.monotonic() - last_schedule >= 60:
                schedule_inactive_daily(service)
                last_schedule = time.monotonic()
            if not run_once(service):
                time.sleep(1)
    except KeyboardInterrupt:
        pass


def schedule_inactive_daily(service: LearningService, idle_minutes: int = 60) -> int:
    from datetime import date
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=idle_minutes)
    today = datetime.now().astimezone().date()
    with service.db.connect() as connection:
        rows = connection.execute(
            "SELECT project_id, substr(created_at, 1, 10) AS day, MAX(created_at) AS latest "
            "FROM events GROUP BY project_id, substr(created_at, 1, 10) ORDER BY day"
        ).fetchall()
    queued = 0
    for row in rows:
        if date.fromisoformat(row["day"]) > today:
            continue
        if datetime.fromisoformat(row["latest"]).astimezone(timezone.utc) > cutoff:
            continue
        with service.db.connect() as connection:
            exists = connection.execute("SELECT 1 FROM daily_reviews WHERE project_id=? AND review_date=?",
                                        (row["project_id"], row["day"])).fetchone()
            attempted = connection.execute("SELECT 1 FROM jobs WHERE dedupe_key=?",
                                           (f"daily:{row['project_id']}:{row['day']}",)).fetchone()
        if not exists and not attempted:
            jobs.enqueue(service.db, "daily_review", {"review_date": row["day"]},
                         project_id=row["project_id"], dedupe_key=f"daily:{row['project_id']}:{row['day']}")
            queued += 1
    return queued


if __name__ == "__main__":
    main()
