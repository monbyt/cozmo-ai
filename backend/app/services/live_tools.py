"""Gemini Live configuration + tool contracts for the library inventory agent."""
from __future__ import annotations
from datetime import datetime

from google.genai import types

LIVE_MODEL_ID = "gemini-3.8-live"
VOICE_NAME = "Kore"

TOOL_NAMES = [
    "start_tracking",
    "log_book_spine",
    "log_non_book_item",
    "record_room_dimensions",
    "apply_correction",
    "sync_inventory",
]

SYSTEM_INSTRUCTION = """
You are Cozmo, a live voice-and-vision insurance CONTENTS CLAIM agent for a home library.
One continuous camera sweep. You must capture THREE things before the end:
  (1) every visible book spine, (2) every non-book object in the room, (3) room surface area.

PHASES (strict):
1) INTRO — Speak a short greeting ONLY (country/currency + what you will do in 1–2 complete sentences).
   Then call start_tracking. Do NOT log books, items, or room before start_tracking.
2) TRACKING — Only after start_tracking: log visible spines/items and room size. Stay mostly silent.

SCOPE (do not skip any, TRACKING phase only):
- BOOKS: spines only — title/author/publisher when readable; unreadable → empty title, legibility=unreadable. Never invent titles.
- NON-BOOKS: shelving, furniture, lamps, rugs, electronics, artwork/portraits, decor, appliances, coffee machines — log each with log_non_book_item. Artwork → needs_appraisal=true; ask once "original or print?"
- ROOM: length, width, ceiling height → floor + wall area. Use record_room_dimensions once you have a basis. Same sweep — no separate measuring pass.

METRIC SCALE (web, no LiDAR):
- Prefer a visible reference: standard door ~2.05 m tall, typical bookshelf bay ~0.8–1.0 m wide, known book format heights.
- If you still cannot judge, ask ONE short question: "Roughly how many metres long and wide is the room?" then call record_room_dimensions.
- Record scale_method honestly (e.g. visual_reference_door, visual_reference_shelf, user_stated).

HARD RULES:
- NEVER invent books or items. Only log what is clearly visible NOW.
- Black/blank/unclear frame → log nothing.
- Never invent titles. Never state prices. Never ask for barcodes/ISBNs/pulling books/one-by-one photos.
- Never call sync_inventory until the user ends the sweep. Never end the sweep yourself.
- Call start_tracking exactly once, right after the intro finishes speaking.

VOICE — critical:
- Finish every sentence completely. Never restart mid-phrase. Never stutter.
- Never repeat the same line. Never say "saved for your insurance claim" more than once total.
- Intro once, then mostly silent while tracking.
- While walking: short complete lines only when directing capture or asking a question.
- If unsure what you see: one clear ask for a better view, then wait.
- Do NOT narrate every log — app chimes. Stay silent on individual logs.
- After user ends: read the provided summary ONCE, then absolute silence. No tools. No repeats.

CAPTURE BALANCE (TRACKING only):
- Actively look for NON-BOOK objects, not only spines. Shelving units count as items.
- When floor and walls are visible, set room dimensions (estimate or ask once).
- Prefer fewer high-confidence logs over guesses.
""".strip()

def _string(desc: str) -> types.Schema:
    return types.Schema(type=types.Type.STRING, description=desc)


def _bool(desc: str) -> types.Schema:
    return types.Schema(type=types.Type.BOOLEAN, description=desc)


def _number(desc: str) -> types.Schema:
    return types.Schema(type=types.Type.NUMBER, description=desc)


