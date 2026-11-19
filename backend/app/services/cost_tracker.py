"""Per-sweep cost + latency counters. Written to cost.json at packet build time.

Numbers are modelled from observed call counts × published unit prices — not invoices.
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# Rough USD unit costs (update when provider pricing changes).
UNIT_COST_USD = {
    "gemini_live_minute": 0.02,       # audio+video Live session (approx)
    "gemini_resolve_call": 0.0003,    # OpenLibrary is free; residual LLM unused
    "serpapi_search": 0.005,
    "openlibrary_lookup": 0.0,
}


@dataclass
class StageTimer:
    name: str
    started: float = 0.0
    elapsed_ms: float = 0.0
    count: int = 0

    def start(self) -> None:
        self.started = time.perf_counter()

    def stop(self) -> None:
        if self.started:
            self.elapsed_ms += (time.perf_counter() - self.started) * 1000
            self.count += 1
            self.started = 0.0


@dataclass
class CostTracker:
    sweep_id: str
    stages: dict[str, StageTimer] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.perf_counter)

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def stage(self, name: str) -> StageTimer:
        if name not in self.stages:
            self.stages[name] = StageTimer(name=name)
        return self.stages[name]

    def estimate_usd(self) -> float:
        live_min = max(1.0, (time.perf_counter() - self.started_at) / 60.0)
        total = live_min * UNIT_COST_USD["gemini_live_minute"]
        total += self.counts.get("serpapi_search", 0) * UNIT_COST_USD["serpapi_search"]
        total += self.counts.get("resolve", 0) * UNIT_COST_USD["openlibrary_lookup"]
        return round(total, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sweep_id": self.sweep_id,
            "duration_s": round(time.perf_counter() - self.started_at, 1),
            "estimated_cost_usd": self.estimate_usd(),
            "counts": dict(self.counts),
            "stages_ms": {
                name: {"count": s.count, "total_ms": round(s.elapsed_ms, 1),
                       "median_ms": round(s.elapsed_ms / s.count, 1) if s.count else 0}
                for name, s in self.stages.items()
            },
            "unit_costs_usd": UNIT_COST_USD,
            "note": "Modelled from call counts × unit prices, not invoices.",
        }

    def write(self, out_dir: Path) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "cost.json"
        path.write_text(json.dumps(self.to_dict(), indent=2))
        return path
