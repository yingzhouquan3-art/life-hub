"""个人健身模块。

记录已经完成的训练：一次训练由若干组构成，每组落到动作库里的一个动作。
由此可以算出容量与个人纪录。

纪录只描述**已经记录过的最好一次**，不代表能力上限；
一段时间没刷新也不说明退步，可能只是没练这个动作。
本模块不承担医疗判断，也不给训练处方。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException

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

# ---------- 动作库 ----------

# 首次建库时预置的常见动作。只是起点，随时可以归档或自己加。
DEFAULT_EXERCISES = (
    ("深蹲", "strength", "腿"),
    ("硬拉", "strength", "背 / 腿"),
    ("卧推", "strength", "胸"),
    ("引体向上", "strength", "背"),
    ("推举", "strength", "肩"),
    ("划船", "strength", "背"),
    ("跑步", "cardio", "全身"),
    ("骑行", "cardio", "腿"),
    ("游泳", "cardio", "全身"),
    ("拉伸", "mobility", "全身"),
)


def list_exercises(conn, include_archived: bool = False) -> list[dict]:
    clause = "" if include_archived else "WHERE is_active = 1"
    rows = conn.execute(
        f"SELECT * FROM exercises {clause} ORDER BY kind, name"
    ).fetchall()
    return [dict(row) for row in rows]


def create_exercise(conn, *, name: str, kind: str = "strength", muscle_group: str = "") -> dict:
    """新增一个动作。同名动作只允许一个，避免纪录被拆成两半。"""
    clean = name.strip()
    if not clean:
        raise HTTPException(400, "动作名称不能为空")
    if kind not in ("strength", "cardio", "mobility"):
        raise HTTPException(400, "kind must be strength, cardio or mobility")
    existing = conn.execute("SELECT * FROM exercises WHERE name = ?", (clean,)).fetchone()
    if existing:
        if not existing["is_active"]:
            conn.execute("UPDATE exercises SET is_active = 1 WHERE id = ?", (existing["id"],))
            return dict(conn.execute(
                "SELECT * FROM exercises WHERE id = ?", (existing["id"],)
            ).fetchone())
        raise HTTPException(409, f"动作「{clean}」已经存在")
    cur = conn.execute(
        """INSERT INTO exercises (name, kind, muscle_group, is_active, created_at)
           VALUES (?, ?, ?, 1, ?)""",
        (clean, kind, muscle_group.strip(), datetime.now().isoformat()),
    )
    return dict(conn.execute("SELECT * FROM exercises WHERE id = ?", (cur.lastrowid,)).fetchone())


def archive_exercise(conn, exercise_id: int) -> dict:
    """归档一个动作。已有的组数记录与纪录全部保留。"""
    if not conn.execute("SELECT 1 FROM exercises WHERE id = ?", (exercise_id,)).fetchone():
        raise HTTPException(404, "exercise not found")
    conn.execute("UPDATE exercises SET is_active = 0 WHERE id = ?", (exercise_id,))
    return dict(conn.execute("SELECT * FROM exercises WHERE id = ?", (exercise_id,)).fetchone())


# ---------- 组数 ----------

def record_set(
    conn, *, session_id: int, exercise_id: int, reps: Optional[int] = None,
    weight_kg: Optional[float] = None, distance_km: Optional[float] = None,
    duration_seconds: Optional[int] = None, note: str = "",
) -> dict:
    """记一组。力量动作填次数与重量，有氧填距离与用时，都可以只填一部分。"""
    if not conn.execute("SELECT 1 FROM fitness_sessions WHERE id = ?", (session_id,)).fetchone():
        raise HTTPException(404, "fitness session not found")
    if not conn.execute("SELECT 1 FROM exercises WHERE id = ?", (exercise_id,)).fetchone():
        raise HTTPException(404, "exercise not found")
    if all(value is None for value in (reps, weight_kg, distance_km, duration_seconds)):
        raise HTTPException(400, "至少填写次数、重量、距离或用时中的一项")
    for label, value in (("reps", reps), ("weight_kg", weight_kg),
                         ("distance_km", distance_km), ("duration_seconds", duration_seconds)):
        if value is not None and value <= 0:
            raise HTTPException(400, f"{label} 必须大于 0")

    next_number = conn.execute(
        "SELECT COALESCE(MAX(set_number), 0) + 1 AS n FROM workout_sets WHERE session_id = ?",
        (session_id,),
    ).fetchone()["n"]
    cur = conn.execute(
        """INSERT INTO workout_sets
           (session_id, exercise_id, set_number, reps, weight_kg, distance_km,
            duration_seconds, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, exercise_id, next_number, reps, weight_kg, distance_km,
         duration_seconds, note.strip(), datetime.now().isoformat()),
    )
    return dict(conn.execute("SELECT * FROM workout_sets WHERE id = ?", (cur.lastrowid,)).fetchone())


