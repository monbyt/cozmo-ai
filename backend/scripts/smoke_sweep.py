"""Pretend to be the phone. Feeds one or more JPGs to the backend WebSocket as 'frames'
and prints the live inventory updates + final packet URL.

Usage:
  .venv/bin/python scripts/smoke_sweep.py /path/to/shelf.jpg [/path/to/shelf2.jpg ...]

Requires the backend to be running on 127.0.0.1:8000.
"""
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
import websockets


BACKEND_WS = "ws://127.0.0.1:8000/ws/sweep"
BACKEND_HTTP = "http://127.0.0.1:8000"


async def run(paths: list[Path]) -> None:
    async with websockets.connect(BACKEND_WS, max_size=16 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "type": "start",
            "country": "US",
            "currency": "USD",
            "device": "smoke_test_cli",
        }))
        start_ack = json.loads(await ws.recv())
        sweep_id = start_ack.get("sweep_id")
        print(f"[started] sweep_id={sweep_id}\n")

        async def read_server():
            async for raw in ws:
                try:
                    m = json.loads(raw)
                except Exception:
                    continue
                t = m.get("type")
                if t == "inventory_update":
                    for b in m.get("new_books", []):
                        print(f"  [book]  {b['status']:14s}  conf={b['id_confidence']:.2f}  "
                              f"h={b['spine_height_cm']:.1f}×t={b['spine_thickness_cm']:.1f}cm  "
                              f"scale={b.get('scale_method','')}  "
                              f"title={b['title']!r}  author={b['author']!r}")
                    for i in m.get("new_items", []):
                        print(f"  [item]  {i['status']:14s}  cat={i['category']}  "
                              f"desc={i['description']!r}")
                    for n in m.get("notes", []):
                        print(f"  [note]  {n}")
                elif t == "capture_note":
                    print(f"  [cap!]  {m.get('note')}")
                elif t == "packet_ready":
                    print(f"\n[packet_ready] {m['sweep_id']}")
                    print(f"  JSON: {BACKEND_HTTP}{m['json_url']}")
                    print(f"  HTML: {BACKEND_HTTP}{m['html_url']}")
                    return

        reader = asyncio.create_task(read_server())

        for i, p in enumerate(paths):
            jpg = p.read_bytes()
            fid = f"f_{int(time.time()*1000)}_{i}"
            await ws.send(json.dumps({
                "type": "frame_meta",
                "frame_id": fid,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "shelf_hint": p.stem,
                "intrinsics": {
                    # Fake-but-reasonable intrinsics for a 4032x3024 iPhone 15 Pro main camera (fov ~65°).
                    "fx": 3200.0, "fy": 3200.0,
                    "cx": 2016.0, "cy": 1512.0,
                    "width": 4032, "height": 3024,
                },
            }))
            await ws.send(jpg)
            print(f"[frame] sent {p.name} ({len(jpg)//1024}kB) -- waiting for perception...")
            await asyncio.sleep(0.3)  # let the backend process

        # Simulate a floor plane so the room block gets a value
        await ws.send(json.dumps({
            "type": "plane", "kind": "floor", "area_m2": 12.0, "width_m": 4.0, "height_m": 3.0,
        }))
        await ws.send(json.dumps({
            "type": "plane", "kind": "wall", "area_m2": 8.4, "width_m": 3.5, "height_m": 2.4,
        }))

        # Wait up to 90s for all frame processing to complete
        print("\n[waiting for backend to finish processing...]")
        await asyncio.sleep(2)
        await ws.send(json.dumps({"type": "end"}))

        try:
            await asyncio.wait_for(reader, timeout=120)
        except asyncio.TimeoutError:
            print("[TIMEOUT] packet_ready never arrived")

    # Also fetch the JSON packet so we can see totals
    if sweep_id:
        async with httpx.AsyncClient() as http:
            r = await http.get(f"{BACKEND_HTTP}/sweeps/{sweep_id}/claim_packet.json")
            if r.status_code == 200:
                packet = r.json()
                print("\n=== TOTALS ===")
                print(json.dumps(packet["totals"], indent=2))
                print("\n=== ROOM ===")
                print(json.dumps(packet["room"], indent=2))
                print(f"\n=== REVIEW QUEUE ({len(packet['review_queue'])}) ===")
                for r in packet["review_queue"][:10]:
                    print(f"  {r['ref_id']}: {r['reason']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    paths = [Path(p).expanduser().resolve() for p in sys.argv[1:]]
    for p in paths:
        if not p.exists():
            print(f"ERROR: {p} does not exist")
            sys.exit(1)
    asyncio.run(run(paths))
