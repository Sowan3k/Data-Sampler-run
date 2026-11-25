"""AI-assisted screening of candidate videos with Gemini (YouTube URL input).

The model drafts observations against the codebook. Its output is a screening
aid only: it never sets the evidence level, never decides inclusion, and must
not be shown to coders doing the reliability subsample.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from . import db

UNCLEAR = "unclear"

PROMPT_TEMPLATE = """You are assisting an academic content analysis of YouTube videos from Bangladesh's
February 2026 parliamentary election campaign. Watch and listen to the whole video.

Rules:
- Report only what is observable in the video or audible in speech. Do not guess.
- Use "unclear" when you are not sure. Use null for text fields with nothing to report.
- Do NOT decide whether any person is AI-generated. Only list concrete visual or audio
  artifacts you can point to, each with an MM:SS timestamp.
- Religion: record only visible markers (cap, beard, hijab, sindoor, tilak and so on) or a
  religion the person states in speech. Never infer religion from a name.
- Party: distinguish a mention from endorsement or criticism. A name or symbol alone does not imply support. Set party_favoured and endorses_party to null if no explicit support.
  Symbol hints (verify on screen): {symbols}
- Transcribe each persona's speech in Bangla script as spoken, including dialect.
- A persona is any individual person who appears and speaks or is interviewed.

