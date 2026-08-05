"""个人目标模块。

管理生活目标与里程碑；目标完成必须由用户主动确认，系统不自动判定。
不管理储蓄金额——带金额的储蓄目标属于个人账本模块。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from backend.core.registry import LifeModule


def get_life_goals_state(conn) -> dict:
    goal_rows = conn.execute(
        """SELECT * FROM life_goals
           ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,
                    target_date IS NULL, target_date, id DESC"""
    ).fetchall()
    milestone_rows = conn.execute(
        "SELECT * FROM goal_milestones ORDER BY status, target_date IS NULL, target_date, id"
    ).fetchall()
    milestones_by_goal: dict[int, list[dict]] = {}
    for row in milestone_rows:
        item = dict(row)
        milestones_by_goal.setdefault(item["goal_id"], []).append(item)
    goals = []
    for row in goal_rows:
        goal = dict(row)
        milestones = milestones_by_goal.get(goal["id"], [])
        completed = sum(1 for item in milestones if item["status"] == "done")
        goal["milestones"] = milestones
        goal["progress"] = {"completed": completed, "total": len(milestones)}
        goals.append(goal)
    return {
        "goals": goals,
        "summary": {
            "active": sum(1 for goal in goals if goal["status"] == "active"),
            "paused": sum(1 for goal in goals if goal["status"] == "paused"),
            "completed": sum(1 for goal in goals if goal["status"] == "completed"),
            "milestones_done": sum(goal["progress"]["completed"] for goal in goals),
            "milestones_total": sum(goal["progress"]["total"] for goal in goals),
        },
    }


def create_life_goal(
    conn, *, title: str, category: str = "personal", target_date: Optional[str] = None,
    motivation: str = "",
) -> dict:
    title = title.strip()
    if not title:
        raise HTTPException(400, "goal title is required")
    if target_date:
        date.fromisoformat(target_date)
    now = datetime.now().isoformat()
    cur = conn.execute(
        """INSERT INTO life_goals
           (title, category, target_date, motivation, status, completed_at, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'active', NULL, ?, ?)""",
        (title, category, target_date or None, motivation.strip(), now, now),
    )
    return dict(conn.execute("SELECT * FROM life_goals WHERE id = ?", (cur.lastrowid,)).fetchone())


def set_life_goal_status(conn, goal_id: int, status: str) -> dict:
    if status not in {"active", "paused", "completed"}:
        raise HTTPException(400, "invalid goal status")
    if not conn.execute("SELECT 1 FROM life_goals WHERE id = ?", (goal_id,)).fetchone():
        raise HTTPException(404, "life goal not found")
    now = datetime.now().isoformat()
    conn.execute(
        """UPDATE life_goals SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?""",
        (status, now if status == "completed" else None, now, goal_id),
    )
    return dict(conn.execute("SELECT * FROM life_goals WHERE id = ?", (goal_id,)).fetchone())


def create_goal_milestone(
    conn, *, goal_id: int, title: str, target_date: Optional[str] = None,
) -> dict:
    title = title.strip()
    if not title:
        raise HTTPException(400, "milestone title is required")
    if target_date:
        date.fromisoformat(target_date)
    if not conn.execute("SELECT 1 FROM life_goals WHERE id = ?", (goal_id,)).fetchone():
        raise HTTPException(404, "life goal not found")
    cur = conn.execute(
        """INSERT INTO goal_milestones
           (goal_id, title, target_date, status, completed_at, created_at)
           VALUES (?, ?, ?, 'pending', NULL, ?)""",
        (goal_id, title, target_date or None, datetime.now().isoformat()),
    )
    return dict(conn.execute(
        "SELECT * FROM goal_milestones WHERE id = ?", (cur.lastrowid,)
    ).fetchone())


def toggle_goal_milestone(conn, milestone_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM goal_milestones WHERE id = ?", (milestone_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "goal milestone not found")
    status = "pending" if row["status"] == "done" else "done"
    completed_at = datetime.now().isoformat() if status == "done" else None
    conn.execute(
        "UPDATE goal_milestones SET status = ?, completed_at = ? WHERE id = ?",
        (status, completed_at, milestone_id),
    )
    return dict(conn.execute(
        "SELECT * FROM goal_milestones WHERE id = ?", (milestone_id,)
    ).fetchone())

SCHEMA = """
CREATE TABLE IF NOT EXISTS life_goals (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          category TEXT NOT NULL DEFAULT 'personal' CHECK (category IN ('personal','study','health','finance','other')),
          target_date TEXT,
          motivation TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','completed')),
          completed_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS goal_milestones (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          goal_id INTEGER NOT NULL REFERENCES life_goals(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          target_date TEXT,
          status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done')),
          completed_at TEXT,
          created_at TEXT NOT NULL
        );
CREATE INDEX IF NOT EXISTS idx_life_goal_target ON life_goals(target_date, status);
CREATE INDEX IF NOT EXISTS idx_goal_milestone_target ON goal_milestones(target_date, status);
"""


MODULE = LifeModule(
    key="goals",
    label="个人目标",
    schema=SCHEMA,
    tables={
        "life_goals": ["id", "title", "category", "target_date", "motivation", "status", "completed_at", "created_at", "updated_at"],
        "goal_milestones": ["id", "goal_id", "title", "target_date", "status", "completed_at", "created_at"],
    },
    optional_tables=frozenset({"life_goals", "goal_milestones"}),
)