def delete_set(conn, set_id: int) -> int:
    if not conn.execute("SELECT 1 FROM workout_sets WHERE id = ?", (set_id,)).fetchone():
        raise HTTPException(404, "workout set not found")
    conn.execute("DELETE FROM workout_sets WHERE id = ?", (set_id,))
    return set_id


def get_session_sets(conn, session_id: int) -> list[dict]:
    rows = conn.execute(
        """SELECT s.*, e.name AS exercise_name, e.kind AS exercise_kind
           FROM workout_sets s JOIN exercises e ON e.id = s.exercise_id
           WHERE s.session_id = ? ORDER BY s.set_number""",
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def session_volume(conn, session_id: int) -> float:
    """这次训练的总容量 = Σ 次数 × 重量。只统计两项都填了的组。"""
    row = conn.execute(
        """SELECT COALESCE(SUM(reps * weight_kg), 0) AS volume FROM workout_sets
           WHERE session_id = ? AND reps IS NOT NULL AND weight_kg IS NOT NULL""",
        (session_id,),
    ).fetchone()
    return round(float(row["volume"] or 0), 1)


# ---------- 个人纪录 ----------

def estimated_one_rep_max(reps: int, weight_kg: float) -> float:
    """Epley 公式估算的 1RM。

    这是一个**估算**，不是实测。次数越多误差越大，超过 10 次基本不可参考。
    """
    return round(weight_kg * (1 + reps / 30), 1)


def get_exercise_records(conn, exercise_id: int) -> dict:
    """某个动作的个人纪录。

    纪录只描述**已经记录过的最好一次**，不代表能力上限，
    也不因为一段时间没刷新就说明退步——可能只是没练这个动作。
    """
    exercise = conn.execute("SELECT * FROM exercises WHERE id = ?", (exercise_id,)).fetchone()
    if not exercise:
        raise HTTPException(404, "exercise not found")

    heaviest = conn.execute(
        """SELECT s.weight_kg, s.reps, f.occurred_on FROM workout_sets s
           JOIN fitness_sessions f ON f.id = s.session_id
           WHERE s.exercise_id = ? AND s.weight_kg IS NOT NULL
           ORDER BY s.weight_kg DESC, s.reps DESC LIMIT 1""",
        (exercise_id,),
    ).fetchone()
    most_reps = conn.execute(
        """SELECT s.reps, s.weight_kg, f.occurred_on FROM workout_sets s
           JOIN fitness_sessions f ON f.id = s.session_id
           WHERE s.exercise_id = ? AND s.reps IS NOT NULL
           ORDER BY s.reps DESC, s.weight_kg DESC LIMIT 1""",
        (exercise_id,),
    ).fetchone()
    farthest = conn.execute(
        """SELECT s.distance_km, s.duration_seconds, f.occurred_on FROM workout_sets s
           JOIN fitness_sessions f ON f.id = s.session_id
           WHERE s.exercise_id = ? AND s.distance_km IS NOT NULL
           ORDER BY s.distance_km DESC LIMIT 1""",
        (exercise_id,),
    ).fetchone()

    best_estimate = None
    for row in conn.execute(
        """SELECT s.reps, s.weight_kg, f.occurred_on FROM workout_sets s
           JOIN fitness_sessions f ON f.id = s.session_id
           WHERE s.exercise_id = ? AND s.reps IS NOT NULL AND s.weight_kg IS NOT NULL""",
        (exercise_id,),
    ).fetchall():
        value = estimated_one_rep_max(int(row["reps"]), float(row["weight_kg"]))
        if best_estimate is None or value > best_estimate["value"]:
            best_estimate = {
                "value": value, "reps": int(row["reps"]),
                "weight_kg": float(row["weight_kg"]), "occurred_on": row["occurred_on"],
            }

    return {
        "exercise": dict(exercise),
        "heaviest": dict(heaviest) if heaviest else None,
        "most_reps": dict(most_reps) if most_reps else None,
        "farthest": dict(farthest) if farthest else None,
        "estimated_one_rep_max": best_estimate,
        "set_count": conn.execute(
            "SELECT COUNT(*) AS count FROM workout_sets WHERE exercise_id = ?", (exercise_id,)
        ).fetchone()["count"],
        "note": "纪录只描述已经记录过的最好一次，不代表能力上限。",
    }


def get_training_state(conn, recent_limit: int = 10) -> dict:
    """动作库、最近几次训练的组数与容量、以及各动作的纪录。"""
    exercises = list_exercises(conn)
    sessions = conn.execute(
        "SELECT * FROM fitness_sessions ORDER BY occurred_on DESC, id DESC LIMIT ?",
        (max(1, min(recent_limit, 60)),),
    ).fetchall()

    recent = []
    for row in sessions:
        session = dict(row)
        session["sets"] = get_session_sets(conn, session["id"])
        session["volume"] = session_volume(conn, session["id"])
        recent.append(session)

    week_start = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    week_volume = conn.execute(
        """SELECT COALESCE(SUM(s.reps * s.weight_kg), 0) AS volume FROM workout_sets s
           JOIN fitness_sessions f ON f.id = s.session_id
           WHERE f.occurred_on >= ? AND s.reps IS NOT NULL AND s.weight_kg IS NOT NULL""",
        (week_start,),
    ).fetchone()["volume"]

    records = [
        get_exercise_records(conn, exercise["id"])
        for exercise in exercises
        if conn.execute(
            "SELECT 1 FROM workout_sets WHERE exercise_id = ? LIMIT 1", (exercise["id"],)
        ).fetchone()
    ]

    return {
        "exercises": exercises,
        "recent_sessions": recent,
        "week": {"start_date": week_start, "volume": round(float(week_volume or 0), 1)},
        "records": records,
    }


def seed_default_exercises(conn) -> None:
    """动作库为空时预置一批常见动作，否则这个功能一上来就没法用。"""
    if conn.execute("SELECT 1 FROM exercises LIMIT 1").fetchone():
        return
    now = datetime.now().isoformat()
    conn.executemany(
        """INSERT INTO exercises (name, kind, muscle_group, is_active, created_at)
           VALUES (?, ?, ?, 1, ?)""",
        [(name, kind, group, now) for name, kind, group in DEFAULT_EXERCISES],
    )


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
CREATE TABLE IF NOT EXISTS exercises (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL DEFAULT 'strength' CHECK (kind IN ('strength','cardio','mobility')),
  muscle_group TEXT DEFAULT '',
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workout_sets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES fitness_sessions(id) ON DELETE CASCADE,
  exercise_id INTEGER NOT NULL REFERENCES exercises(id),
  set_number INTEGER NOT NULL CHECK (set_number > 0),
  reps INTEGER CHECK (reps IS NULL OR reps > 0),
  weight_kg REAL CHECK (weight_kg IS NULL OR weight_kg > 0),
  distance_km REAL CHECK (distance_km IS NULL OR distance_km > 0),
  duration_seconds INTEGER CHECK (duration_seconds IS NULL OR duration_seconds > 0),
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fitness_date ON fitness_sessions(occurred_on);
CREATE INDEX IF NOT EXISTS idx_workout_set_session ON workout_sets(session_id);
CREATE INDEX IF NOT EXISTS idx_workout_set_exercise ON workout_sets(exercise_id);
"""


MODULE = LifeModule(
    key="fitness",
    label="个人健身",
    schema=SCHEMA,
    tables={
        "fitness_sessions": ["id", "occurred_on", "activity", "duration_minutes", "intensity", "note", "created_at"],
        "exercises": ["id", "name", "kind", "muscle_group", "is_active", "created_at"],
        "workout_sets": ["id", "session_id", "exercise_id", "set_number", "reps", "weight_kg",
                         "distance_km", "duration_seconds", "note", "created_at"],
    },
    optional_tables=frozenset({"fitness_sessions", "exercises", "workout_sets"}),
    migrate=seed_default_exercises,
)
