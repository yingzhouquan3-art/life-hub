"""个人目标模块的 HTTP 接口。"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.goals import (
    create_goal_milestone,
    create_life_goal,
    get_life_goals_state,
    set_life_goal_status,
    toggle_goal_milestone,
)

router = APIRouter()


class LifeGoalIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    category: Literal["personal", "study", "health", "finance", "other"] = "personal"
    target_date: Optional[str] = None
    motivation: str = Field("", max_length=500)


class LifeGoalStatusIn(BaseModel):
    status: Literal["active", "paused", "completed"]


class GoalMilestoneIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    target_date: Optional[str] = None


@router.get("/api/life-goals")
def life_goals_state():
    with db() as conn:
        return get_life_goals_state(conn)


@router.post("/api/life-goals")
def add_life_goal(body: LifeGoalIn):
    with db() as conn:
        goal = create_life_goal(
            conn, title=body.title, category=body.category,
            target_date=body.target_date, motivation=body.motivation,
        )
        return {"goal": goal, "goals": get_life_goals_state(conn)}


@router.post("/api/life-goals/{goal_id}/status")
def update_life_goal_status(goal_id: int, body: LifeGoalStatusIn):
    with db() as conn:
        goal = set_life_goal_status(conn, goal_id, body.status)
        return {"goal": goal, "goals": get_life_goals_state(conn)}


@router.delete("/api/life-goals/{goal_id}")
def delete_life_goal(goal_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM life_goals WHERE id = ?", (goal_id,)).fetchone():
            raise HTTPException(404, "life goal not found")
        conn.execute("DELETE FROM life_goals WHERE id = ?", (goal_id,))
        return {"deleted": goal_id, "goals": get_life_goals_state(conn)}


@router.post("/api/life-goals/{goal_id}/milestones")
def add_goal_milestone(goal_id: int, body: GoalMilestoneIn):
    with db() as conn:
        milestone = create_goal_milestone(
            conn, goal_id=goal_id, title=body.title, target_date=body.target_date,
        )
        return {"milestone": milestone, "goals": get_life_goals_state(conn)}


@router.post("/api/goal-milestones/{milestone_id}/toggle")
def toggle_life_goal_milestone(milestone_id: int):
    with db() as conn:
        milestone = toggle_goal_milestone(conn, milestone_id)
        return {"milestone": milestone, "goals": get_life_goals_state(conn)}


@router.delete("/api/goal-milestones/{milestone_id}")
def delete_life_goal_milestone(milestone_id: int):
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM goal_milestones WHERE id = ?", (milestone_id,)
        ).fetchone():
            raise HTTPException(404, "goal milestone not found")
        conn.execute("DELETE FROM goal_milestones WHERE id = ?", (milestone_id,))
        return {"deleted": milestone_id, "goals": get_life_goals_state(conn)}
