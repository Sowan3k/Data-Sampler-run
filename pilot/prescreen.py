"""Automated metadata pre-screen (proposal section 7.4).

The pre-screen only narrows the pool for human viewing. It never decides
inclusion and never judges AI origin.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any

_DURATION_RE = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?$"
)
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍﻿"), None)


def parse_iso_duration(value: str | None) -> int | None:
    if not value:
        return None
    match = _DURATION_RE.match(value)
    if not match:
        return None
    parts = {k: int(v) if v else 0 for k, v in match.groupdict().items()}
    return parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"]


def normalise(text: str) -> str:
    return unicodedata.normalize("NFC", text).translate(_ZERO_WIDTH).casefold()


def term_hits(text: str, terms: list[str]) -> list[str]:
    """Return the terms found in text.

    Latin-script terms match on word boundaries so 'ai' does not match 'said'.
    Bangla terms match as substrings, because Bangla words take suffixes.
    """
    norm = normalise(text)
    hits = []
    for term in terms:
        t = normalise(term)
        if not t:
            continue
        if t.isascii():
            pattern = r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])"
            if re.search(pattern, norm):
                hits.append(term)
        elif t in norm:
            hits.append(term)
    return hits


def local_date(published_at: str | None, offset_hours: int) -> date | None:
    if not published_at:
        return None
    stamp = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone(timedelta(hours=offset_hours))).date()


def in_period(published_at: str | None, period: dict[str, Any]) -> bool:
    day = local_date(published_at, int(period.get("timezone_offset_hours", 6)))
    if day is None:
        return False
    return date.fromisoformat(str(period["start"])) <= day <= date.fromisoformat(str(period["end"]))


def prescreen_video(video: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """`video` is a row from the videos table (or a dict with the same keys)."""
    rules = cfg["prescreen"]
    tags = video.get("tags_json") or "[]"
    tag_list = json.loads(tags) if isinstance(tags, str) else list(tags)
    text = " ".join([video.get("title") or "", video.get("description") or "", " ".join(tag_list)])
    election = term_hits(text, rules.get("election_terms", []))
    ai = term_hits(text, rules.get("ai_terms", []))
    duration = video.get("duration_seconds")
    is_short = duration is not None and duration <= int(rules.get("max_duration_seconds", 60))
    period_ok = in_period(video.get("published_at"), cfg["study_period"])
    return {
        "in_period": period_ok,
        "is_short": is_short,
        "election_hits": election,
        "ai_hits": ai,
        "candidate": bool(period_ok),
        "priority": "high" if election and ai else "medium" if election or ai else "low",
    }
