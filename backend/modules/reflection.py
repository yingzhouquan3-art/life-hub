"""日记与复盘模块。

每个日期最多一条每日回顾，同日再次保存代表更新。
周度快照只汇总各模块已经存在的记录，不补全缺失数据；
其中的零只代表没有记录，不能推导现实中没有发生。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException

from backend.core.dates import get_week_bounds
from backend.core.registry import LifeModule


def get_weekly_snapshot(conn, anchor: Optional[date] = None) -> dict:
    anchor_day = anchor or date.today()
    week_start, week_end = get_week_bounds(anchor_day)
    start_key, end_key = week_start.isoformat(), week_end.isoformat()
    finance = conn.execute(
        """SELECT
             COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) AS income,
             COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0) AS expense,
             COUNT(*) AS count
           FROM transactions WHERE occurred_on BETWEEN ? AND ?""",
        (start_key, end_key),
    ).fetchone()
    fitness = conn.execute(
        """SELECT COUNT(*) AS count, COALESCE(SUM(duration_minutes), 0) AS minutes
           FROM fitness_sessions WHERE occurred_on BETWEEN ? AND ?""",
        (start_key, end_key),
    ).fetchone()
    nutrition = conn.execute(
        """SELECT COUNT(*) AS count, COUNT(calories) AS calories_known,
                  COALESCE(SUM(water_ml), 0) AS water_ml
           FROM nutrition_entries WHERE occurred_on BETWEEN ? AND ?""",
        (start_key, end_key),
    ).fetchone()
    recovery = conn.execute(
        """SELECT COUNT(*) AS count, AVG(sleep_hours) AS sleep_hours,
                  AVG(energy) AS energy, AVG(mood) AS mood,
                  COUNT(sleep_hours) AS sleep_known
           FROM recovery_checkins WHERE occurred_on BETWEEN ? AND ?""",
        (start_key, end_key),
    ).fetchone()
    study = conn.execute(
        """SELECT COUNT(*) AS count, COALESCE(SUM(duration_minutes), 0) AS minutes,
                  AVG(focus) AS avg_focus
           FROM study_sessions WHERE occurred_on BETWEEN ? AND ?""",
        (start_key, end_key),
    ).fetchone()
    tasks = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done
           FROM personal_tasks WHERE due_on BETWEEN ? AND ?""",
        (start_key, end_key),
    ).fetchone()
    habits = conn.execute(
        """SELECT COUNT(*) AS checkins, COUNT(DISTINCT habit_id) AS habits,
                  COUNT(DISTINCT occurred_on) AS active_days
           FROM habit_checkins WHERE occurred_on BETWEEN ? AND ?""",
        (start_key, end_key),
    ).fetchone()
    reflections = conn.execute(
        "SELECT COUNT(*) AS count FROM daily_reflections WHERE occurred_on BETWEEN ? AND ?",
        (start_key, end_key),
    ).fetchone()
    def avg(row, key: str) -> Optional[float]:
        return round(float(row[key]), 1) if row[key] is not None else None
    return {
        "week": {"start_date": start_key, "end_date": end_key},
        "finance": {
            "income": round(float(finance["income"] or 0), 2),
            "expense": round(float(finance["expense"] or 0), 2),
            "transaction_count": int(finance["count"] or 0),
        },
        "fitness": {"count": int(fitness["count"] or 0), "minutes": int(fitness["minutes"] or 0)},
        "nutrition": {
            "count": int(nutrition["count"] or 0),
            "calories_known": int(nutrition["calories_known"] or 0),
            "water_ml": round(float(nutrition["water_ml"] or 0), 1),
        },
        "recovery": {
            "count": int(recovery["count"] or 0),
            "sleep_hours": avg(recovery, "sleep_hours"),
            "sleep_known": int(recovery["sleep_known"] or 0),
            "energy": avg(recovery, "energy"),
            "mood": avg(recovery, "mood"),
        },
        "study": {
            "count": int(study["count"] or 0),
            "minutes": int(study["minutes"] or 0),
            "avg_focus": avg(study, "avg_focus"),
        },
        "rhythm": {
            "tasks_total": int(tasks["total"] or 0),
            "tasks_done": int(tasks["done"] or 0),
            "habit_checkins": int(habits["checkins"] or 0),
            "habits_practiced": int(habits["habits"] or 0),
            "habit_active_days": int(habits["active_days"] or 0),
        },
        "reflection_count": int(reflections["count"] or 0),
    }


def get_reflection_state(conn, anchor_date: Optional[str] = None) -> dict:
    anchor = date.fromisoformat(anchor_date) if anchor_date else date.today()
    selected = conn.execute(
        "SELECT * FROM daily_reflections WHERE occurred_on = ?", (anchor.isoformat(),)
    ).fetchone()
    recent = conn.execute(
        "SELECT * FROM daily_reflections ORDER BY occurred_on DESC, id DESC LIMIT 30"
    ).fetchall()
    return {
        "date": anchor.isoformat(),
        "selected": dict(selected) if selected else None,
        "weekly": get_weekly_snapshot(conn, anchor),
        "recent": [dict(row) for row in recent],
    }


def save_daily_reflection(
    conn, *, occurred_on: str, highlight: str = "", challenge: str = "",
    gratitude: str = "", note: str = "",
) -> dict:
    date.fromisoformat(occurred_on)
    values = [highlight.strip(), challenge.strip(), gratitude.strip(), note.strip()]
    if not any(values):
        raise HTTPException(400, "每日回顾至少填写一项")
    conn.execute(
        """INSERT INTO daily_reflections
           (occurred_on, highlight, challenge, gratitude, note, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(occurred_on) DO UPDATE SET
             highlight = excluded.highlight,
             challenge = excluded.challenge,
             gratitude = excluded.gratitude,
             note = excluded.note,
             updated_at = excluded.updated_at""",
        (occurred_on, *values, datetime.now().isoformat()),
    )
    return dict(conn.execute(
        "SELECT * FROM daily_reflections WHERE occurred_on = ?", (occurred_on,)
    ).fetchone())

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_reflections (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          occurred_on TEXT NOT NULL UNIQUE,
          highlight TEXT DEFAULT '',
          challenge TEXT DEFAULT '',
          gratitude TEXT DEFAULT '',
          note TEXT DEFAULT '',
          updated_at TEXT NOT NULL
        );
CREATE INDEX IF NOT EXISTS idx_reflection_date ON daily_reflections(occurred_on);
"""


MODULE = LifeModule(
    key="reflection",
    label="日记与复盘",
    schema=SCHEMA,
    tables={
        "daily_reflections": ["id", "occurred_on", "highlight", "challenge", "gratitude", "note", "updated_at"],
    },
    optional_tables=frozenset({"daily_reflections"}),
)
