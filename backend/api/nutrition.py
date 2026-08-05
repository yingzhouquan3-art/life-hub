"""个人饮食模块的 HTTP 接口。"""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.nutrition import get_nutrition_state, record_meal
from backend.views.overview import get_life_overview

router = APIRouter()


class NutritionEntryIn(BaseModel):
    occurred_on: Optional[str] = None
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    name: str = Field(..., min_length=1, max_length=80)
    calories: Optional[float] = Field(None, ge=0, le=10000)
    protein_g: Optional[float] = Field(None, ge=0, le=1000)
    water_ml: Optional[float] = Field(None, ge=0, le=10000)
    note: str = Field("", max_length=120)


@router.get("/api/nutrition")
def nutrition_state():
    with db() as conn:
        return get_nutrition_state(conn)


@router.post("/api/nutrition/entries")
def add_nutrition_entry(body: NutritionEntryIn):
    with db() as conn:
        entry = record_meal(
            conn,
            occurred_on=body.occurred_on or date.today().isoformat(),
            meal_type=body.meal_type,
            name=body.name,
            calories=body.calories,
            protein_g=body.protein_g,
            water_ml=body.water_ml,
            note=body.note,
        )
        return {"entry": entry, "nutrition": get_nutrition_state(conn), "life": get_life_overview(conn)}


@router.delete("/api/nutrition/entries/{entry_id}")
def delete_nutrition_entry(entry_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM nutrition_entries WHERE id = ?", (entry_id,)).fetchone():
            raise HTTPException(404, "nutrition entry not found")
        conn.execute("DELETE FROM nutrition_entries WHERE id = ?", (entry_id,))
        return {"deleted": entry_id, "nutrition": get_nutrition_state(conn), "life": get_life_overview(conn)}
