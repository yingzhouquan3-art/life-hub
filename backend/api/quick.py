"""全局一句话记录的 HTTP 接口。

两步走，和账本原有的一句话记账保持一致：
先 `POST /api/quick/parse` 拿到可编辑预览，用户确认后再 `POST /api/quick/commit` 落库。
解析这一步绝不写入任何数据。
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.fitness import record_workout
from backend.modules.ledger import create_transaction
from backend.modules.nutrition import record_meal
from backend.modules.recovery import save_recovery_checkin
from backend.modules.rhythm import create_personal_task
from backend.modules.study import record_study_session
from backend.quick import MODULE_LABELS, parse_quick_record
from backend.views.overview import get_life_overview

router = APIRouter()


class QuickTextIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=200)
    module: Optional[
        Literal["finance", "fitness", "nutrition", "recovery", "study", "rhythm"]
    ] = None


class QuickCommitIn(BaseModel):
    module: Literal["finance", "fitness", "nutrition", "recovery", "study", "rhythm"]
    payload: dict[str, Any]


def _commit_finance(conn, payload: dict) -> dict:
    return {"transaction": create_transaction(
        conn,
        occurred_on=payload.get("occurred_on"),
        type=payload.get("type", "expense"),
        amount=payload.get("amount"),
        source=payload.get("source"),
        category=payload.get("category"),
        account_id=payload.get("account_id"),
        note=payload.get("note", ""),
    )}


def _commit_fitness(conn, payload: dict) -> dict:
    return {"session": record_workout(
        conn,
        occurred_on=payload["occurred_on"],
        activity=payload["activity"],
        duration_minutes=int(payload["duration_minutes"]),
        intensity=int(payload["intensity"]),
        note=payload.get("note", ""),
    )}


def _commit_nutrition(conn, payload: dict) -> dict:
    return {"entry": record_meal(
        conn,
        occurred_on=payload["occurred_on"],
        meal_type=payload["meal_type"],
        name=payload["name"],
        calories=payload.get("calories"),
        protein_g=payload.get("protein_g"),
        water_ml=payload.get("water_ml"),
        note=payload.get("note", ""),
    )}


def _commit_recovery(conn, payload: dict) -> dict:
    return {"checkin": save_recovery_checkin(
        conn,
        occurred_on=payload["occurred_on"],
        sleep_hours=payload.get("sleep_hours"),
        sleep_quality=payload.get("sleep_quality"),
        energy=payload.get("energy"),
        mood=payload.get("mood"),
        note=payload.get("note", ""),
    )}


def _commit_study(conn, payload: dict) -> dict:
    return {"session": record_study_session(
        conn,
        occurred_on=payload["occurred_on"],
        subject=payload["subject"],
        duration_minutes=int(payload["duration_minutes"]),
        focus=int(payload["focus"]),
        note=payload.get("note", ""),
    )}


def _commit_rhythm(conn, payload: dict) -> dict:
    return {"task": create_personal_task(
        conn,
        title=payload["title"],
        due_on=payload["due_on"],
        priority=payload.get("priority", "normal"),
        category=payload.get("category", "personal"),
        note=payload.get("note", ""),
    )}


_COMMITTERS = {
    "finance": _commit_finance,
    "fitness": _commit_fitness,
    "nutrition": _commit_nutrition,
    "recovery": _commit_recovery,
    "study": _commit_study,
    "rhythm": _commit_rhythm,
}


@router.get("/api/quick/modules")
def quick_modules():
    """一句话记录能落到哪些模块。前端用来渲染「改判到别的模块」。"""
    return {"modules": [{"key": key, "label": label} for key, label in MODULE_LABELS.items()]}


@router.post("/api/quick/parse")
def parse_quick(body: QuickTextIn):
    """解析一句话，返回可编辑预览。这一步不写入任何数据。

    带上 module 表示用户改判了归属，按指定模块重新解析同一句话。
    """
    with db() as conn:
        return parse_quick_record(conn, body.text, body.module)


@router.post("/api/quick/commit")
def commit_quick(body: QuickCommitIn):
    """把用户确认过的预览写入对应模块。"""
    committer = _COMMITTERS.get(body.module)
    if committer is None:
        raise HTTPException(400, f"未知模块：{body.module}")
    with db() as conn:
        try:
            result = committer(conn, body.payload)
        except KeyError as exc:
            raise HTTPException(400, f"预览缺少字段：{exc.args[0]}") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"预览内容无法写入：{exc}") from exc
        return {"module": body.module, **result, "life": get_life_overview(conn)}