Return one JSON object that follows the provided schema."""

ENUM_YNU = ["yes", "no", UNCLEAR]

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "election_related": {"type": "string", "enum": ENUM_YNU},
        "format": {"type": "string", "enum": [
            "street_interview", "single_testimonial", "montage_of_testimonials", "drama_or_skit",
            "news_style_report", "song_or_music", "speech_or_rally", "other", UNCLEAR]},
        "genre": {"type": "string", "enum": ["persuasive", "satirical_or_comedy", UNCLEAR]},
        "has_interviewer": {"type": "string", "enum": ENUM_YNU},
        "news_branded_microphone": {"type": "string", "enum": ENUM_YNU},
        "microphone_brand_text": {"type": ["string", "null"]},
        "onscreen_captions": {"type": "string", "enum": ENUM_YNU},
        "onscreen_ai_disclosure_text": {"type": ["string", "null"]},
        "party_favoured": {"type": ["string", "null"]},
        "artifact_observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"time": {"type": "string"}, "description": {"type": "string"}},
                "required": ["time", "description"],
            },
        },
        "personas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "persona_id": {"type": "integer"},
                    "start_time": {"type": ["string", "null"]},
                    "end_time": {"type": ["string", "null"]},
                    "apparent_gender": {"type": "string", "enum": ["male", "female", UNCLEAR]},
                    "apparent_age_group": {"type": "string", "enum": [
                        "child", "young_adult", "middle_aged", "elderly", UNCLEAR]},
                    "visible_religious_markers": {"type": "array", "items": {"type": "string"}},
                    "occupational_markers": {"type": "array", "items": {"type": "string"}},
                    "setting": {"type": "string", "enum": ["rural", "urban", UNCLEAR]},
                    "visible_disability": {"type": "string", "enum": ENUM_YNU},
                    "stated_identity": {"type": ["string", "null"]},
                    "transcript_bn": {"type": ["string", "null"]},
                    "endorses_party": {"type": ["string", "null"]},
                    "attacks": {"type": ["string", "null"]},
                    "issues_raised": {"type": "array", "items": {"type": "string"}},
                    "emotional_appeal": {"type": "string", "enum": [
                        "none", "fear", "anger", "hope", "pride", "humour", "grievance", "other"]},
                    "endorsement_voice": {"type": "string", "enum": ["personal", "collective", "none"]},
                },
                "required": ["persona_id", "apparent_gender", "apparent_age_group", "transcript_bn",
                             "endorses_party", "endorsement_voice"],
            },
        },
        "notes": {"type": ["string", "null"]},
    },
    "required": ["election_related", "format", "genre", "personas", "artifact_observations"],
}


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona_id: int
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    apparent_gender: Literal["male", "female", "unclear"] = UNCLEAR
    apparent_age_group: Literal["child", "young_adult", "middle_aged", "elderly", "unclear"] = UNCLEAR
    visible_religious_markers: list[str] = []
    occupational_markers: list[str] = []
    setting: Literal["rural", "urban", "unclear"] = UNCLEAR
    visible_disability: Literal["yes", "no", "unclear"] = UNCLEAR
    stated_identity: Optional[str] = None
    transcript_bn: Optional[str] = None
    endorses_party: Optional[str] = None
    attacks: Optional[str] = None
    issues_raised: list[str] = []
    emotional_appeal: Literal["none", "fear", "anger", "hope", "pride", "humour", "grievance", "other"] = "none"
    endorsement_voice: Literal["personal", "collective", "none"] = "none"


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    time: str
    description: str


class VideoScreen(BaseModel):
    model_config = ConfigDict(extra="forbid")
    election_related: Literal["yes", "no", "unclear"]
    format: Literal["street_interview", "single_testimonial", "montage_of_testimonials", "drama_or_skit", "news_style_report", "song_or_music", "speech_or_rally", "other", "unclear"]
    genre: Literal["persuasive", "satirical_or_comedy", "unclear"]
    has_interviewer: Literal["yes", "no", "unclear"] = UNCLEAR
    news_branded_microphone: Literal["yes", "no", "unclear"] = UNCLEAR
    microphone_brand_text: Optional[str] = None
    onscreen_captions: Literal["yes", "no", "unclear"] = UNCLEAR
    onscreen_ai_disclosure_text: Optional[str] = None
    party_favoured: Optional[str] = None
    artifact_observations: list[Artifact] = []
    personas: list[Persona] = []
    notes: Optional[str] = None


_SECRET = re.compile(r'AIza[0-9A-Za-z_-]{20,}|(?i:key=)[^&\s"\']+')


def redact(text: str) -> str:
    """Remove anything that looks like an API key from an error message."""
    return _SECRET.sub("[redacted]", text)


def build_prompt(cfg: dict[str, Any]) -> str:
    symbols = cfg.get("gemini", {}).get("party_symbols", {}) or {}
    hint = "; ".join(f"{k} = {v}" for k, v in symbols.items()) or "none provided"
    return PROMPT_TEMPLATE.format(symbols=hint)


def parse_output(text: str, duration: int | None = None) -> VideoScreen:
    """Parse model text into a validated VideoScreen. Tolerates code fences."""
    cleaned = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.S)
    if fence:
        cleaned = fence.group(1)
    if not cleaned.startswith("{"):
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON object in model output")
        cleaned = cleaned[start:end + 1]
    result = VideoScreen.model_validate(json.loads(cleaned))
    def seconds(t):
        # Accepts M:SS, MM:SS, H:MM:SS and fractional seconds (Gemini writes all of these).
        if t is None: return None
        m = re.fullmatch(r"(\d+):([0-5]\d)(?::([0-5]\d))?(?:\.\d+)?", str(t).strip())
        if not m: raise ValueError(f"Invalid timestamp {t!r}")
        a, b, c = m.groups()
        n = int(a)*3600 + int(b)*60 + int(c) if c is not None else int(a)*60 + int(b)
        # one second of tolerance for rounding at the end of a clip
        if duration is not None and n > duration + 1: raise ValueError(f"Timestamp {t} beyond duration {duration}s")
        return n
    ids = set()
    for p in result.personas:
        if p.persona_id < 1 or p.persona_id in ids: raise ValueError("Invalid or repeated persona ID")
        ids.add(p.persona_id)
        a,b = seconds(p.start_time),seconds(p.end_time)
        if a is not None and b is not None and a>b: raise ValueError("Reversed persona interval")
    for a in result.artifact_observations: seconds(a.time)
    return result


def call_gemini(client: Any, model: str, prompt: str, url: str) -> str:
    """One request per video. Tries schema-enforced JSON first, then plain text."""
    content = [{"type": "text", "text": prompt}, {"type": "video", "uri": url}]
    try:
        interaction = client.interactions.create(
            model=model,
            input=content,
            response_format={"type": "text", "mime_type": "application/json", "schema": RESPONSE_SCHEMA},
        )
    except Exception as exc:  # schema rejected or param unsupported: fall back
        if "INVALID_ARGUMENT" not in str(exc) and "response_format" not in str(exc):
            raise
        interaction = client.interactions.create(model=model, input=content)
    return interaction.output_text or ""


def pending_candidates(conn: sqlite3.Connection, model: str, limit: int) -> list[str]:
    return [r["video_id"] for r in db.rows(conn, """
        SELECT p.video_id FROM prescreen p
        JOIN videos v ON v.video_id = p.video_id
        WHERE p.candidate = 1
          AND v.privacy_status = 'public'
          AND p.video_id NOT IN (SELECT video_id FROM gemini_screens WHERE model = ? AND parsed_ok = 1)
        ORDER BY v.published_at
        LIMIT ?""", (model, limit))]


def screen_videos(conn: sqlite3.Connection, cfg: dict[str, Any], video_ids: list[str],
                  client: Any = None, log=print, sleep=time.sleep) -> dict[str, int]:
    model = cfg["gemini"]["model"]
    if client is None:
        from google import genai  # imported lazily so tests run without a key
        client = genai.Client()
    prompt = build_prompt(cfg)
    ok = failed = 0
    for index, vid in enumerate(video_ids):
        url = f"https://www.youtube.com/watch?v={vid}"
        raw, parsed, error = None, None, None
        try:
            raw = call_gemini(client, model, prompt, url)
            parsed = parse_output(raw)
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            error = f"parse: {exc}"[:2000]
        except Exception as exc:  # network, quota, unsupported video
            error = f"call: {type(exc).__name__}: {redact(str(exc))}"[:2000]
        conn.execute(
            """INSERT INTO gemini_screens (video_id, model, run_at, parsed_ok, output_json, raw_text, error)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (vid, model, db.utcnow(), int(parsed is not None),
             parsed.model_dump_json() if parsed else None, raw, error),
        )
        conn.commit()
        if parsed:
            ok += 1
            log(f"  {vid}: {parsed.format}, {len(parsed.personas)} persona(s), genre {parsed.genre}")
        else:
            failed += 1
            log(f"  {vid}: FAILED ({error})")
        if index < len(video_ids) - 1:
            sleep(float(cfg["gemini"].get("seconds_between_calls", 4)))
    return {"ok": ok, "failed": failed}
