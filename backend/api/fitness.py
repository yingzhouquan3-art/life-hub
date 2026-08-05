"""个人健身模块的 HTTP 接口。"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.fitness import get_fitness_state, record_workout
from backend.views.overview import get_life_overview

router = APIRouter()


class WorkoutIn(BaseModel):
    occurred_on: Optional[str] = None
    activity: Literal["strength", "cardio", "sport", "mobility", "other"]
    duration_minutes: int = Field(..., ge=1, le=1440)
    intensity: int = Field(..., ge=1, le=10)
    note: str = Field("", max_length=120)


@router.get("/api/fitness")
def fitness_state():
    with db() as conn:
        return get_fitness_state(conn)


@router.post("/api/fitness/sessions")
def add_workout(body: WorkoutIn):
    with db() as conn:
        session = record_workout(
            conn,
            occurred_on=body.occurred_on or date.today().isoformat(),
            activity=body.activity,
            duration_minutes=body.duration_minutes,
            intensity=body.intensity,
            note=body.note,
        )
        return {"session": session, "fitness": get_fitness_state(conn), "life": get_life_overview(conn)}


@router.delete("/api/fitness/sessions/{session_id}")
def delete_workout(session_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM fitness_sessions WHERE id = ?", (session_id,)).fetchone():
            raise HTTPException(404, "fitness session not found")
        conn.execute("DELETE FROM fitness_sessions WHERE id = ?", (session_id,))
        return {"deleted": session_id, "fitness": get_fitness_state(conn), "life": get_life_overview(conn)}
