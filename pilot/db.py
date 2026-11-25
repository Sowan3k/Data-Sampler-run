"""SQLite storage.

Two kinds of data live here and are treated differently:

* API data (titles, descriptions, tags, statistics, durations) comes from the
  YouTube Data API. Policy III.E.4 says it must be refreshed or deleted within
  30 days. `fetched_at` records when each row was last refreshed.
* Research data (discovery provenance, availability checks, search logs,
  model screening, manual codes) is our own observation and is kept.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id          TEXT PRIMARY KEY,
    handle              TEXT,
    title               TEXT,              -- API data
    created_at          TEXT,              -- API data
    subscriber_count    INTEGER,           -- API statistic, 30-day rule
    uploads_playlist_id TEXT,
    is_seed             INTEGER DEFAULT 0,
    fetched_at          TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    video_id                 TEXT PRIMARY KEY,
    channel_id               TEXT,
    channel_title            TEXT,         -- API data
    title                    TEXT,         -- API data
    description              TEXT,         -- API data
    tags_json                TEXT,         -- API data
    published_at             TEXT,
    duration_seconds         INTEGER,
    privacy_status           TEXT,
    synthetic_field_present  INTEGER,      -- 1 if status.containsSyntheticMedia was in the response
    contains_synthetic_media INTEGER,      -- NULL when the field was absent
    view_count               INTEGER,      -- API statistic, 30-day rule
    fetched_at               TEXT
);

CREATE TABLE IF NOT EXISTS discovery (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id      TEXT NOT NULL,
    source        TEXT NOT NULL,   -- seed_video | channel_expansion | search | fact_check | manual
    detail        TEXT NOT NULL DEFAULT '',
    discovered_at TEXT NOT NULL,
    UNIQUE (video_id, source, detail)
);

CREATE TABLE IF NOT EXISTS prescreen (
    video_id       TEXT PRIMARY KEY,
    in_period      INTEGER,
    is_short       INTEGER,
    election_hits  TEXT,
    ai_hits        TEXT,
    candidate      INTEGER,
    computed_at    TEXT
);

CREATE TABLE IF NOT EXISTS availability_checks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id   TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    status     TEXT NOT NULL     -- public | unlisted | private | unavailable
);

CREATE TABLE IF NOT EXISTS search_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    query            TEXT,
    order_by         TEXT,
    published_after  TEXT,
    published_before TEXT,
    page             INTEGER,
    result_count     INTEGER,
    total_results    INTEGER,
    run_at           TEXT
);

CREATE TABLE IF NOT EXISTS gemini_screens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id   TEXT NOT NULL,
    model      TEXT NOT NULL,
    run_at     TEXT NOT NULL,
    parsed_ok  INTEGER NOT NULL,
    output_json TEXT,
    raw_text   TEXT,
    error      TEXT
);

CREATE TABLE IF NOT EXISTS quota_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at  TEXT,
    command TEXT,
    units   INTEGER
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def upsert_video(conn: sqlite3.Connection, item: dict[str, Any], duration_seconds: int | None,
                 fetched_at: str | None = None) -> None:
    """Store one `videos.list` item."""
    fetched_at = fetched_at or utcnow()
    snippet = item.get("snippet", {})
    status = item.get("status", {})
    stats = item.get("statistics", {})
    field_present = 1 if "containsSyntheticMedia" in status else 0
    synthetic = None
    if field_present:
        synthetic = int(status["containsSyntheticMedia"]) if isinstance(status.get("containsSyntheticMedia"), bool) else None
    conn.execute(
        """
        INSERT INTO videos (video_id, channel_id, channel_title, title, description, tags_json,
                            published_at, duration_seconds, privacy_status,
                            synthetic_field_present, contains_synthetic_media, view_count, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            channel_id=excluded.channel_id,
            channel_title=excluded.channel_title,
            title=excluded.title,
            description=excluded.description,
            tags_json=excluded.tags_json,
            published_at=excluded.published_at,
            duration_seconds=excluded.duration_seconds,
            privacy_status=excluded.privacy_status,
            synthetic_field_present=excluded.synthetic_field_present,
            contains_synthetic_media=excluded.contains_synthetic_media,
            view_count=excluded.view_count,
            fetched_at=excluded.fetched_at
        """,
        (
            item["id"],
            snippet.get("channelId"),
            snippet.get("channelTitle"),
            snippet.get("title"),
            snippet.get("description"),
            json.dumps(snippet.get("tags", []), ensure_ascii=False),
            snippet.get("publishedAt"),
            duration_seconds,
            status.get("privacyStatus"),
            field_present,
            synthetic,
            _int(stats.get("viewCount")),
            fetched_at,
        ),
    )


def upsert_channel(conn: sqlite3.Connection, item: dict[str, Any], is_seed: bool = False,
                   handle: str | None = None, fetched_at: str | None = None) -> None:
    fetched_at = fetched_at or utcnow()
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    uploads = item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
    subs = None if stats.get("hiddenSubscriberCount") else _int(stats.get("subscriberCount"))
    conn.execute(
        """
        INSERT INTO channels (channel_id, handle, title, created_at, subscriber_count,
                              uploads_playlist_id, is_seed, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(channel_id) DO UPDATE SET
            handle=COALESCE(excluded.handle, channels.handle),
            title=excluded.title,
            created_at=excluded.created_at,
            subscriber_count=excluded.subscriber_count,
            uploads_playlist_id=COALESCE(excluded.uploads_playlist_id, channels.uploads_playlist_id),
            is_seed=MAX(channels.is_seed, excluded.is_seed),
            fetched_at=excluded.fetched_at
        """,
        (
            item["id"],
            handle or snippet.get("customUrl"),
            snippet.get("title"),
            snippet.get("publishedAt"),
            subs,
            uploads,
            1 if is_seed else 0,
            fetched_at,
        ),
    )


def add_discovery(conn: sqlite3.Connection, video_id: str, source: str, detail: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO discovery (video_id, source, detail, discovered_at) VALUES (?, ?, ?, ?)",
        (video_id, source, detail, utcnow()),
    )


def record_availability(conn: sqlite3.Connection, video_id: str, status: str) -> None:
    conn.execute(
        "INSERT INTO availability_checks (video_id, checked_at, status) VALUES (?, ?, ?)",
        (video_id, utcnow(), status),
    )


def save_prescreen(conn: sqlite3.Connection, video_id: str, result: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO prescreen (video_id, in_period, is_short, election_hits, ai_hits, candidate, computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            in_period=excluded.in_period, is_short=excluded.is_short,
            election_hits=excluded.election_hits, ai_hits=excluded.ai_hits,
            candidate=excluded.candidate, computed_at=excluded.computed_at
        """,
        (
            video_id,
            int(result["in_period"]),
            int(result["is_short"]),
            json.dumps(result["election_hits"], ensure_ascii=False),
            json.dumps(result["ai_hits"], ensure_ascii=False),
            int(result["candidate"]),
            utcnow(),
        ),
    )


def log_quota(conn: sqlite3.Connection, command: str, units: int) -> None:
    conn.execute("INSERT INTO quota_log (run_at, command, units) VALUES (?, ?, ?)", (utcnow(), command, units))


def rows(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, tuple(params)))
