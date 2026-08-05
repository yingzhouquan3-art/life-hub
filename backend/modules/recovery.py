"""睡眠与恢复模块。

每天至多一条记录，同日再次保存视为更新；不依据记录输出医疗判断。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from backend.core.registry import LifeModule


def get_recovery_state(conn, recent_limit: int = 30) -> dict:
    today_key = date.today().isoformat()
    week_start = (date.today() - timedelta(days=6)).isoformat()
    today_row = conn.execute(
        "SELECT * FROM recovery_checkins WHERE occurred_on = ?", (today_key,)
    ).fetchone()
    latest_row = conn.execute(
        "SELECT * FROM recovery_checkins ORDER BY occurred_on DESC, id DESC LIMIT 1"
    ).fetchone()
    week_row = conn.execute(
        """SELECT COUNT(*) AS count, AVG(sleep_hours) AS sleep_hours,
                  AVG(sleep_quality) AS sleep_quality, AVG(energy) AS energy, AVG(mood) AS mood,
                  COUNT(sleep_hours) AS sleep_known
           FROM recovery_checkins WHERE occurred_on BETWEEN ? AND ?""",
        (week_start, today_key),
    ).fetchone()
    recent = conn.execute(
        """SELECT * FROM recovery_checkins
           ORDER BY occurred_on DESC, id DESC LIMIT ?""",
        (recent_limit,),
    ).fetchall()
    def average(name: str) -> Optional[float]:
        return round(float(week_row[name]), 1) if week_row[name] is not None else None
    return {
        "today": dict(today_row) if today_row else None,
        "latest": dict(latest_row) if latest_row else None,
        "week": {
            "start_date": week_start,
            "count": int(week_row["count"] or 0),
            "sleep_hours": average("sleep_hours"),
            "sleep_quality": average("sleep_quality"),
            "energy": average("energy"),
            "mood": average("mood"),
            "sleep_known": int(week_row["sleep_known"] or 0),
        },
        "recent": [dict(row) for row in recent],
    }


def save_recovery_checkin(
    conn, *, occurred_on: str, sleep_hours: Optional[float] = None,
    sleep_quality: Optional[int] = None, energy: Optional[int] = None,
    mood: Optional[int] = None, note: str = "",
) -> dict:
    date.fromisoformat(occurred_on)
    if all(value is None for value in (sleep_hours, sleep_quality, energy, mood)) and not note.strip():
        raise HTTPException(400, "至少填写一项恢复状态")
    conn.execute(
        """INSERT INTO recovery_checkins
           (occurred_on, sleep_hours, sleep_quality, energy, mood, note, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(occurred_on) DO UPDATE SET
             sleep_hours = excluded.sleep_hours,
             sleep_quality = excluded.sleep_quality,
             energy = excluded.energy,
             mood = excluded.mood,
             note = excluded.note,
             updated_at = excluded.updated_at""",
        (occurred_on, sleep_hours, sleep_quality, energy, mood, note.strip(), datetime.now().isoformat()),
    )
    return dict(conn.execute(
        "SELECT * FROM recovery_checkins WHERE occurred_on = ?", (occurred_on,)
    ).fetchone())

SCHEMA = """
CREATE TABLE IF NOT EXISTS recovery_checkins (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          occurred_on TEXT NOT NULL UNIQUE,
          sleep_hours REAL CHECK (sleep_hours IS NULL OR (sleep_hours >= 0 AND sleep_hours <= 24)),
          sleep_quality INTEGER CHECK (sleep_quality IS NULL OR sleep_quality BETWEEN 1 AND 5),
          energy INTEGER CHECK (energy IS NULL OR energy BETWEEN 1 AND 5),
          mood INTEGER CHECK (mood IS NULL OR mood BETWEEN 1 AND 5),
          note TEXT DEFAULT '',
          updated_at TEXT NOT NULL
        );
CREATE INDEX IF NOT EXISTS idx_recovery_date ON recovery_checkins(occurred_on);
"""


MODULE = LifeModule(
    key="recovery",
    label="睡眠与恢复",
    schema=SCHEMA,
    tables={
        "recovery_checkins": ["id", "occurred_on", "sleep_hours", "sleep_quality", "energy", "mood", "note", "updated_at"],
    },
    optional_tables=frozenset({"recovery_checkins"}),
)
