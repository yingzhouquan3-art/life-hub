"""学习与专注模块。

学习时长只表示投入时间，不能推导知识掌握程度。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from backend.core.registry import LifeModule


def get_study_state(conn, recent_limit: int = 30) -> dict:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    today_row = conn.execute(
        """SELECT COUNT(*) AS count, COALESCE(SUM(duration_minutes), 0) AS minutes,
                  AVG(focus) AS avg_focus
           FROM study_sessions WHERE occurred_on = ?""",
        (today.isoformat(),),
    ).fetchone()
    week_row = conn.execute(
        """SELECT COUNT(*) AS count, COALESCE(SUM(duration_minutes), 0) AS minutes,
                  AVG(focus) AS avg_focus
           FROM study_sessions WHERE occurred_on BETWEEN ? AND ?""",
        (week_start.isoformat(), today.isoformat()),
    ).fetchone()
    recent = conn.execute(
        """SELECT * FROM study_sessions
           ORDER BY occurred_on DESC, id DESC LIMIT ?""",
        (recent_limit,),
    ).fetchall()
    return {
        "today": {
            "count": int(today_row["count"] or 0),
            "minutes": int(today_row["minutes"] or 0),
            "avg_focus": round(float(today_row["avg_focus"]), 1) if today_row["avg_focus"] is not None else None,
        },
        "week": {
            "start_date": week_start.isoformat(),
            "count": int(week_row["count"] or 0),
            "minutes": int(week_row["minutes"] or 0),
            "avg_focus": round(float(week_row["avg_focus"]), 1) if week_row["avg_focus"] is not None else None,
        },
        "recent": [dict(row) for row in recent],
    }


def record_study_session(
    conn, *, occurred_on: str, subject: str, duration_minutes: int,
    focus: int, note: str = "",
) -> dict:
    date.fromisoformat(occurred_on)
    cur = conn.execute(
        """INSERT INTO study_sessions
           (occurred_on, subject, duration_minutes, focus, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (occurred_on, subject.strip(), duration_minutes, focus, note.strip(), datetime.now().isoformat()),
    )
    return dict(conn.execute("SELECT * FROM study_sessions WHERE id = ?", (cur.lastrowid,)).fetchone())

SCHEMA = """
CREATE TABLE IF NOT EXISTS study_sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          occurred_on TEXT NOT NULL,
          subject TEXT NOT NULL,
          duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0 AND duration_minutes <= 1440),
          focus INTEGER NOT NULL CHECK (focus BETWEEN 1 AND 5),
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
CREATE INDEX IF NOT EXISTS idx_study_date ON study_sessions(occurred_on);
"""


MODULE = LifeModule(
    key="study",
    label="学习与专注",
    schema=SCHEMA,
    tables={
        "study_sessions": ["id", "occurred_on", "subject", "duration_minutes", "focus", "note", "created_at"],
    },
    optional_tables=frozenset({"study_sessions"}),
)
