"""睡眠与恢复模块的 HTTP 接口。"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.recovery import get_recovery_state, save_recovery_checkin
from backend.views.overview import get_life_overview

router = APIRouter()


class RecoveryCheckinIn(BaseModel):
    occurred_on: Optional[str] = None
    sleep_hours: Optional[float] = Field(None, ge=0, le=24)
    sleep_quality: Optional[int] = Field(None, ge=1, le=5)
    energy: Optional[int] = Field(None, ge=1, le=5)
    mood: Optional[int] = Field(None, ge=1, le=5)
    note: str = Field("", max_length=120)


@router.get("/api/recovery")
def recovery_state():
    with db() as conn:
        return get_recovery_state(conn)


@router.post("/api/recovery/checkin")
def set_recovery_checkin(body: RecoveryCheckinIn):
    with db() as conn:
        checkin = save_recovery_checkin(
            conn,
            occurred_on=body.occurred_on or date.today().isoformat(),
            sleep_hours=body.sleep_hours,
            sleep_quality=body.sleep_quality,
            energy=body.energy,
            mood=body.mood,
            note=body.note,
        )
        return {"checkin": checkin, "recovery": get_recovery_state(conn), "life": get_life_overview(conn)}


@router.delete("/api/recovery/checkins/{checkin_id}")
def delete_recovery_checkin(checkin_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM recovery_checkins WHERE id = ?", (checkin_id,)).fetchone():
            raise HTTPException(404, "recovery checkin not found")
        conn.execute("DELETE FROM recovery_checkins WHERE id = ?", (checkin_id,))
        return {"deleted": checkin_id, "recovery": get_recovery_state(conn), "life": get_life_overview(conn)}
