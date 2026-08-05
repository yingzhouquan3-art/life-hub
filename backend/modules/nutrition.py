"""个人饮食模块。

营养数值允许留空；未填写代表未知，不能当作零摄入。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from backend.core.registry import LifeModule


def get_nutrition_state(conn, recent_limit: int = 30) -> dict:
    today_key = date.today().isoformat()
    today_row = conn.execute(
        """SELECT COUNT(*) AS count,
                  COALESCE(SUM(calories), 0) AS calories,
                  COALESCE(SUM(protein_g), 0) AS protein_g,
                  COALESCE(SUM(water_ml), 0) AS water_ml,
                  COUNT(calories) AS calories_known,
                  COUNT(protein_g) AS protein_known,
                  COUNT(water_ml) AS water_known
           FROM nutrition_entries WHERE occurred_on = ?""",
        (today_key,),
    ).fetchone()
    recent = conn.execute(
        """SELECT * FROM nutrition_entries
           ORDER BY occurred_on DESC, id DESC LIMIT ?""",
        (recent_limit,),
    ).fetchall()
    return {
        "today": {
            "count": int(today_row["count"] or 0),
            "calories": round(float(today_row["calories"] or 0), 1),
            "protein_g": round(float(today_row["protein_g"] or 0), 1),
            "water_ml": round(float(today_row["water_ml"] or 0), 1),
            "calories_known": int(today_row["calories_known"] or 0),
            "protein_known": int(today_row["protein_known"] or 0),
            "water_known": int(today_row["water_known"] or 0),
        },
        "recent": [dict(row) for row in recent],
    }


def record_meal(
    conn, *, occurred_on: str, meal_type: str, name: str,
    calories: Optional[float] = None, protein_g: Optional[float] = None,
    water_ml: Optional[float] = None, note: str = "",
) -> dict:
    date.fromisoformat(occurred_on)
    cur = conn.execute(
        """INSERT INTO nutrition_entries
           (occurred_on, meal_type, name, calories, protein_g, water_ml, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (occurred_on, meal_type, name.strip(), calories, protein_g, water_ml, note.strip(), datetime.now().isoformat()),
    )
    return dict(conn.execute("SELECT * FROM nutrition_entries WHERE id = ?", (cur.lastrowid,)).fetchone())

SCHEMA = """
CREATE TABLE IF NOT EXISTS nutrition_entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          occurred_on TEXT NOT NULL,
          meal_type TEXT NOT NULL CHECK (meal_type IN ('breakfast','lunch','dinner','snack')),
          name TEXT NOT NULL,
          calories REAL CHECK (calories IS NULL OR calories >= 0),
          protein_g REAL CHECK (protein_g IS NULL OR protein_g >= 0),
          water_ml REAL CHECK (water_ml IS NULL OR water_ml >= 0),
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
CREATE INDEX IF NOT EXISTS idx_nutrition_date ON nutrition_entries(occurred_on);
"""


MODULE = LifeModule(
    key="nutrition",
    label="个人饮食",
    schema=SCHEMA,
    tables={
        "nutrition_entries": ["id", "occurred_on", "meal_type", "name", "calories", "protein_g", "water_ml", "note", "created_at"],
    },
    optional_tables=frozenset({"nutrition_entries"}),
)
