"""Voice-agent turn controller. Local STT/TTS on the phone; the LLM runs here.

Strict constraints:
- Reply length: <= 2 sentences, under 180 chars
- Never state a price, never 'identify' a book — those come from the vision/pricing pipeline
- If the user said something off-topic, return an empty reply ('')
"""
from __future__ import annotations
import logging
from google import genai
from google.genai import types

from ..config import get_settings

log = logging.getLogger(__name__)

SYSTEM = (
    "You are a live voice assistant guiding a one-sweep home-library inventory. "
    "You are listening while the policyholder walks the room. "
    "Keep every reply to 1 short sentence, under 25 words. "
    "You MUST NOT state prices or dollar amounts. "
    "You MUST NOT name a book unless the user already named it. "
    "You MUST NOT make any statement about insurance coverage, policy limits, exclusions, deductibles, "
    "claim approval, or what will or won't be reimbursed. For any policy question, say exactly: "
    "'I can't speak to policy details — your adjuster will go through the packet with you.' "
    "You acknowledge corrections ('skip that shelf', 'that's a first edition', 'it's a print') in one friendly line. "
    "You give capture hints only when the recent_notes mention blur_high or glare_high. "
    "If the user said nothing worth responding to, reply with an empty string. "
    "Do not say 'as an AI'. Do not restate the task."
)


def build_prompt(user_text: str, recent_notes: list[str], books_so_far: int, items_so_far: int) -> str:
    notes = ", ".join(recent_notes) if recent_notes else "none"
    return (
        f"State: {books_so_far} books logged, {items_so_far} items. "
        f"Recent capture notes: {notes}. "
        f'User just said: "{user_text}". '
        "Reply in one short sentence, or empty string."
    )


class AgentService:
    def __init__(self):
        s = get_settings()
        self._key = s.gemini_api_key
        self._model = s.gemini_agent_model
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            if not self._key:
                raise RuntimeError("GEMINI_API_KEY not set")
            self._client = genai.Client(api_key=self._key)
        return self._client

    def turn(self, user_text: str, recent_notes: list[str],
             books_so_far: int, items_so_far: int) -> str:
        if not user_text.strip():
            return ""
        try:
            resp = self.client.models.generate_content(
                model=self._model,
                contents=build_prompt(user_text, recent_notes, books_so_far, items_so_far),
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM,
                    temperature=0.3,
                    max_output_tokens=80,
                ),
            )
            text = (resp.text or "").strip().strip('"').strip()
            # Truncate hard — some models over-generate
            if len(text) > 200:
                text = text[:200].rsplit(" ", 1)[0] + "…"
            return text
        except Exception as e:
            log.warning("agent turn failed: %s", e)
            return ""
