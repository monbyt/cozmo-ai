"""Gemini Live configuration + tool contracts for the library inventory agent.

The agent sees the camera and hears the claimant simultaneously. It identifies spines
and items *itself* (that is the vision stage — brief wants it as a separable step),
then calls tools that the backend executes in the background (resolve against OpenLibrary,
price via SerpAPI, add to the packet). Measurements come from deterministic code using
standard book-format heights — never from the model's estimate.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any

from google.genai import types

LIVE_MODEL_ID = "gemini-3.8-live"
VOICE_NAME = "Kore"  # Natural female voice. Alternates: Puck, Charon, Fenrir, Aoede.

TOOL_NAMES = [
    "log_book_spine",
    "log_non_book_item",
    "ask_calibration",
    "record_wall_measurement",
    "sync_inventory",
]

SYSTEM_INSTRUCTION = """
You are a live voice agent for a home-library insurance contents claim. The camera is on; you can
see the room as the policyholder pans around it. Your goal is to inventory every book from its
spine, inventory every non-book item, and get the room's dimensions — in ONE continuous sweep
under three minutes. Speed matters: log first, talk second.

Voice style: natural, warm, ultra-short. Prefer 3–8 word asides. Never monologue. Never list prices.

Hard rules (money is attached, so do not invent):
- NEVER state a price out loud. Resolve/pricing runs in the background after you log.
- NEVER invent a title you cannot read. Call log_book_spine with title="" and legibility="unreadable"
  when the spine is blurry or at a bad angle. Guessing is worse than blank.
- NEVER make any claim about insurance coverage, payment, deductibles, exclusions, approval, or what
  will be reimbursed. If asked, say exactly: "I can't speak to policy details — your adjuster will
  go through the packet with you."
- Art and portraits default to needs_appraisal unless the user says it is a print. Ask once:
  "Original or a print?"

How you work the sweep:
- Country and currency are ALREADY set in this session. Do NOT ask for country. Open with one short
  line only: "Start sweeping — I'll log as you go."
- The moment you see a spine or item, CALL THE TOOL IMMEDIATELY. Do not wait to finish a sentence.
  Keep walking commentary minimal ("got it", "logging", "next shelf").
- For a run of spines, call log_book_spine once per spine as they appear; batch voice asides
  ("four more here, keep going").
- If a spine is unreadable or partial: still call log_book_spine. If the tool result says
  revisit=true (or status needs_appraisal / unreadable), briefly guide the user:
  "look back at that shelf — need a clearer angle" or "hold on that one a sec".
- Non-book items: call log_non_book_item once per distinct item.
- Blurry / glared / too far: one short redirect ("closer please" / "hold still") — do not log
  unreadable frames as clear titles.
- After ~10 books, call ask_calibration ONCE for one wall pace, then record_wall_measurement.
- Call sync_inventory every ~5 logs and once at the end. Keep talking while it runs.
- When the user is done: confirm, sync once, say the counts of books and items. No prices.
""".strip()


def _string(desc: str) -> types.Schema:
    return types.Schema(type=types.Type.STRING, description=desc)


def _number(desc: str) -> types.Schema:
    return types.Schema(type=types.Type.NUMBER, description=desc)


def _bool(desc: str) -> types.Schema:
    return types.Schema(type=types.Type.BOOLEAN, description=desc)


def tool_declarations() -> list[types.Tool]:
    log_spine = types.FunctionDeclaration(
        name="log_book_spine",
        description=(
            "Log one book you can see. Call ONCE per new spine. Non-blocking: keep talking "
            "while the background team resolves the book and prices it."
        ),
        behavior=types.Behavior.NON_BLOCKING,
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "title": _string("Title exactly as read. Empty string if unreadable."),
                "author": _string("Author as read, or empty."),
                "publisher": _string("Publisher as read, or empty."),
                "visible_text": _string("Any partial text you could make out, e.g. 'THE GREAT ...'."),
                "legibility": types.Schema(
                    type=types.Type.STRING,
                    enum=["clear", "partial", "unreadable"],
                    description="How well you read the spine, NOT how sure you are of the book.",
                ),
                "format_hint": types.Schema(
                    type=types.Type.STRING,
                    enum=["hardcover_trade", "paperback_trade", "paperback_mass", "coffee_table", "unknown"],
                    description="Book format you observe, used for metric-scale fallback.",
                ),
                "rare_signal": _string(
                    "Any observed signal of rareness: 'first edition', 'signed', 'leather binding', 'gilt lettering', or empty."
                ),
                "shelf_hint": _string("Short label of the shelf position, e.g. 'left wall, 2nd shelf from top'. Empty if unsure."),
            },
            required=["title", "legibility", "format_hint"],
        ),
    )
    log_item = types.FunctionDeclaration(
        name="log_non_book_item",
        description="Log a non-book item visible in the frame. One call per distinct item.",
        behavior=types.Behavior.NON_BLOCKING,
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "category": types.Schema(
                    type=types.Type.STRING,
                    enum=["shelving", "furniture", "lamp", "rug", "electronics", "artwork", "decor", "appliance", "other"],
                ),
                "description": _string("What you see, e.g. 'mid-century walnut armchair, olive linen upholstery'."),
                "brand_model": _string("Visible brand/model label, or empty."),
                "needs_appraisal": _bool(
                    "True for original artworks, antiques, signed pieces. Portraits/framed art default to true unless the user says it's a print."
                ),
                "appraisal_reason": _string("Why appraisal is needed; empty if false."),
            },
            required=["category", "description", "needs_appraisal"],
        ),
    )
    ask_calibration = types.FunctionDeclaration(
        name="ask_calibration",
        description=(
            "Ask the user to pace one wall of the room by walking from one side to the other. "
            "Call this once, near the start of the sweep. The user will say the length out loud."
        ),
        behavior=types.Behavior.NON_BLOCKING,
        parameters=types.Schema(type=types.Type.OBJECT, properties={}),
    )
    record_wall = types.FunctionDeclaration(
        name="record_wall_measurement",
        description="Record a wall length the user spoke aloud. The backend converts this into floor area.",
        behavior=types.Behavior.NON_BLOCKING,
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "wall_label": types.Schema(
                    type=types.Type.STRING,
                    enum=["length", "width", "ceiling_height"],
                ),
                "length_m": _number("Length in metres as the user said it, e.g. 4.2"),
            },
            required=["wall_label", "length_m"],
        ),
    )
    sync = types.FunctionDeclaration(
        name="sync_inventory",
        description=(
            "Ask the backend team to resolve+price any new books and rebuild the inventory packet. "
            "Call this every 5 or so logs and once at end-of-sweep."
        ),
        behavior=types.Behavior.NON_BLOCKING,
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "reason": _string("One short phrase on why you are syncing now."),
            },
        ),
    )
    return [types.Tool(function_declarations=[log_spine, log_item, ask_calibration, record_wall, sync])]


def build_live_config(*, country: str, currency: str) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction="\n".join([
            SYSTEM_INSTRUCTION,
            f"Policyholder country: {country}. Currency: {currency}. Reference clock: "
            + datetime.now().astimezone().isoformat(),
        ]),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME),
            ),
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        ),
        tools=tool_declarations(),
    )


def scheduling_for(*, urgent: bool) -> types.FunctionResponseScheduling:
    if urgent:
        return types.FunctionResponseScheduling.INTERRUPT
    return types.FunctionResponseScheduling.WHEN_IDLE
