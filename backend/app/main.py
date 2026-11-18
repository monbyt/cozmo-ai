from __future__ import annotations
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routes.sweep import router as sweep_router
from .routes.agent import router as agent_router
from .routes.stt import router as stt_router
from .routes.live import router as live_router
from .storage import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

app = FastAPI(title="Library Contents Claim Agent", version="0.1.0")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
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
