"""身体指标模块的 HTTP 接口。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.body import (
    delete_body_measurement,
    get_body_state,
    get_weight_trend,
    save_body_measurement,
)

router = APIRouter()


class BodyMeasurementIn(BaseModel):
    occurred_on: Optional[str] = None
    weight_kg: Optional[float] = Field(None, gt=0, le=500)
    body_fat_pct: Optional[float] = Field(None, gt=0, lt=100)
    neck_cm: Optional[float] = Field(None, gt=0, le=300)
    chest_cm: Optional[float] = Field(None, gt=0, le=300)
    waist_cm: Optional[float] = Field(None, gt=0, le=300)
    hip_cm: Optional[float] = Field(None, gt=0, le=300)
    arm_cm: Optional[float] = Field(None, gt=0, le=300)
    thigh_cm: Optional[float] = Field(None, gt=0, le=300)
    note: str = Field("", max_length=120)


@router.get("/api/body")
def body_state():
    with db() as conn:
        return get_body_state(conn)


@router.get("/api/body/trend")
def body_trend(days: int = 90):
    with db() as conn:
        return get_weight_trend(conn, days)


@router.post("/api/body/measurements")
def add_body_measurement(body: BodyMeasurementIn):
    """保存某一天的身体指标。同一天再次提交视为更新。"""
    from datetime import date

    payload = body.model_dump()
    occurred_on = payload.pop("occurred_on") or date.today().isoformat()
    note = payload.pop("note")
    weight_kg = payload.pop("weight_kg")
    body_fat_pct = payload.pop("body_fat_pct")
    with db() as conn:
        measurement = save_body_measurement(
            conn, occurred_on=occurred_on, weight_kg=weight_kg,
            body_fat_pct=body_fat_pct, note=note, **payload,
        )
        return {"measurement": measurement, "body": get_body_state(conn)}


@router.delete("/api/body/measurements/{measurement_id}")
def remove_body_measurement(measurement_id: int):
    with db() as conn:
        return {
            "deleted": delete_body_measurement(conn, measurement_id),
            "body": get_body_state(conn),
        }
