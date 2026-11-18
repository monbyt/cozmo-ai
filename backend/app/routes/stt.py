"""Speech-to-text proxy. Takes an audio blob from the browser, sends it to Gemini
audio transcription, returns {text}. Keeps the frontend dumb and the API key server-side."""
from __future__ import annotations
import logging
from fastapi import APIRouter, UploadFile, File, HTTPException

from google import genai
from google.genai import types

from ..config import get_settings

log = logging.getLogger(__name__)
router = APIRouter()

TRANSCRIBE_PROMPT = (
    "Transcribe this audio verbatim into plain text, in the language spoken. "
    "Output only the transcript. Empty string if no speech is audible."
)


@router.post("/stt")
async def stt(audio: UploadFile = File(...)) -> dict[str, str]:
    s = get_settings()
    if not s.gemini_api_key:
        raise HTTPException(500, "GEMINI_API_KEY not set")
    data = await audio.read()
    if len(data) < 500:
        return {"text": ""}
    mime = audio.content_type or "audio/webm"
    try:
        client = genai.Client(api_key=s.gemini_api_key)
        resp = client.models.generate_content(
            model=s.gemini_agent_model,
            contents=[
                types.Part.from_bytes(data=data, mime_type=mime),
                TRANSCRIBE_PROMPT,
            ],
            config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=200),
        )
        return {"text": (resp.text or "").strip()}
    except Exception as e:
        log.warning("stt failed: %s", e)
        return {"text": ""}
