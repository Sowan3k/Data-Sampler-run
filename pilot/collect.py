"""Corpus construction: field check, seed resolution, channel expansion, search."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable

from . import db
from .prescreen import in_period, parse_iso_duration, prescreen_video
from .youtube import YouTubeClient, extract_video_id

Log = Callable[[str], None]


def _store_videos(conn: sqlite3.Connection, cfg: dict[str, Any], items: list[dict],
                  source: str, detail_for: Callable[[dict], str]) -> int:
    """Upsert video items, record discovery and availability, run the pre-screen."""
    candidates = 0
    for item in items:
        duration = parse_iso_duration(item.get("contentDetails", {}).get("duration"))
        db.upsert_video(conn, item, duration)
        db.add_discovery(conn, item["id"], source, detail_for(item))
        db.record_availability(conn, item["id"], item.get("status", {}).get("privacyStatus", "public"))
        row = dict(conn.execute("SELECT * FROM videos WHERE video_id = ?", (item["id"],)).fetchone())
        result = prescreen_video(row, cfg)
        db.save_prescreen(conn, item["id"], result)
        candidates += int(result["candidate"])
    conn.commit()
    return candidates


def check_synthetic_field(client: YouTubeClient, video_ids: list[str]) -> list[dict[str, Any]]:
    """Report whether status.containsSyntheticMedia is returned to a non-owner."""
    items = {item["id"]: item for item in client.videos(video_ids, parts="snippet,status")}
    report = []
    for vid in video_ids:
        item = items.get(vid)
        if item is None:
            report.append({"video_id": vid, "available": False, "field_present": None, "value": None, "title": None})
            continue
        status = item.get("status", {})
        report.append({
            "video_id": vid,
            "available": True,
            "field_present": "containsSyntheticMedia" in status,
            "value": status.get("containsSyntheticMedia"),
            "title": item.get("snippet", {}).get("title"),
        })
    return report


def resolve_seeds(client: YouTubeClient, conn: sqlite3.Connection, cfg: dict[str, Any], log: Log = print) -> list[str]:
    """Turn seed videos, handles and channel IDs into a list of channel IDs."""
    seeds = cfg["seeds"]
    channel_ids: list[str] = list(seeds.get("channel_ids", []))

    video_ids = []
    for raw in seeds.get("videos", []):
        vid = extract_video_id(str(raw))
        if vid:
            video_ids.append(vid)
        else:
            log(f"  could not read a video ID from: {raw}")
    if video_ids:
        items = client.videos(video_ids)
        found = {item["id"] for item in items}
        _store_videos(conn, cfg, items, "seed_video", lambda _item: "config")
        for vid in video_ids:
            if vid not in found:
                db.add_discovery(conn, vid, "seed_video", "config")
                db.record_availability(conn, vid, "unavailable")
                log(f"  seed video {vid} is unavailable")
        channel_ids += [item["snippet"]["channelId"] for item in items]
        conn.commit()

    for handle in seeds.get("handles", []):
        item = client.channel_by_handle(str(handle))
        if item is None:
            log(f"  handle not found: {handle}")
            continue
        db.upsert_channel(conn, item, is_seed=True, handle=str(handle))
        channel_ids.append(item["id"])
    conn.commit()
    return list(dict.fromkeys(channel_ids))


def expand_channels(client: YouTubeClient, conn: sqlite3.Connection, cfg: dict[str, Any],
                    channel_ids: list[str], log: Log = print) -> dict[str, dict[str, int]]:
    """Retrieve the full upload history of each channel and keep in-period uploads."""
    summary: dict[str, dict[str, int]] = {}
    period = cfg["study_period"]
    channels = client.channels_by_id(channel_ids)
    returned = {c["id"] for c in channels}
    for missing in set(channel_ids) - returned:
        log(f"  channel {missing} not returned (deleted, terminated or wrong ID)")
    for channel in channels:
        db.upsert_channel(conn, channel, is_seed=True)
        title = channel.get("snippet", {}).get("title", channel["id"])
        uploads = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        if not uploads:
            log(f"  {title}: no uploads playlist")
            continue
        all_items = list(client.playlist_items(uploads))
        in_range = [i["video_id"] for i in all_items if in_period(i["published_at"], period)]
        items = client.videos(in_range) if in_range else []
        n_candidates = _store_videos(conn, cfg, items, "channel_expansion", lambda _i, cid=channel["id"]: cid)
        summary[channel["id"]] = {
            "uploads_listed": len(all_items),
            "in_period": len(in_range),
            "details_returned": len(items),
            "candidates": n_candidates,
        }
        log(f"  {title}: {len(all_items)} uploads, {len(in_range)} in period, {n_candidates} candidates")
    conn.commit()
    return summary


def month_windows(start: str, end: str, offset_hours: int = 6) -> list[tuple[str, str]]:
    """Calendar-month windows in local time, returned as UTC RFC 3339 strings."""
    tz = timezone(timedelta(hours=offset_hours))
    first, last = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    windows = []
    cursor = first
    while cursor <= last:
        next_month = (cursor.replace(day=1) + timedelta(days=32)).replace(day=1)
        stop = min(next_month, last + timedelta(days=1))
        to_utc = lambda d: datetime.combine(d, time.min, tz).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        windows.append((to_utc(cursor), to_utc(stop)))
        cursor = stop
    return windows


def run_search(client: YouTubeClient, conn: sqlite3.Connection, cfg: dict[str, Any],
               max_calls: int | None = None, log: Log = print) -> dict[str, int]:
    """Logged keyword search over monthly windows (proposal section 7.3, source 3)."""
    s = cfg["search"]
    period = cfg["study_period"]
    windows = month_windows(period["start"], period["end"], int(period.get("timezone_offset_hours", 6)))
    calls, found_ids = 0, {}
    for query in s.get("queries", []):
        for order in s.get("orders", ["relevance"]):
            for after, before in windows:
                token = None
                for page in range(1, int(s.get("max_pages_per_query", 1)) + 1):
                    if max_calls is not None and calls >= max_calls:
                        log(f"  stopped after {calls} search calls (limit)")
                        return _finish_search(client, conn, cfg, found_ids, calls)
                    data = client.search(query, after, before, order, s.get("region_code"),
                                         s.get("relevance_language"), s.get("video_duration"), token)
                    calls += 1
                    items = data.get("items", [])
                    conn.execute(
                        """INSERT INTO search_log (query, order_by, published_after, published_before,
                           page, result_count, total_results, run_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (query, order, after, before, page, len(items),
                         data.get("pageInfo", {}).get("totalResults"), db.utcnow()),
                    )
                    for item in items:
                        vid = item.get("id", {}).get("videoId")
                        if vid:
                            found_ids.setdefault(vid, f"{query} | {order} | {after[:10]}")
                    token = data.get("nextPageToken")
                    if not token:
                        break
    conn.commit()
    return _finish_search(client, conn, cfg, found_ids, calls)


def _finish_search(client: YouTubeClient, conn: sqlite3.Connection, cfg: dict[str, Any],
                   found_ids: dict[str, str], calls: int) -> dict[str, int]:
    items = client.videos(list(found_ids)) if found_ids else []
    candidates = _store_videos(conn, cfg, items, "search", lambda item: found_ids.get(item["id"], ""))
    return {"search_calls": calls, "videos_found": len(found_ids), "candidates": candidates}
