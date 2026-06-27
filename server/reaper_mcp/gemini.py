"""Gemini audio-critique client for the Reaper MCP server.

Borrowed wholesale from abletest/abletonosc_cli/gemini.py (only the system
prompt's DAW name is changed). Sends rendered audio to Gemini's native
audio-understanding models so the agent can "hear" and critique its own work.

Verified facts (carried over from the source module):
- Endpoint: POST /v1beta/models/{model}:generateContent, key in x-goog-api-key.
- Audio is sent inline as base64 ``inline_data`` (fine for clip/section renders,
  well under the 20 MB inline limit); ~32 audio tokens/sec.
- DEFAULT model is ``gemini-3.5-flash`` (NOT lite): in a calibration test it
  correctly identified a 440 Hz/A4 tone using its thinking budget, while
  ``gemini-3.1-flash-lite`` got it wrong by an octave + semitone. Lite is fine
  for *qualitative* feedback only and is offered as a cheaper --model.
- ``gemini-3.5-flash`` can return transient HTTP 503 "high demand"; we retry
  with backoff.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
from typing import Optional

import requests

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-3.5-flash"          # primary: accurate, reasons over audio
FAST_MODEL = "gemini-3.1-flash-lite"        # cheaper; qualitative feedback only
INLINE_LIMIT_BYTES = 20 * 1024 * 1024       # 20 MB inline ceiling

# What we ask for: a music-production critique as structured JSON the agent can
# act on (drive fx / track changes / note edits) rather than prose.
SYSTEM_PROMPT = (
    "You are a meticulous music producer and mix engineer reviewing a short "
    "excerpt of a work-in-progress track produced in the REAPER DAW. Listen to "
    "the AUDIO and give concrete, actionable feedback an automated agent can "
    "apply. Be specific about frequencies, instruments, timing, and arrangement. "
    "If you are unsure about exact pitch/tuning, say so rather than guessing.\n\n"
    "Respond with ONLY a JSON object (no markdown fence) of this shape:\n"
    "{\n"
    '  "overall": "<one-sentence verdict>",\n'
    '  "severity": "minor" | "moderate" | "significant",\n'
    '  "what_works": ["..."],\n'
    '  "mix_issues": ["..."],\n'
    '  "arrangement_notes": ["..."],\n'
    '  "tuning_timing": ["..."],\n'
    '  "suggestions": [{"change": "...", "how": "<e.g. eq cut low-mids on track '
    '1, lower track 2 volume, quantize hats>"}]\n'
    "}\n"
    "Keep each list to the few most important items. If the audio is silent or "
    'unintelligible, set overall to say so and leave the lists empty.'
)


class GeminiError(Exception):
    """Raised for config/transport/parse problems."""


def _load_dotenv_key() -> Optional[str]:
    """Read GEMINI_API_KEY from a .env in the cwd or repo root (no dependency).

    Only fills in the key if it isn't already set in the environment.
    """
    here = os.path.abspath(os.path.dirname(__file__))
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(here), ".env"),       # server/ dir
        os.path.join(os.path.dirname(os.path.dirname(here)), ".env"),  # repo root
    ]
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    name, _, val = line.partition("=")
                    if name.strip() == "GEMINI_API_KEY":
                        return val.strip().strip('"').strip("'")
        except OSError:
            continue
    return None


def get_api_key(explicit: Optional[str] = None) -> str:
    key = explicit or os.environ.get("GEMINI_API_KEY") or _load_dotenv_key()
    if not key:
        raise GeminiError(
            "no Gemini API key: set GEMINI_API_KEY (e.g. in .env) or pass --api-key"
        )
    return key


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    if mime and mime.startswith("audio/"):
        return mime
    # mimetypes is spotty on some audio types; map by extension.
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return {
        "wav": "audio/wav", "mp3": "audio/mp3", "flac": "audio/flac",
        "aac": "audio/aac", "ogg": "audio/ogg", "aiff": "audio/aiff",
        "aif": "audio/aiff", "m4a": "audio/aac",
    }.get(ext, "audio/wav")


def _request(model: str, key: str, body: dict, *, timeout: float,
             retries: int) -> dict:
    """POST to :generateContent with backoff on transient 429/503."""
    url = "%s/%s:generateContent" % (API_BASE, model)
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}
    delay = 4.0
    last_err = None
    for attempt in range(retries + 1):
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        last_err = "HTTP %d: %s" % (resp.status_code, resp.text[:300])
        # 429 rate-limit / 503 high-demand are transient; retry with backoff.
        if resp.status_code in (429, 503) and attempt < retries:
            time.sleep(delay)
            delay *= 1.7
            continue
        break
    raise GeminiError("Gemini request failed: %s" % last_err)


def _extract_text(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError):
        raise GeminiError("unexpected Gemini response: %s"
                          % json.dumps(data)[:300])
    # The model may emit a thought part then a text part; take the last text.
    texts = [p["text"] for p in parts if "text" in p]
    if not texts:
        raise GeminiError("no text in Gemini response")
    return texts[-1]


def _parse_json_maybe(text: str):
    """Best-effort: strip a markdown fence and parse JSON; else return raw text."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.lstrip().startswith("json"):
            s = s.lstrip()[4:]
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def critique_audio(
    audio_path: str,
    *,
    ask: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
    timeout: float = 120.0,
    retries: int = 3,
) -> dict:
    """Send an audio file to Gemini and return a structured critique.

    Without ``ask`` it returns the full structured-JSON critique. With ``ask`` it
    answers a specific question (free-form text) about the audio instead.
    """
    key = get_api_key(api_key)
    if not os.path.exists(audio_path):
        raise GeminiError("audio file not found: %s" % audio_path)
    size = os.path.getsize(audio_path)
    if size > INLINE_LIMIT_BYTES:
        raise GeminiError(
            "audio is %.1f MB, over the %d MB inline limit; capture a shorter "
            "section (File API upload is not implemented yet)"
            % (size / 1e6, INLINE_LIMIT_BYTES // (1024 * 1024))
        )

    with open(audio_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    mime = _guess_mime(audio_path)

    if ask:
        prompt = ask
    else:
        prompt = SYSTEM_PROMPT

    body = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": mime, "data": b64}},
            ]
        }]
    }

    data = _request(model, key, body, timeout=timeout, retries=retries)
    text = _extract_text(data)
    usage = data.get("usageMetadata", {})

    result = {
        "ok": True,
        "model": data.get("modelVersion", model),
        "audio": audio_path,
        "tokens": usage.get("totalTokenCount"),
    }
    if ask:
        result["question"] = ask
        result["answer"] = text
    else:
        parsed = _parse_json_maybe(text)
        if parsed is not None:
            result["critique"] = parsed
        else:
            # Model didn't return clean JSON; hand back the prose so it's not lost.
            result["critique_text"] = text
    return result
