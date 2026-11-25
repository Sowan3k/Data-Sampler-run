"""Offline tests. A fake YouTube API (httpx.MockTransport) and a fake Gemini client
stand in for the real services, so no keys or network are needed."""
from __future__ import annotations

import csv
import json
from types import SimpleNamespace

import httpx
import pytest

from pilot import collect, db, gemini_screen
from pilot.prescreen import in_period, parse_iso_duration, prescreen_video, term_hits
from pilot.youtube import QuotaExceeded, YouTubeClient, extract_video_id

CFG = {
    "study_period": {"start": "2025-06-15", "end": "2026-02-12", "timezone_offset_hours": 6},
    "seeds": {"videos": ["https://youtube.com/shorts/AAAAAAAAAA1"], "handles": ["@ai_world"], "channel_ids": []},
    "prescreen": {"max_duration_seconds": 60,
                  "election_terms": ["নির্বাচন", "ভোট", "মতামত", "election"],
                  "ai_terms": ["#ai", "ai", "veo3", "এআই"]},
    "search": {"region_code": "BD", "relevance_language": "bn", "orders": ["relevance"],
               "max_pages_per_query": 1, "video_duration": "short", "queries": ["জনমত"]},
    "gemini": {"model": "test-model", "seconds_between_calls": 0, "party_symbols": {"ধানের শীষ": "BNP"}},
    "storage": {"db_path": ":memory:", "api_data_max_age_days": 30},
}


def video_item(vid, channel="UC_one", title="নির্বাচন নিয়ে মতামত #ai", published="2025-12-01T10:00:00Z",
               duration="PT12S", synthetic=None):
    status = {"privacyStatus": "public"}
    if synthetic is not None:
        status["containsSyntheticMedia"] = synthetic
    return {"id": vid, "snippet": {"channelId": channel, "channelTitle": "Ai World", "title": title,
                                   "description": "", "tags": ["veo3"], "publishedAt": published},
            "contentDetails": {"duration": duration}, "status": status, "statistics": {"viewCount": "43000"}}


VIDEOS = {
    "AAAAAAAAAA1": video_item("AAAAAAAAAA1", synthetic=True),
    "AAAAAAAAAA2": video_item("AAAAAAAAAA2", title="রান্নার রেসিপি", duration="PT10S"),        # not election
    "AAAAAAAAAA3": video_item("AAAAAAAAAA3", duration="PT8M"),                                    # too long
    "AAAAAAAAAA4": video_item("AAAAAAAAAA4", published="2025-01-01T10:00:00Z"),                   # out of period
    "AAAAAAAAAA5": video_item("AAAAAAAAAA5", title="ভোটের দিন সবাই আসুন", duration="PT15S"),      # candidate, no AI term
}
UPLOADS = [("AAAAAAAAAA1", "2025-12-01T10:00:00Z"), ("AAAAAAAAAA2", "2025-12-02T10:00:00Z"),
           ("AAAAAAAAAA3", "2025-12-03T10:00:00Z"), ("AAAAAAAAAA4", "2025-01-01T10:00:00Z"),
           ("AAAAAAAAAA5", "2026-02-12T17:00:00Z"),   # 23:00 Dhaka on polling day: in period
           ("GONEGONEGO6", "2025-12-05T10:00:00Z")]   # listed but details not returned


