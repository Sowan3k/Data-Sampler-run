"""Minimal YouTube Data API v3 client with quota accounting.

Only public, non-authorized endpoints are used. The API key is read from the
YOUTUBE_API_KEY environment variable and is never printed.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Iterator

import httpx

BASE_URL = "https://www.googleapis.com/youtube/v3"
# search.list costs 100 units; the list methods used here cost 1 unit per call.
UNIT_COST = {"search": 1}

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_PATTERNS = (
    re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([A-Za-z0-9_-]{11})"),
)


class YouTubeError(RuntimeError):
    pass


class QuotaExceeded(YouTubeError):
    pass


def extract_video_id(value: str) -> str | None:
    value = value.strip()
    if _ID_RE.match(value):
        return value
    for pattern in _URL_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1)
    return None


def chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


class YouTubeClient:
    def __init__(self, api_key: str | None = None, transport: httpx.BaseTransport | None = None,
                 timeout: float = 30.0, sleep=time.sleep):
        self.api_key = api_key or os.environ.get("YOUTUBE_API_KEY")
        if not self.api_key:
            raise YouTubeError("Set the YOUTUBE_API_KEY environment variable first (see README).")
        self._http = httpx.Client(base_url=BASE_URL, timeout=timeout, transport=transport)
        self._sleep = sleep
        self.units_used = 0
        self.search_calls = 0
        self.general_calls = 0
        self.on_request = None

    def close(self) -> None:
        self._http.close()

    def get(self, endpoint: str, **params: Any) -> dict[str, Any]:
        query = {k: v for k, v in params.items() if v is not None}
        query["key"] = self.api_key
        response = None
        for attempt in range(4):
            if self.on_request:
                self.on_request(endpoint)
            self.units_used += 1
            self.search_calls += int(endpoint == "search")
            self.general_calls += int(endpoint != "search")
            try:
                response = self._http.get(f"/{endpoint}", params=query)
            except httpx.HTTPError:
                raise YouTubeError("Network request failed; retry when connected.") from None
            if response.status_code in (429, 500, 502, 503, 504):
                self._sleep(2 ** attempt)
                continue
            break
        assert response is not None
        if response.status_code >= 400:
            reason, message = "unknown", response.text[:300]
            try:
                err = response.json().get("error", {})
                message = err.get("message", message)
                errors = err.get("errors") or [{}]
                reason = errors[0].get("reason", reason)
            except ValueError:
                pass
            if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
                raise QuotaExceeded(f"Quota exhausted on {endpoint}: {message.replace(self.api_key, '[redacted]')}")
            # The URL contains the key, so build our own message instead of httpx's.
            raise YouTubeError(f"YouTube API {response.status_code} on {endpoint} ({reason}): {message.replace(self.api_key, '[redacted]')}")
        return response.json()

    # --- endpoints -----------------------------------------------------------

    def videos(self, ids: list[str], parts: str = "snippet,contentDetails,status,statistics") -> list[dict]:
        items: list[dict] = []
        for batch in chunks(list(dict.fromkeys(ids)), 50):
            data = self.get("videos", part=parts, id=",".join(batch), maxResults=50)
            items.extend(data.get("items", []))
        return items

    def channels_by_id(self, ids: list[str]) -> list[dict]:
        items: list[dict] = []
        for batch in chunks(list(dict.fromkeys(ids)), 50):
            data = self.get("channels", part="snippet,contentDetails,statistics", id=",".join(batch), maxResults=50)
            items.extend(data.get("items", []))
        return items

    def channel_by_handle(self, handle: str) -> dict | None:
        handle = handle.strip()
        if not handle.startswith("@"):
            handle = "@" + handle
        data = self.get("channels", part="snippet,contentDetails,statistics", forHandle=handle)
        items = data.get("items", [])
        return items[0] if items else None

    def playlist_items(self, playlist_id: str, max_pages: int = 60) -> Iterator[dict]:
        """Yield {'video_id', 'published_at'} for every item in a playlist."""
        token = None
        for _ in range(max_pages):
            data = self.get("playlistItems", part="contentDetails", playlistId=playlist_id,
                            maxResults=50, pageToken=token)
            for item in data.get("items", []):
                details = item.get("contentDetails", {})
                if details.get("videoId"):
                    yield {"video_id": details["videoId"], "published_at": details.get("videoPublishedAt")}
            token = data.get("nextPageToken")
            if not token:
                return

    def search(self, query: str, published_after: str, published_before: str, order: str,
               region_code: str | None, relevance_language: str | None, video_duration: str | None,
               page_token: str | None = None) -> dict[str, Any]:
        return self.get(
            "search", part="snippet", q=query, type="video", maxResults=50, order=order,
            publishedAfter=published_after, publishedBefore=published_before,
            regionCode=region_code, relevanceLanguage=relevance_language,
            videoDuration=video_duration, pageToken=page_token,
        )
