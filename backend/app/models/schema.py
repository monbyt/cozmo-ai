"""Claim packet schema — mirrors the contract in the brief exactly, with additions allowed."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Sweep(BaseModel):
    id: str = ""
    captured_at: str = ""
    device: str = ""
    duration_s: float = 0
    country: str = ""
    currency: str = ""


class Room(BaseModel):
    length_m: float = 0
    width_m: float = 0
    height_m: float = 0
    floor_area_m2: float = 0
    wall_area_m2: float = 0
    shelved_wall_area_m2: float = 0
    scale_method: str = ""
    confidence: float = 0
    # Extensions — brief asks for ft² in the report; also echoed here for adjusters.
    floor_area_ft2: float = 0
    wall_area_ft2: float = 0
    shape_notes: str = ""


class Price(BaseModel):
    amount: float = 0
    source: str = ""
    url: str = ""
    retrieved_at: str = ""
    converted: bool = False
    condition_assumed: str = ""  # used only; harmless on replacement


class PriceRange(BaseModel):
    low: float = 0
    high: float = 0
    source: str = ""
    url: str = ""
    retrieved_at: str = ""


BookStatus = Literal["identified", "unidentified", "needs_appraisal"]


class Book(BaseModel):
    id: str
    shelf: str = ""
    position: int = 0
    frame_ref: str = ""  # points to a saved frame path or timestamp
    status: BookStatus = "unidentified"
    title: str = ""
    author: str = ""
    edition: str = ""
    isbn: str = ""
    spine_height_cm: float = 0
    spine_thickness_cm: float = 0
    id_confidence: float = 0
    replacement_cost: Optional[Price] = None
    used_value: Optional[Price] = None
    # Extensions:
    rare_flag_reason: str = ""  # why human appraisal is needed


ItemStatus = Literal["priced", "range", "needs_appraisal"]


class ItemDimensions(BaseModel):
    w: float = 0
    h: float = 0
    d: float = 0


class Item(BaseModel):
    id: str
    category: str = ""
    description: str = ""
    brand_model: str = ""
    frame_ref: str = ""
    dimensions_cm: ItemDimensions = Field(default_factory=ItemDimensions)
    status: ItemStatus = "range"
    replacement_cost: Optional[PriceRange] = None
    confidence: float = 0


class Totals(BaseModel):
    book_count: int = 0
    books_identified: int = 0
    books_unidentified: int = 0
    shelf_run_m: float = 0
    books_replacement_cost: float = 0
    books_used_value: float = 0
    items_replacement_cost_low: float = 0
    items_replacement_cost_high: float = 0
    excluded_from_totals: int = 0


class ReviewItem(BaseModel):
    ref_id: str
    reason: str


class ClaimPacket(BaseModel):
    sweep: Sweep
    room: Room
    books: list[Book] = Field(default_factory=list)
    items: list[Item] = Field(default_factory=list)
    totals: Totals = Field(default_factory=Totals)
    review_queue: list[ReviewItem] = Field(default_factory=list)
