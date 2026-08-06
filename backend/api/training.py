"""训练记录的 HTTP 接口：动作库、组数与个人纪录。

和 api/fitness.py 分开：那边管「今天动了多久」，这边管「具体做了什么」。
两者写的是同一个模块的表，所以放在同一层，只是路由分组不同。
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.fitness import (
    archive_exercise,
    create_exercise,
    delete_set,
    get_exercise_records,
    get_training_state,
    record_set,
)

router = APIRouter()


class ExerciseIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    kind: Literal["strength", "cardio", "mobility"] = "strength"
    muscle_group: str = Field("", max_length=30)


class WorkoutSetIn(BaseModel):
    session_id: int
    exercise_id: int
    reps: Optional[int] = Field(None, gt=0, le=1000)
    weight_kg: Optional[float] = Field(None, gt=0, le=1000)
    distance_km: Optional[float] = Field(None, gt=0, le=1000)
    duration_seconds: Optional[int] = Field(None, gt=0, le=86400)
    note: str = Field("", max_length=120)


@router.get("/api/training")
def training_state(recent: int = 10):
    with db() as conn:
        return get_training_state(conn, recent)


@router.post("/api/training/exercises")
def add_exercise(body: ExerciseIn):
    with db() as conn:
        exercise = create_exercise(
            conn, name=body.name, kind=body.kind, muscle_group=body.muscle_group,
        )
        return {"exercise": exercise, "training": get_training_state(conn)}


@router.delete("/api/training/exercises/{exercise_id}")
def remove_exercise(exercise_id: int):
    """归档一个动作。已有的组数与纪录全部保留。"""
    with db() as conn:
        return {
            "exercise": archive_exercise(conn, exercise_id),
            "training": get_training_state(conn),
        }


@router.get("/api/training/exercises/{exercise_id}/records")
def exercise_records(exercise_id: int):
    with db() as conn:
        return get_exercise_records(conn, exercise_id)


@router.post("/api/training/sets")
def add_set(body: WorkoutSetIn):
    """给某次训练加一组。组号按该次训练里已有的组自动累加。"""
    with db() as conn:
        created = record_set(
            conn,
            session_id=body.session_id,
            exercise_id=body.exercise_id,
            reps=body.reps,
            weight_kg=body.weight_kg,
            distance_km=body.distance_km,
            duration_seconds=body.duration_seconds,
            note=body.note,
        )
        return {"set": created, "training": get_training_state(conn)}


@router.delete("/api/training/sets/{set_id}")
def remove_set(set_id: int):
    with db() as conn:
        return {"deleted": delete_set(conn, set_id), "training": get_training_state(conn)}