def fake_api(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.rsplit("/", 1)[-1]
        q = dict(request.url.params)
        calls.append(path)
        assert q["key"] == "test-key"
        if path == "videos":
            ids = q["id"].split(",")
            return httpx.Response(200, json={"items": [VIDEOS[i] for i in ids if i in VIDEOS]})
        if path == "channels":
            ch = {"id": "UC_one", "snippet": {"title": "Ai World", "publishedAt": "2025-05-01T00:00:00Z"},
                  "contentDetails": {"relatedPlaylists": {"uploads": "UU_one"}},
                  "statistics": {"subscriberCount": "1200"}}
            return httpx.Response(200, json={"items": [ch]})
        if path == "playlistItems":
            page = 1 if q.get("pageToken") is None else 2
            chunk = UPLOADS[:3] if page == 1 else UPLOADS[3:]
            body = {"items": [{"contentDetails": {"videoId": v, "videoPublishedAt": p}} for v, p in chunk]}
            if page == 1:
                body["nextPageToken"] = "p2"
            return httpx.Response(200, json=body)
        if path == "search":
            return httpx.Response(200, json={"items": [{"id": {"videoId": "AAAAAAAAAA5"}}],
                                             "pageInfo": {"totalResults": 1}})
        return httpx.Response(404)
    return handler


@pytest.fixture
def setup():
    calls = []
    client = YouTubeClient(api_key="test-key", transport=httpx.MockTransport(fake_api(calls)), sleep=lambda s: None)
    conn = db.connect(":memory:")
    return client, conn, calls


# --- pure functions ----------------------------------------------------------

def test_duration_parsing():
    assert parse_iso_duration("PT12S") == 12
    assert parse_iso_duration("PT1M5S") == 65
    assert parse_iso_duration("PT1H") == 3600
    assert parse_iso_duration("P1DT2S") == 86402
    assert parse_iso_duration("garbage") is None


def test_video_id_extraction():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtube.com/shorts/dQw4w9WgXcQ?feature=share") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("not a link") is None


def test_term_matching_bangla_and_latin():
    assert term_hits("নির্বাচনের আগে জনগণের মতামত", ["নির্বাচন", "মতামত"]) == ["নির্বাচন", "মতামত"]
    assert term_hits("he said hello", ["ai"]) == []          # no substring match inside words
    assert term_hits("Made with AI #Veo3", ["ai", "veo3"]) == ["ai", "veo3"]
    assert term_hits("নির্‌বাচন", ["নির্বাচন"]) == ["নির্বাচন"]   # zero-width joiner removed


def test_period_uses_bangladesh_time():
    p = CFG["study_period"]
    assert in_period("2026-02-12T17:00:00Z", p)      # 23:00 in Dhaka on polling day
    assert not in_period("2026-02-12T18:30:00Z", p)  # 00:30 on 13 Feb in Dhaka
    assert in_period("2025-06-14T19:00:00Z", p)      # 01:00 on 15 June in Dhaka


def test_prescreen_keeps_videos_without_ai_terms():
    row = {"title": "ভোটের দিন সবাই আসুন", "description": "", "tags_json": "[]",
           "duration_seconds": 15, "published_at": "2025-12-01T10:00:00Z"}
    result = prescreen_video(row, CFG)
    assert result["candidate"] and result["ai_hits"] == []


# --- API flows -----------------------------------------------------------------

def test_check_field_distinguishes_absent_from_false(setup):
    client, _, _ = setup
    res = {r["video_id"]: r for r in collect.check_synthetic_field(client, ["AAAAAAAAAA1", "AAAAAAAAAA2", "GONEGONEGO6"])}
    assert res["AAAAAAAAAA1"]["field_present"] and res["AAAAAAAAAA1"]["value"] is True
    assert res["AAAAAAAAAA2"]["field_present"] is False
    assert res["GONEGONEGO6"]["available"] is False


def test_seed_resolution_and_expansion(setup):
    client, conn, calls = setup
    channels = collect.resolve_seeds(client, conn, CFG, log=lambda m: None)
    assert channels == ["UC_one"]
    summary = collect.expand_channels(client, conn, CFG, channels, log=lambda m: None)
    s = summary["UC_one"]
    assert s["uploads_listed"] == 6 and s["in_period"] == 5 and s["details_returned"] == 4
    cands = {r["video_id"] for r in db.rows(conn, "SELECT video_id FROM prescreen WHERE candidate = 1")}
    assert cands == {"AAAAAAAAAA1", "AAAAAAAAAA2", "AAAAAAAAAA3", "AAAAAAAAAA5"}
    assert calls.count("playlistItems") == 2                     # pagination followed
    assert client.units_used == len(calls)                       # 1 unit per non-search call
    row = conn.execute("SELECT synthetic_field_present, contains_synthetic_media FROM videos WHERE video_id='AAAAAAAAAA2'").fetchone()
    assert tuple(row) == (0, None)                               # absent is stored as NULL, not False


def test_search_logs_every_call_and_counts_separately(setup):
    client, conn, _ = setup
    result = collect.run_search(client, conn, CFG, max_calls=3, log=lambda m: None)
    assert result["search_calls"] == 3
    assert conn.execute("SELECT COUNT(*) FROM search_log").fetchone()[0] == 3
    assert client.units_used == 4 and client.search_calls == 3 and client.general_calls == 1                      # 3 searches + 1 videos.list
    assert ("AAAAAAAAAA5", "search") in {(r[0], r[1]) for r in conn.execute("SELECT video_id, source FROM discovery")}


def test_month_windows_cover_period_without_gaps():
    w = collect.month_windows("2025-06-15", "2026-02-12")
    assert w[0][0] == "2025-06-14T18:00:00Z"
    assert w[-1][1] == "2026-02-12T18:00:00Z"
    assert all(a[1] == b[0] for a, b in zip(w, w[1:]))
    assert len(w) == 9


def test_quota_error_is_raised_cleanly():
    def handler(request):
        return httpx.Response(403, json={"error": {"message": "quota", "errors": [{"reason": "quotaExceeded"}]}})
    client = YouTubeClient(api_key="secret-key", transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(QuotaExceeded) as exc:
        client.videos(["AAAAAAAAAA1"])
    assert "secret-key" not in str(exc.value)


# --- Gemini --------------------------------------------------------------------

GOOD = {
    "election_related": "yes", "format": "street_interview", "genre": "persuasive",
    "has_interviewer": "yes", "news_branded_microphone": "yes", "microphone_brand_text": "Voice TV",
    "onscreen_captions": "no", "onscreen_ai_disclosure_text": None, "party_favoured": "BNP",
    "artifact_observations": [{"time": "00:04", "description": "fingers merge on microphone"}],
    "personas": [{"persona_id": 1, "start_time": "00:00", "end_time": "00:08", "apparent_gender": "male",
                  "apparent_age_group": "elderly", "visible_religious_markers": ["cap", "beard"],
                  "occupational_markers": ["rickshaw"], "setting": "urban", "visible_disability": "no",
                  "stated_identity": "রিকশাচালক", "transcript_bn": "আমি ধানের শীষে ভোট দিব",
                  "endorses_party": "BNP", "attacks": None, "issues_raised": [], "emotional_appeal": "hope",
                  "endorsement_voice": "personal"}],
    "notes": None,
}


def test_parse_output_accepts_fenced_json():
    parsed = gemini_screen.parse_output("```json\n" + json.dumps(GOOD, ensure_ascii=False) + "\n```")
    assert parsed.personas[0].occupational_markers == ["rickshaw"]


def test_parse_output_rejects_bad_enum():
    bad = dict(GOOD, election_related="maybe")
    with pytest.raises(Exception):
        gemini_screen.parse_output(json.dumps(bad))


class FakeInteractions:
    def __init__(self, outputs, reject_schema=False):
        self.outputs, self.reject_schema, self.requests = list(outputs), reject_schema, []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.reject_schema and "response_format" in kwargs:
            raise RuntimeError("400 INVALID_ARGUMENT: schema too complex")
        return SimpleNamespace(output_text=self.outputs.pop(0))


def test_screen_stores_results_and_falls_back_without_schema(setup):
    client, conn, _ = setup
    collect.expand_channels(client, conn, CFG, ["UC_one"], log=lambda m: None)
    fake = FakeInteractions([json.dumps(GOOD, ensure_ascii=False), "sorry, I cannot help"], reject_schema=True)
    ids = gemini_screen.pending_candidates(conn, "test-model", 2)
    assert len(ids) == 2
    result = gemini_screen.screen_videos(conn, CFG, ids, client=SimpleNamespace(interactions=fake),
                                         log=lambda m: None, sleep=lambda s: None)
    assert result == {"ok": 1, "failed": 1}
    first = fake.requests[0]
    assert first["input"][1] == {"type": "video", "uri": f"https://www.youtube.com/watch?v={ids[0]}"}
    assert "response_format" not in fake.requests[1]               # fallback request
    assert len(gemini_screen.pending_candidates(conn, "test-model", 10)) == 3   # failed one stays pending


