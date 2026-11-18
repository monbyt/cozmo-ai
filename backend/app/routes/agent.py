from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from ..services.agent import AgentService

router = APIRouter()
_agent = AgentService()


class TurnIn(BaseModel):
    sweep_id: str
    user_text: str
    capture_notes: list[str] = []
    books_so_far: int = 0
    items_so_far: int = 0


class TurnOut(BaseModel):
    reply: str


@router.post("/agent/turn", response_model=TurnOut)
async def agent_turn(body: TurnIn) -> TurnOut:
    reply = _agent.turn(
        user_text=body.user_text,
        recent_notes=body.capture_notes,
        books_so_far=body.books_so_far,
        items_so_far=body.items_so_far,
    )
    return TurnOut(reply=reply)
