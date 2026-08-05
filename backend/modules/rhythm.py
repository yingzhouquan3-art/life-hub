"""日程与习惯模块。

待办与每日习惯含义分离：待办有完成状态，习惯只记录是否实践过。
连续完成只描述实践连续性，不用于惩罚或人格评价。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from backend.core.registry import LifeModule


def get_habit_streak(conn, habit_id: int, today: Optional[date] = None) -> int:
    current_day = today or date.today()
    rows = conn.execute(
        "SELECT occurred_on FROM habit_checkins WHERE habit_id = ? AND occurred_on <= ?",
        (habit_id, current_day.isoformat()),
    ).fetchall()
    checked_days = {row["occurred_on"] for row in rows}
    cursor = current_day if current_day.isoformat() in checked_days else current_day - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in checked_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def get_rhythm_state(conn) -> dict:
    today = date.today()
    today_key = today.isoformat()
    upcoming_end = (today + timedelta(days=7)).isoformat()
    task_rows = conn.execute(
        """SELECT * FROM personal_tasks
           WHERE status = 'pending' OR due_on >= ?
           ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,
                    due_on ASC,
                    CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
                    id DESC LIMIT 100""",
        ((today - timedelta(days=14)).isoformat(),),
    ).fetchall()
    task_items = [dict(row) for row in task_rows]
    today_tasks = [item for item in task_items if item["due_on"] == today_key]
    overdue = [item for item in task_items if item["status"] == "pending" and item["due_on"] < today_key]
    upcoming = [
        item for item in task_items
        if item["status"] == "pending" and today_key < item["due_on"] <= upcoming_end
    ]
    habit_rows = conn.execute(
        """SELECT h.*,
                  EXISTS(SELECT 1 FROM habit_checkins c WHERE c.habit_id = h.id AND c.occurred_on = ?) AS checked_today,
                  (SELECT COUNT(*) FROM habit_checkins c WHERE c.habit_id = h.id) AS checkin_count,
                  (SELECT MAX(occurred_on) FROM habit_checkins c WHERE c.habit_id = h.id) AS last_checked_on
           FROM habits h WHERE h.is_active = 1 ORDER BY h.id DESC""",
        (today_key,),
    ).fetchall()
    habits = []
    for row in habit_rows:
        item = dict(row)
        item["checked_today"] = bool(item["checked_today"])
        item["streak"] = get_habit_streak(conn, item["id"], today)
        habits.append(item)
    completed_habits = sum(1 for item in habits if item["checked_today"])
    return {
        "date": today_key,
        "tasks": task_items,
        "task_summary": {
            "today_total": len(today_tasks),
            "today_done": sum(1 for item in today_tasks if item["status"] == "done"),
            "today_pending": sum(1 for item in today_tasks if item["status"] == "pending"),
            "overdue": len(overdue),
            "upcoming_7_days": len(upcoming),
        },
        "habits": habits,
        "habit_summary": {
            "total": len(habits),
            "completed_today": completed_habits,
            "pending_today": len(habits) - completed_habits,
        },
    }


def create_personal_task(
    conn, *, title: str, due_on: str, priority: str = "normal",
    category: str = "personal", note: str = "",
) -> dict:
    date.fromisoformat(due_on)
    cur = conn.execute(
        """INSERT INTO personal_tasks
           (title, due_on, priority, category, status, note, completed_at, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?, NULL, ?)""",
        (title.strip(), due_on, priority, category, note.strip(), datetime.now().isoformat()),
    )
    return dict(conn.execute("SELECT * FROM personal_tasks WHERE id = ?", (cur.lastrowid,)).fetchone())


def toggle_personal_task(conn, task_id: int) -> dict:
    row = conn.execute("SELECT * FROM personal_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(404, "task not found")
    next_status = "done" if row["status"] == "pending" else "pending"
    completed_at = datetime.now().isoformat() if next_status == "done" else None
    conn.execute(
        "UPDATE personal_tasks SET status = ?, completed_at = ? WHERE id = ?",
        (next_status, completed_at, task_id),
    )
    return dict(conn.execute("SELECT * FROM personal_tasks WHERE id = ?", (task_id,)).fetchone())


def create_habit(conn, *, name: str, category: str = "personal") -> dict:
    existing = conn.execute(
        "SELECT 1 FROM habits WHERE is_active = 1 AND lower(name) = lower(?)", (name.strip(),)
    ).fetchone()
    if existing:
        raise HTTPException(400, "已有同名的每日习惯")
    cur = conn.execute(
        "INSERT INTO habits (name, category, is_active, created_at) VALUES (?, ?, 1, ?)",
        (name.strip(), category, datetime.now().isoformat()),
    )
    return dict(conn.execute("SELECT * FROM habits WHERE id = ?", (cur.lastrowid,)).fetchone())


def toggle_habit_checkin(conn, habit_id: int, occurred_on: str) -> dict:
    date.fromisoformat(occurred_on)
    habit = conn.execute("SELECT * FROM habits WHERE id = ? AND is_active = 1", (habit_id,)).fetchone()
    if not habit:
        raise HTTPException(404, "active habit not found")
    existing = conn.execute(
        "SELECT id FROM habit_checkins WHERE habit_id = ? AND occurred_on = ?",
        (habit_id, occurred_on),
    ).fetchone()
    if existing:
        conn.execute("DELETE FROM habit_checkins WHERE id = ?", (existing["id"],))
        checked = False
    else:
        conn.execute(
            "INSERT INTO habit_checkins (habit_id, occurred_on, created_at) VALUES (?, ?, ?)",
            (habit_id, occurred_on, datetime.now().isoformat()),
        )
        checked = True
    return {"habit_id": habit_id, "occurred_on": occurred_on, "checked": checked}

SCHEMA = """
CREATE TABLE IF NOT EXISTS personal_tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          due_on TEXT NOT NULL,
          priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high')),
          category TEXT NOT NULL DEFAULT 'personal' CHECK (category IN ('personal','study','health','finance','other')),
          status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done')),
          note TEXT DEFAULT '',
          completed_at TEXT,
          created_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS habits (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          category TEXT NOT NULL DEFAULT 'personal' CHECK (category IN ('personal','study','health','finance','other')),
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS habit_checkins (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
          occurred_on TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE (habit_id, occurred_on)
        );
CREATE INDEX IF NOT EXISTS idx_task_due ON personal_tasks(due_on, status);
CREATE INDEX IF NOT EXISTS idx_habit_checkin_date ON habit_checkins(occurred_on);
"""


MODULE = LifeModule(
    key="rhythm",
    label="日程与习惯",
    schema=SCHEMA,
    tables={
        "personal_tasks": ["id", "title", "due_on", "priority", "category", "status", "note", "completed_at", "created_at"],
        "habits": ["id", "name", "category", "is_active", "created_at"],
        "habit_checkins": ["id", "habit_id", "occurred_on", "created_at"],
    },
    optional_tables=frozenset({"personal_tasks", "habits", "habit_checkins"}),
)
