from __future__ import annotations
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .routes.sweep import router as sweep_router
from .routes.agent import router as agent_router
from .routes.stt import router as stt_router
from .routes.live import router as live_router
from .storage import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

app = FastAPI(title="Library Contents Claim Agent", version="0.2.0")
settings = get_settings()

_origins = settings.cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _origins == ["*"] else _origins,
    allow_credentials=False if _origins == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "has_gemini_key": "yes" if settings.gemini_api_key else "no",
        "has_serpapi_key": "yes" if settings.serpapi_key else "no",
    }


app.include_router(sweep_router)
app.include_router(agent_router)
app.include_router(stt_router)
app.include_router(live_router)

# Web client (Vite build) — served from the same Fly host so reviewers get one link.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir() and (STATIC_DIR / "index.html").exists():
    assets = STATIC_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def spa_index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        # Don't swallow API paths that somehow missed a router.
        candidate = STATIC_DIR / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(STATIC_DIR / "index.html")
