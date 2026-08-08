"""学习与专注模块的 HTTP 接口。"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.study import (
    finish_focus_session,
    get_focus_state,
    get_study_state,
    record_study_session,
    start_focus_session,
)
from backend.views.overview import get_life_overview

router = APIRouter()


class StudySessionIn(BaseModel):
    occurred_on: Optional[str] = None
    subject: str = Field(..., min_length=1, max_length=80)
    duration_minutes: int = Field(..., ge=1, le=1440)
    focus: int = Field(..., ge=1, le=5)
    note: str = Field("", max_length=120)


@router.get("/api/study")
def study_state():
    with db() as conn:
        return get_study_state(conn)


@router.post("/api/study/sessions")
def add_study_session(body: StudySessionIn):
    with db() as conn:
        session = record_study_session(
            conn,
            occurred_on=body.occurred_on or date.today().isoformat(),
            subject=body.subject,
            duration_minutes=body.duration_minutes,
            focus=body.focus,
            note=body.note,
        )
        return {"session": session, "study": get_study_state(conn), "life": get_life_overview(conn)}


@router.delete("/api/study/sessions/{session_id}")
def delete_study_session(session_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM study_sessions WHERE id = ?", (session_id,)).fetchone():
            raise HTTPException(404, "study session not found")
        conn.execute("DELETE FROM study_sessions WHERE id = ?", (session_id,))
        return {"deleted": session_id, "study": get_study_state(conn), "life": get_life_overview(conn)}


class FocusStartIn(BaseModel):
    kind: Literal["focus", "short_break", "long_break"] = "focus"
    minutes: Optional[int] = Field(None, ge=1, le=240)
    subject: str = Field("", max_length=30)


class FocusFinishIn(BaseModel):
    focus: Optional[int] = Field(None, ge=1, le=5)
    record: bool = True


@router.get("/api/study/focus")
def focus_state():
    """当前番茄与今日完成情况。剩余秒数由后端按结束时刻算，前端只负责显示。"""
    with db() as conn:
        return get_focus_state(conn)


@router.post("/api/study/focus")
def start_focus(body: FocusStartIn):
    with db() as conn:
        session = start_focus_session(
            conn, kind=body.kind, minutes=body.minutes, subject=body.subject,
        )
        return {"session": session, "focus": get_focus_state(conn)}


@router.post("/api/study/focus/{session_id}/finish")
def finish_focus(session_id: int, body: FocusFinishIn):
    """结束一个番茄。按**实际专注分钟数**记学习，不足一分钟不记。"""
    with db() as conn:
        session = finish_focus_session(
            conn, session_id, focus=body.focus, record=body.record,
        )
        return {
            "session": session,
            "focus": get_focus_state(conn),
            "study": get_study_state(conn),
        }
