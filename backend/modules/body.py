"""身体指标模块。

体重、体脂与围度。它是健身与饮食唯一的共同锚点：
练了多少、吃了多少，最终都落在这几个数字上。

- 每天至多一条记录，同一天再次保存视为更新；
- 所有指标都可以留空，**未填写代表未知，不能当作零**；
- 变化量只描述两次记录之间的差值，不解释原因，也不判断好坏。
  体重上升可能是脱水后补水、可能是增肌、也可能只是称的时间不同。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException

from backend.core.registry import LifeModule

# 围度字段与它们的中文名。加新围度只要改这里。
GIRTH_FIELDS = {
    "neck_cm": "颈围",
    "chest_cm": "胸围",
    "waist_cm": "腰围",
    "hip_cm": "臀围",
    "arm_cm": "上臂围",
    "thigh_cm": "大腿围",
}

METRIC_FIELDS = ("weight_kg", "body_fat_pct", *GIRTH_FIELDS)


def save_body_measurement(
    conn, *, occurred_on: str, weight_kg: Optional[float] = None,
    body_fat_pct: Optional[float] = None, note: str = "", **girths,
) -> dict:
    """保存或更新某一天的身体指标。

    一项都没填就拒绝：空记录既占位置又会让「有没有量过」失去意义。
    """
    date.fromisoformat(occurred_on)
    unknown = set(girths) - set(GIRTH_FIELDS)
    if unknown:
        raise HTTPException(400, f"未知的围度字段：{sorted(unknown)}")

    values = {"weight_kg": weight_kg, "body_fat_pct": body_fat_pct}
    values.update({field: girths.get(field) for field in GIRTH_FIELDS})
    if all(value is None for value in values.values()) and not note.strip():
        raise HTTPException(400, "至少填写一项身体指标")
    for field, value in values.items():
        if value is not None and value <= 0:
            raise HTTPException(400, f"{field} 必须大于 0")
    if body_fat_pct is not None and body_fat_pct >= 100:
        raise HTTPException(400, "体脂率必须小于 100")

    columns = ["occurred_on", *values, "note", "updated_at"]
    placeholders = ", ".join("?" for _ in columns)
    updates = ", ".join(f"{name} = excluded.{name}" for name in [*values, "note", "updated_at"])
    conn.execute(
        f"""INSERT INTO body_measurements ({', '.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(occurred_on) DO UPDATE SET {updates}""",
        (occurred_on, *values.values(), note.strip(), datetime.now().isoformat()),
    )
    return dict(conn.execute(
        "SELECT * FROM body_measurements WHERE occurred_on = ?", (occurred_on,)
    ).fetchone())


def delete_body_measurement(conn, measurement_id: int) -> int:
    if not conn.execute(
        "SELECT 1 FROM body_measurements WHERE id = ?", (measurement_id,)
    ).fetchone():
        raise HTTPException(404, "body measurement not found")
    conn.execute("DELETE FROM body_measurements WHERE id = ?", (measurement_id,))
    return measurement_id


def _latest_value(conn, field: str, before: Optional[str] = None) -> Optional[dict]:
    clause = "AND occurred_on < ?" if before else ""
    params = (before,) if before else ()
    row = conn.execute(
        f"""SELECT occurred_on, {field} AS value FROM body_measurements
            WHERE {field} IS NOT NULL {clause}
            ORDER BY occurred_on DESC LIMIT 1""",
        params,
    ).fetchone()
    return {"occurred_on": row["occurred_on"], "value": float(row["value"])} if row else None


def get_body_state(conn, recent_limit: int = 30) -> dict:
    """最近一次记录、与上一次的差值，以及近期趋势。

    差值只描述两次记录之间的变化，不解释原因，也不判断好坏。
    """
    latest_row = conn.execute(
        "SELECT * FROM body_measurements ORDER BY occurred_on DESC LIMIT 1"
    ).fetchone()
    latest = dict(latest_row) if latest_row else None

    changes = {}
    for field in METRIC_FIELDS:
        current = _latest_value(conn, field)
        if not current:
            continue
        previous = _latest_value(conn, field, before=current["occurred_on"])
        changes[field] = {
            "value": current["value"],
            "measured_on": current["occurred_on"],
            "previous": previous["value"] if previous else None,
            "previous_on": previous["occurred_on"] if previous else None,
            "delta": round(current["value"] - previous["value"], 2) if previous else None,
            "days_between": (
                (date.fromisoformat(current["occurred_on"])
                 - date.fromisoformat(previous["occurred_on"])).days if previous else None
            ),
        }

    recent = conn.execute(
        "SELECT * FROM body_measurements ORDER BY occurred_on DESC LIMIT ?",
        (max(1, min(recent_limit, 200)),),
    ).fetchall()

    days_since = None
    if latest:
        days_since = (date.today() - date.fromisoformat(latest["occurred_on"])).days

    return {
        "latest": latest,
        "changes": changes,
        "days_since_last": days_since,
        "girth_labels": GIRTH_FIELDS,
        "recent": [dict(row) for row in recent],
        "measured_count": conn.execute(
            "SELECT COUNT(*) AS count FROM body_measurements"
        ).fetchone()["count"],
    }


def get_weight_trend(conn, days: int = 90) -> dict:
    """体重曲线与七日均值。

    七日均值用来压掉每天的水分波动；它是一个平滑值，不是「真实体重」。
    """
    if days < 1 or days > 3650:
        raise HTTPException(400, "days out of range")
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    rows = conn.execute(
        """SELECT occurred_on, weight_kg FROM body_measurements
           WHERE weight_kg IS NOT NULL AND occurred_on >= ?
           ORDER BY occurred_on""",
        (start,),
    ).fetchall()

    points = []
    window: list[float] = []
    for row in rows:
        window.append(float(row["weight_kg"]))
        if len(window) > 7:
            window.pop(0)
        points.append({
            "occurred_on": row["occurred_on"],
            "weight_kg": round(float(row["weight_kg"]), 2),
            "average_7": round(sum(window) / len(window), 2),
        })

    return {
        "days": days,
        "start_date": start,
        "points": points,
        "count": len(points),
        "note": "没有数据点只表示这段时间没有称过，不能推导体重没有变化。",
    }


SCHEMA = """
CREATE TABLE IF NOT EXISTS body_measurements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_on TEXT NOT NULL UNIQUE,
  weight_kg REAL CHECK (weight_kg IS NULL OR weight_kg > 0),
  body_fat_pct REAL CHECK (body_fat_pct IS NULL OR (body_fat_pct > 0 AND body_fat_pct < 100)),
  neck_cm REAL CHECK (neck_cm IS NULL OR neck_cm > 0),
  chest_cm REAL CHECK (chest_cm IS NULL OR chest_cm > 0),
  waist_cm REAL CHECK (waist_cm IS NULL OR waist_cm > 0),
  hip_cm REAL CHECK (hip_cm IS NULL OR hip_cm > 0),
  arm_cm REAL CHECK (arm_cm IS NULL OR arm_cm > 0),
  thigh_cm REAL CHECK (thigh_cm IS NULL OR thigh_cm > 0),
  note TEXT DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_body_date ON body_measurements(occurred_on);
"""

MODULE = LifeModule(
    key="body",
    label="身体指标",
    schema=SCHEMA,
    tables={
        "body_measurements": ["id", "occurred_on", "weight_kg", "body_fat_pct", "neck_cm",
                              "chest_cm", "waist_cm", "hip_cm", "arm_cm", "thigh_cm",
                              "note", "updated_at"],
    },
    optional_tables=frozenset({"body_measurements"}),
)
