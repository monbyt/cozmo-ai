"""SQLite storage for per-sweep intermediate data. Totals are computed at export time, never stored."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

DB_PATH = Path(__file__).parent.parent / "data" / "sweeps.db"
FRAMES_DIR = Path(__file__).parent.parent / "data" / "frames"
SWEEPS_DIR = Path(__file__).parent.parent / "data" / "sweeps"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sweeps (
    id TEXT PRIMARY KEY,
    captured_at TEXT NOT NULL,
    device TEXT,
    duration_s REAL,
    country TEXT,
    currency TEXT,
    status TEXT DEFAULT 'in_progress',
    meta_json TEXT
);

CREATE TABLE IF NOT EXISTS frames (
    id TEXT PRIMARY KEY,
    sweep_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    path TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    blur_score REAL,
    glare_score REAL,
    orientation_json TEXT,
    FOREIGN KEY (sweep_id) REFERENCES sweeps(id)
);

CREATE TABLE IF NOT EXISTS book_candidates (
    id TEXT PRIMARY KEY,
    sweep_id TEXT NOT NULL,
    frame_id TEXT,
    shelf TEXT,
    position INTEGER,
    bbox_json TEXT,
    ocr_text TEXT,
    ocr_title TEXT,
    ocr_author TEXT,
    ocr_publisher TEXT,
    spine_height_cm REAL,
    spine_thickness_cm REAL,
    resolved_title TEXT,
    resolved_author TEXT,
    resolved_edition TEXT,
    resolved_isbn TEXT,
    id_confidence REAL,
    status TEXT,
    rare_flag_reason TEXT,
    replacement_cost_json TEXT,
    used_value_json TEXT,
    dedup_key TEXT,
    FOREIGN KEY (sweep_id) REFERENCES sweeps(id)
);

CREATE INDEX IF NOT EXISTS idx_books_sweep ON book_candidates(sweep_id);
CREATE INDEX IF NOT EXISTS idx_books_dedup ON book_candidates(sweep_id, dedup_key);

CREATE TABLE IF NOT EXISTS item_candidates (
    id TEXT PRIMARY KEY,
    sweep_id TEXT NOT NULL,
    frame_id TEXT,
    category TEXT,
    description TEXT,
    brand_model TEXT,
    dims_json TEXT,
    status TEXT,
    replacement_cost_json TEXT,
    confidence REAL,
    dedup_key TEXT,
    FOREIGN KEY (sweep_id) REFERENCES sweeps(id)
);

CREATE INDEX IF NOT EXISTS idx_items_sweep ON item_candidates(sweep_id);

CREATE TABLE IF NOT EXISTS room_state (
    sweep_id TEXT PRIMARY KEY,
    length_m REAL DEFAULT 0,
    width_m REAL DEFAULT 0,
    height_m REAL DEFAULT 0,
    floor_area_m2 REAL DEFAULT 0,
    wall_area_m2 REAL DEFAULT 0,
    shelved_wall_area_m2 REAL DEFAULT 0,
    scale_method TEXT DEFAULT '',
    confidence REAL DEFAULT 0,
    FOREIGN KEY (sweep_id) REFERENCES sweeps(id)
);

CREATE TABLE IF NOT EXISTS review_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sweep_id TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    FOREIGN KEY (sweep_id) REFERENCES sweeps(id)
);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    SWEEPS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _j(v: Any) -> str:
    return json.dumps(v) if v is not None else ""


def insert_sweep(sweep_id: str, captured_at: str, device: str, country: str, currency: str) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO sweeps(id, captured_at, device, country, currency) VALUES(?,?,?,?,?)",
            (sweep_id, captured_at, device, country, currency),
        )
        conn.execute("INSERT INTO room_state(sweep_id) VALUES(?)", (sweep_id,))
        conn.commit()
    finally:
        conn.close()


def finalize_sweep(sweep_id: str, duration_s: float) -> None:
    conn = connect()
    try:
        conn.execute(
            "UPDATE sweeps SET duration_s=?, status='complete' WHERE id=?",
            (duration_s, sweep_id),
        )
        conn.commit()
    finally:
        conn.close()


def insert_frame(frame_id: str, sweep_id: str, captured_at: str, path: str,
                 width: int, height: int, blur_score: float, glare_score: float,
                 orientation: dict | None) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO frames(id, sweep_id, captured_at, path, width, height, blur_score, glare_score, orientation_json) VALUES(?,?,?,?,?,?,?,?,?)",
            (frame_id, sweep_id, captured_at, path, width, height, blur_score, glare_score, _j(orientation)),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_book_candidate(**row: Any) -> None:
    cols = list(row.keys())
    placeholders = ",".join("?" for _ in cols)
    conn = connect()
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO book_candidates({','.join(cols)}) VALUES({placeholders})",
            tuple(row.values()),
        )
        conn.commit()
    finally:
        conn.close()


def upsert_item_candidate(**row: Any) -> None:
    cols = list(row.keys())
    placeholders = ",".join("?" for _ in cols)
    conn = connect()
    try:
        conn.execute(
            f"INSERT OR REPLACE INTO item_candidates({','.join(cols)}) VALUES({placeholders})",
            tuple(row.values()),
        )
        conn.commit()
    finally:
        conn.close()


def patch_book_candidate(book_id: str, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    conn = connect()
    try:
        conn.execute(f"UPDATE book_candidates SET {sets} WHERE id=?", (*fields.values(), book_id))
        conn.commit()
    finally:
        conn.close()


def patch_item_candidate(item_id: str, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    conn = connect()
    try:
        conn.execute(f"UPDATE item_candidates SET {sets} WHERE id=?", (*fields.values(), item_id))
        conn.commit()
    finally:
        conn.close()


def book_exists_by_dedup(sweep_id: str, dedup_key: str) -> bool:
    conn = connect()
    try:
        cur = conn.execute(
            "SELECT 1 FROM book_candidates WHERE sweep_id=? AND dedup_key=? LIMIT 1",
            (sweep_id, dedup_key),
        )
        return cur.fetchone() is not None
    finally:
        conn.close()


def get_sweep(sweep_id: str) -> dict | None:
    conn = connect()
    try:
        cur = conn.execute("SELECT * FROM sweeps WHERE id=?", (sweep_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_books(sweep_id: str) -> list[dict]:
    conn = connect()
    try:
        cur = conn.execute("SELECT * FROM book_candidates WHERE sweep_id=? ORDER BY shelf, position", (sweep_id,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_items(sweep_id: str) -> list[dict]:
    conn = connect()
    try:
        cur = conn.execute("SELECT * FROM item_candidates WHERE sweep_id=?", (sweep_id,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_room(sweep_id: str) -> dict | None:
    conn = connect()
    try:
        cur = conn.execute("SELECT * FROM room_state WHERE sweep_id=?", (sweep_id,))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_room(sweep_id: str, **fields: Any) -> None:
    if not fields:
        return
    sets = ",".join(f"{k}=?" for k in fields.keys())
    conn = connect()
    try:
        conn.execute(
            f"UPDATE room_state SET {sets} WHERE sweep_id=?",
            tuple(fields.values()) + (sweep_id,),
        )
        conn.commit()
    finally:
        conn.close()


def delete_book(book_id: str) -> None:
    conn = connect()
    try:
        conn.execute("DELETE FROM book_candidates WHERE id=?", (book_id,))
        conn.commit()
    finally:
        conn.close()


def delete_item(item_id: str) -> None:
    conn = connect()
    try:
        conn.execute("DELETE FROM item_candidates WHERE id=?", (item_id,))
        conn.commit()
    finally:
        conn.close()


def add_review(sweep_id: str, ref_id: str, reason: str) -> None:
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO review_queue(sweep_id, ref_id, reason) VALUES(?,?,?)",
            (sweep_id, ref_id, reason),
        )
        conn.commit()
    finally:
        conn.close()


def get_review(sweep_id: str) -> list[dict]:
    conn = connect()
    try:
        cur = conn.execute("SELECT ref_id, reason FROM review_queue WHERE sweep_id=?", (sweep_id,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
