"""日程与习惯模块的 HTTP 接口。"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.rhythm import (
    create_habit,
    create_personal_task,
    get_rhythm_state,
    toggle_habit_checkin,
    toggle_personal_task,
)
from backend.views.overview import get_life_overview

router = APIRouter()


class PersonalTaskIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    due_on: Optional[str] = None
    priority: Literal["low", "normal", "high"] = "normal"
    category: Literal["personal", "study", "health", "finance", "other"] = "personal"
    note: str = Field("", max_length=160)


class HabitIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    category: Literal["personal", "study", "health", "finance", "other"] = "personal"


class HabitCheckinIn(BaseModel):
    occurred_on: Optional[str] = None
    # 留空是「切换」；手机端离线补发时必须显式给出想要的状态，
    # 否则一条迟到的切换会把已经打好的卡取消掉。
    desired: Optional[bool] = None


class TaskToggleIn(BaseModel):
    desired: Optional[Literal["done", "pending"]] = None


@router.get("/api/rhythm")
def rhythm_state():
    with db() as conn:
        return get_rhythm_state(conn)


@router.post("/api/tasks")
def add_personal_task(body: PersonalTaskIn):
    with db() as conn:
        task = create_personal_task(
            conn,
            title=body.title,
            due_on=body.due_on or date.today().isoformat(),
            priority=body.priority,
            category=body.category,
            note=body.note,
        )
        return {"task": task, "rhythm": get_rhythm_state(conn), "life": get_life_overview(conn)}


@router.post("/api/tasks/{task_id}/toggle")
def toggle_task(task_id: int, body: Optional[TaskToggleIn] = None):
    with db() as conn:
        task = toggle_personal_task(conn, task_id, body.desired if body else None)
        return {"task": task, "rhythm": get_rhythm_state(conn), "life": get_life_overview(conn)}


@router.delete("/api/tasks/{task_id}")
def delete_personal_task(task_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM personal_tasks WHERE id = ?", (task_id,)).fetchone():
            raise HTTPException(404, "task not found")
        conn.execute("DELETE FROM personal_tasks WHERE id = ?", (task_id,))
        return {"deleted": task_id, "rhythm": get_rhythm_state(conn), "life": get_life_overview(conn)}


@router.post("/api/habits")
def add_habit(body: HabitIn):
    with db() as conn:
        habit = create_habit(conn, name=body.name, category=body.category)
        return {"habit": habit, "rhythm": get_rhythm_state(conn), "life": get_life_overview(conn)}


@router.post("/api/habits/{habit_id}/toggle")
def toggle_habit(habit_id: int, body: HabitCheckinIn):
    with db() as conn:
        result = toggle_habit_checkin(
            conn, habit_id, body.occurred_on or date.today().isoformat(), body.desired)
        return {**result, "rhythm": get_rhythm_state(conn), "life": get_life_overview(conn)}


@router.delete("/api/habits/{habit_id}")
def archive_habit(habit_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM habits WHERE id = ? AND is_active = 1", (habit_id,)).fetchone():
            raise HTTPException(404, "active habit not found")
        conn.execute("UPDATE habits SET is_active = 0 WHERE id = ?", (habit_id,))
        return {"archived": habit_id, "rhythm": get_rhythm_state(conn), "life": get_life_overview(conn)}