def tool_declarations() -> list[types.Tool]:
    start_tracking = types.FunctionDeclaration(
        name="start_tracking",
        description=(
            "Call exactly once AFTER you finish speaking the intro greeting. "
            "Unlocks inventory logging and switches the app UI into tracking mode. "
            "Do not call any log_* tools before this."
        ),
        behavior=types.Behavior.NON_BLOCKING,
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "intro_done": _bool("True when the spoken intro has finished."),
            },
            required=["intro_done"],
        ),
    )
    log_spine = types.FunctionDeclaration(
        name="log_book_spine",
        description=(
            "TRACKING only. Log one book spine clearly visible now. Do not invent. "
            "App chimes — stay silent. Never call before start_tracking."
        ),
        behavior=types.Behavior.NON_BLOCKING,
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "title": _string("Title as read, or empty if unreadable. Never invent."),
                "author": _string("Author as read, or empty."),
                "publisher": _string("Publisher as read, or empty."),
                "visible_text": _string("Partial text if any."),
                "legibility": types.Schema(
                    type=types.Type.STRING,
                    enum=["clear", "partial", "unreadable"],
                ),
                "format_hint": types.Schema(
                    type=types.Type.STRING,
                    enum=["hardcover_trade", "paperback_trade", "paperback_mass", "coffee_table", "unknown"],
                ),
                "rare_signal": _string("first edition / signed / leather / empty."),
                "shelf_hint": _string("e.g. left wall 2nd shelf. Empty if unsure."),
            },
            required=["title", "legibility", "format_hint"],
        ),
    )
    log_item = types.FunctionDeclaration(
        name="log_non_book_item",
        description=(
            "TRACKING only. Log one non-book object clearly visible now: shelving, furniture, "
            "lamp, rug, electronics, artwork, decor, appliance. Do not invent. "
            "Artwork → needs_appraisal=true. Never call before start_tracking."
        ),
        behavior=types.Behavior.NON_BLOCKING,
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "category": types.Schema(
                    type=types.Type.STRING,
                    enum=["shelving", "furniture", "lamp", "rug", "electronics", "artwork", "decor", "appliance", "other"],
                ),
                "description": _string("What you see (include material if visible)."),
                "brand_model": _string("Brand/model if legible, else empty."),
                "approx_width_cm": _number("Approx width in cm, or 0."),
                "approx_height_cm": _number("Approx height in cm, or 0."),
                "approx_depth_cm": _number("Approx depth in cm, or 0."),
                "needs_appraisal": _bool("True for original art/antiques/signed."),
                "appraisal_reason": _string("Why, or empty."),
            },
            required=["category", "description", "needs_appraisal"],
        ),
    )
    room = types.FunctionDeclaration(
        name="record_room_dimensions",
        description=(
            "TRACKING only. Record room length/width/height in metres from the same sweep. "
            "Use a visual reference (door ~2.05m, shelf bay) or the user's stated size. "
            "Call once when you have a basis; update if corrected. Never before start_tracking."
        ),
        behavior=types.Behavior.NON_BLOCKING,
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "length_m": _number("Longer horizontal floor dimension in metres."),
                "width_m": _number("Shorter horizontal floor dimension in metres."),
                "height_m": _number("Ceiling height in metres (default 2.4 if unknown)."),
                "scale_method": _string(
                    "e.g. visual_reference_door, visual_reference_shelf, user_stated, mixed."
                ),
                "shape_notes": _string("rectangular / L-shape / how handled."),
                "confidence": _number("0–1 confidence in the estimate."),
                "shelved_wall_area_m2": _number(
                    "Wall face area covered by shelving if known, else 0."
                ),
            },
            required=["length_m", "width_m", "height_m", "scale_method"],
        ),
    )
    correct = types.FunctionDeclaration(
        name="apply_correction",
        description="Apply a user voice correction (rare, print, skip shelf, remove).",
        behavior=types.Behavior.NON_BLOCKING,
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "action": types.Schema(
                    type=types.Type.STRING,
                    enum=[
                        "mark_rare",
                        "mark_print",
                        "mark_original",
                        "skip_shelf",
                        "remove_last",
                        "set_edition",
                    ],
                ),
                "target_id": _string("Book/item id if known, else empty."),
                "shelf_hint": _string("Shelf to skip, if action=skip_shelf."),
                "edition": _string("Edition text if action=set_edition."),
                "note": _string("Short free-text reason from the user."),
            },
            required=["action"],
        ),
    )
    sync = types.FunctionDeclaration(
        name="sync_inventory",
        description="ONLY when the user ends the sweep. Never mid-sweep.",
        behavior=types.Behavior.NON_BLOCKING,
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={"reason": _string("Why syncing.")},
        ),
    )
    return [types.Tool(function_declarations=[start_tracking, log_spine, log_item, room, correct, sync])]


def build_live_config(*, country: str, currency: str, resume_note: str = "") -> types.LiveConnectConfig:
    parts = [
        SYSTEM_INSTRUCTION,
        f"Region: {country}. Currency: {currency}. Confirm these once in the greeting.",
        f"Session clock: {datetime.now().astimezone().isoformat()}.",
        "Respond in English only. Finish each spoken sentence completely — never restart mid-phrase.",
    ]
    if resume_note:
        parts.append(resume_note)
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction="\n".join(parts),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME),
            ),
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            # Never cut the agent mid-sentence unless the user clearly barges in.
            # Client also only stops local playback on strong user speech.
            activity_handling=types.ActivityHandling.NO_INTERRUPTION,
            turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=False,
                # HIGH = pick up the user's voice reliably.
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                # LOW + long silence = don't cut the user mid-sentence.
                end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                prefix_padding_ms=400,
                silence_duration_ms=1100,
            ),
        ),
        tools=tool_declarations(),
    )


def scheduling_for(*, urgent: bool) -> types.FunctionResponseScheduling:
    if urgent:
        return types.FunctionResponseScheduling.INTERRUPT
    return types.FunctionResponseScheduling.WHEN_IDLE
