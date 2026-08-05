"""个人健身模块。

负责健身记录的新增与汇总，不承担医疗判断或训练处方。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from backend.core.registry import LifeModule


def get_fitness_state(conn, recent_limit: int = 30) -> dict:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    today_row = conn.execute(
        """SELECT COUNT(*) AS count, COALESCE(SUM(duration_minutes), 0) AS minutes,
                  AVG(intensity) AS avg_intensity
           FROM fitness_sessions WHERE occurred_on = ?""",
        (today.isoformat(),),
    ).fetchone()
    week_row = conn.execute(
        """SELECT COUNT(*) AS count, COALESCE(SUM(duration_minutes), 0) AS minutes,
                  AVG(intensity) AS avg_intensity
           FROM fitness_sessions WHERE occurred_on BETWEEN ? AND ?""",
        (week_start.isoformat(), today.isoformat()),
    ).fetchone()
    recent = conn.execute(
        """SELECT * FROM fitness_sessions
           ORDER BY occurred_on DESC, id DESC LIMIT ?""",
        (recent_limit,),
    ).fetchall()
    return {
        "today": {
            "count": int(today_row["count"] or 0),
            "minutes": int(today_row["minutes"] or 0),
            "avg_intensity": round(float(today_row["avg_intensity"]), 1) if today_row["avg_intensity"] is not None else None,
        },
        "week": {
            "start_date": week_start.isoformat(),
            "count": int(week_row["count"] or 0),
            "minutes": int(week_row["minutes"] or 0),
            "avg_intensity": round(float(week_row["avg_intensity"]), 1) if week_row["avg_intensity"] is not None else None,
        },
        "recent": [dict(row) for row in recent],
    }


def record_workout(
    conn, *, occurred_on: str, activity: str, duration_minutes: int, intensity: int, note: str = ""
) -> dict:
    date.fromisoformat(occurred_on)
    cur = conn.execute(
        """INSERT INTO fitness_sessions
           (occurred_on, activity, duration_minutes, intensity, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (occurred_on, activity, duration_minutes, intensity, note.strip(), datetime.now().isoformat()),
    )
    return dict(conn.execute("SELECT * FROM fitness_sessions WHERE id = ?", (cur.lastrowid,)).fetchone())

SCHEMA = """
CREATE TABLE IF NOT EXISTS fitness_sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          occurred_on TEXT NOT NULL,
          activity TEXT NOT NULL CHECK (activity IN ('strength','cardio','sport','mobility','other')),
          duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0 AND duration_minutes <= 1440),
          intensity INTEGER NOT NULL CHECK (intensity BETWEEN 1 AND 10),
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
CREATE INDEX IF NOT EXISTS idx_fitness_date ON fitness_sessions(occurred_on);
"""


MODULE = LifeModule(
    key="fitness",
    label="个人健身",
    schema=SCHEMA,
    tables={
        "fitness_sessions": ["id", "occurred_on", "activity", "duration_minutes", "intensity", "note", "created_at"],
    },
    optional_tables=frozenset({"fitness_sessions"}),
)
