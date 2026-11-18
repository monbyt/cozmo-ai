"""Gemini vision calls: spine detection+OCR per shelf crop, non-book item detection, quality gate.
We never let the model produce prices or book-identity 'guesses': status fields are strict."""
from __future__ import annotations
import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from ..config import get_settings

log = logging.getLogger(__name__)

SPINE_SCHEMA = {
    "type": "object",
    "properties": {
        "spines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "bbox": {
                        "type": "object",
                        "description": "Normalized bbox in [0,1], x,y,w,h",
                        "properties": {
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "w": {"type": "number"},
                            "h": {"type": "number"},
                        },
                        "required": ["x", "y", "w", "h"],
                    },
                    "orientation": {"type": "string", "enum": ["vertical", "horizontal_stacked"]},
                    "ocr_title": {"type": "string", "description": "Empty if not clearly legible."},
                    "ocr_author": {"type": "string"},
                    "ocr_publisher": {"type": "string"},
                    "visible_text": {"type": "string", "description": "Raw text as read; include partials."},
                    "legibility": {
                        "type": "string",
                        "enum": ["clear", "partial", "unreadable"],
                        "description": "How confidently the text was read, NOT how confident we are about the book identity.",
                    },
                    "rare_signals": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Mentions of 'first edition', 'signed', 'limited', gilt lettering on leather, etc.",
                    },
                },
                "required": ["bbox", "orientation", "legibility"],
            },
        },
        "frame_quality": {
            "type": "object",
            "properties": {
                "blur": {"type": "string", "enum": ["none", "mild", "severe"]},
                "glare": {"type": "string", "enum": ["none", "mild", "severe"]},
                "note": {"type": "string"},
            },
        },
    },
    "required": ["spines"],
}

ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "shelving | furniture | lamp | rug | electronics | artwork | decor | appliance | other",
                    },
                    "description": {"type": "string"},
                    "brand_model": {"type": "string", "description": "Only if clearly legible."},
                    "material_hint": {"type": "string"},
                    "approx_w_cm": {"type": "number"},
                    "approx_h_cm": {"type": "number"},
                    "approx_d_cm": {"type": "number"},
                    "needs_appraisal": {
                        "type": "boolean",
                        "description": "True for original artwork, antiques, signed pieces, etc.",
                    },
                    "appraisal_reason": {"type": "string"},
                },
                "required": ["category", "description"],
            },
        },
    },
    "required": ["items"],
}


SPINE_PROMPT = """You are inspecting a single video frame of a home library for an insurance inventory.

Return every clearly visible book spine in this frame. For each spine:
- bbox in normalized [0,1] coordinates.
- orientation: "vertical" for upright spines, "horizontal_stacked" for books lying flat.
- ocr_title / ocr_author / ocr_publisher: fill ONLY if you can read them. Leave empty if not.
- visible_text: the raw characters you can read, partials included.
- legibility: "clear" (fully readable), "partial" (some letters), "unreadable" (shape only).
- rare_signals: any visual hints of first editions, signed copies, antiquarian bindings, leather + gilt, dust jacket wear suggesting age, etc.

Hard rules:
- NEVER guess a title you cannot read. "Unreadable" means empty ocr fields.
- If a book is only partially visible (cut off at the edge), still report the bbox but mark legibility accordingly.
- Also fill frame_quality: blur and glare levels as you see them.

Return JSON matching the schema."""


ITEM_PROMPT = """You are inspecting a video frame of a home room for an insurance inventory.

Return every non-book item visible: shelving, furniture, lamps, rugs, electronics, artwork, decor, appliances.

For each item:
- category from the list in the schema
- description: what you can plainly see (e.g. "mid-century walnut armchair, upholstered in olive linen")
- brand_model: ONLY if a logo or nameplate is legible
- material_hint: wood/metal/fabric/glass/etc.
- approximate dimensions in cm (rough is fine, but reasoned from context)
- needs_appraisal: true if this looks like an original artwork, antique, or signed piece. Portraits and framed art default to true unless clearly a print.
- appraisal_reason: why.

Do NOT include books. Do NOT invent brands. Return JSON matching the schema."""


@dataclass
class VisionConfig:
    model: str
    api_key: str


class VisionService:
    def __init__(self, cfg: VisionConfig | None = None):
        s = get_settings()
        self.cfg = cfg or VisionConfig(model=s.gemini_vision_model, api_key=s.gemini_api_key)
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            if not self.cfg.api_key:
                raise RuntimeError("GEMINI_API_KEY not set — cannot run vision. Add it to backend/.env.")
            self._client = genai.Client(api_key=self.cfg.api_key)
        return self._client

    def _call(self, image_path: Path, prompt: str, schema: dict) -> dict[str, Any]:
        image_bytes = image_path.read_bytes()
        try:
            resp = self.client.models.generate_content(
                model=self.cfg.model,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.1,  # low: we want deterministic reads, not creativity
                ),
            )
            text = resp.text or "{}"
            return json.loads(text)
        except Exception as e:
            log.exception("vision call failed: %s", e)
            return {"error": str(e), "spines": [], "items": []}

    def detect_spines(self, image_path: Path) -> dict[str, Any]:
        return self._call(image_path, SPINE_PROMPT, SPINE_SCHEMA)

    def detect_items(self, image_path: Path) -> dict[str, Any]:
        return self._call(image_path, ITEM_PROMPT, ITEM_SCHEMA)
