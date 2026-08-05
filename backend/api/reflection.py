"""日记与复盘模块的 HTTP 接口。"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.reflection import get_reflection_state, save_daily_reflection
from backend.views.overview import get_life_overview

router = APIRouter()


class DailyReflectionIn(BaseModel):
    occurred_on: Optional[str] = None
    highlight: str = Field("", max_length=500)
    challenge: str = Field("", max_length=500)
    gratitude: str = Field("", max_length=500)
    note: str = Field("", max_length=1200)


@router.get("/api/reflection")
def reflection_state(reflection_date: Optional[str] = Query(None, alias="date")):
    if reflection_date:
        try:
            date.fromisoformat(reflection_date)
        except ValueError as exc:
            raise HTTPException(400, "invalid reflection date") from exc
    with db() as conn:
        return get_reflection_state(conn, reflection_date)


@router.post("/api/reflections")
def set_daily_reflection(body: DailyReflectionIn):
    occurred_on = body.occurred_on or date.today().isoformat()
    try:
        date.fromisoformat(occurred_on)
    except ValueError as exc:
        raise HTTPException(400, "invalid reflection date") from exc
    with db() as conn:
        reflection = save_daily_reflection(
            conn,
            occurred_on=occurred_on,
            highlight=body.highlight,
            challenge=body.challenge,
            gratitude=body.gratitude,
            note=body.note,
        )
        return {
            "reflection": reflection,
            "reflection_state": get_reflection_state(conn, occurred_on),
            "life": get_life_overview(conn),
        }


@router.delete("/api/reflections/{reflection_id}")
def delete_daily_reflection(reflection_id: int):
    with db() as conn:
        row = conn.execute(
            "SELECT occurred_on FROM daily_reflections WHERE id = ?", (reflection_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "reflection not found")
        conn.execute("DELETE FROM daily_reflections WHERE id = ?", (reflection_id,))
        return {
            "deleted": reflection_id,
            "reflection": get_reflection_state(conn, row["occurred_on"]),
            "life": get_life_overview(conn),
        }
