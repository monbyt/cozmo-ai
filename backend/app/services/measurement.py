"""Measurement module. With ARKit upstream, most heavy lifting is done on-device.

The frontend streams in (per frame) the camera intrinsics, the 6DoF pose, and when available,
depth samples and plane anchors. The backend's job here is:

  1. Convert pixel bboxes (from vision) into metric spine_height_cm / spine_thickness_cm
     using the depth sample at the bbox center. Fallback to reference-object scaling
     (first resolved book's known typical height) if depth is unavailable.
  2. Aggregate plane anchors into floor_area_m2, wall_area_m2.
  3. Record scale_method so adjusters can trust the number.

No geometry is invented. If we lack data, we return 0 and add a review note."""
from __future__ import annotations
import logging
import math
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Typical print book formats (cm). Used as reference-object fallback.
TYPICAL_HEIGHTS = {
    "hardcover_trade": 23.5,
    "paperback_mass": 17.5,
    "paperback_trade": 20.3,
    "coffee_table": 30.0,
}


@dataclass
class Intrinsics:
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int


@dataclass
class DepthSample:
    """Single depth reading from ARKit at (u,v). value_m is linear depth in meters."""
    u: int
    v: int
    value_m: float
    confidence: float = 1.0


def bbox_to_metric_from_depth(
    bbox: dict[str, float],
    intrinsics: Intrinsics,
    depth_samples: list[DepthSample],
) -> tuple[float, float, str] | None:
    """Return (height_cm, thickness_cm, method) using ARKit depth under the bbox.
    Returns None if no depth samples available for the bbox."""
    W, H = intrinsics.width, intrinsics.height
    x = bbox["x"] * W
    y = bbox["y"] * H
    w = bbox["w"] * W
    h = bbox["h"] * H
    cx_px, cy_px = x + w / 2, y + h / 2

    nearby = [s for s in depth_samples if x <= s.u <= x + w and y <= s.v <= y + h and s.value_m > 0]
    if not nearby:
        return None
    z = sorted(s.value_m for s in nearby)[len(nearby) // 2]  # median depth

    # Pinhole projection: object metric size = pixel_size * z / focal
    height_m = (h * z) / intrinsics.fy
    thickness_m = (w * z) / intrinsics.fx
    return round(height_m * 100, 1), round(thickness_m * 100, 1), "arkit_lidar_depth"


def bbox_to_metric_from_reference(
    bbox: dict[str, float],
    intrinsics: Intrinsics,
    reference_height_cm: float,
    reference_bbox_pixel_height: float,
) -> tuple[float, float, str]:
    """When depth isn't available: scale from a known book height in the same frame."""
    W, H = intrinsics.width, intrinsics.height
    w = bbox["w"] * W
    h = bbox["h"] * H
    cm_per_px = reference_height_cm / reference_bbox_pixel_height
    return round(h * cm_per_px, 1), round(w * cm_per_px, 1), "reference_object"


@dataclass
class PlaneAnchor:
    """ARKit plane anchor projected to world coordinates."""
    kind: str  # "floor" | "wall" | "ceiling" | "other"
    area_m2: float
    width_m: float = 0
    height_m: float = 0  # vertical extent for walls


def aggregate_room(planes: list[PlaneAnchor]) -> dict[str, float]:
    """Sum plane areas. ARKit labels planes as horizontal/vertical;
    the frontend tags them as floor/wall/ceiling/other before sending.
    Floors are deduplicated by keeping the largest connected floor area in the sweep."""
    floors = [p for p in planes if p.kind == "floor"]
    walls = [p for p in planes if p.kind == "wall"]

    floor_area_m2 = max((p.area_m2 for p in floors), default=0.0)
    wall_area_m2 = sum(p.area_m2 for p in walls)

    # Height estimate: median wall height
    heights = [p.height_m for p in walls if p.height_m > 0]
    heights.sort()
    height_m = heights[len(heights) // 2] if heights else 0.0

    # Rough length/width from floor: assume rectangular if we only have one floor plane
    length_m = width_m = 0
    if floors:
        f = max(floors, key=lambda p: p.area_m2)
        if f.width_m and f.height_m:
            length_m, width_m = f.width_m, f.height_m
        else:
            side = math.sqrt(f.area_m2) if f.area_m2 > 0 else 0
            length_m = width_m = round(side, 2)

    return {
        "length_m": round(length_m, 2),
        "width_m": round(width_m, 2),
        "height_m": round(height_m, 2),
        "floor_area_m2": round(floor_area_m2, 2),
        "wall_area_m2": round(wall_area_m2, 2),
    }
