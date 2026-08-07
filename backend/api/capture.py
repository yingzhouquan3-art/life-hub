"""待确认捕获的 HTTP 接口。

`POST /api/capture` 是手机端自动化（通知监听、短信转发）的唯一入口。
确认一条捕获会跨两个模块：由账本创建交易，再由捕获模块记下对应关系。
这层编排放在 api，是为了让两个模块彼此仍然不知道对方存在。
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.capture import (
    dismiss_capture,
    get_capture,
    get_capture_coverage,
    get_capture_state,
    mark_capture_confirmed,
    record_capture,
)
from backend.modules.capture_rules import describe_rules, parse_notification
from backend.modules.categorize import learn_category, suggest_category
from backend.modules.ledger import compute_stats, create_transaction, get_today_overview

router = APIRouter()


class CaptureIn(BaseModel):
    channel: Literal["wechat_notification", "bank_sms", "manual", "other"]
    raw_text: str = Field(..., min_length=1, max_length=500)
    amount: float = Field(..., gt=0)
    direction: Literal["expense", "income"] = "expense"
    merchant: str = Field("", max_length=60)
    occurred_at: Optional[str] = None
    note: str = Field("", max_length=200)


class CaptureConfirmIn(BaseModel):
    category: Optional[
        Literal["food", "transport", "study", "housing", "medical",
                "entertainment", "social", "digital", "other"]
    ] = None
    source: Optional[
        Literal["family_support", "scholarship", "part_time", "project", "investment", "other"]
    ] = None
    account_id: Optional[int] = None
    occurred_on: Optional[str] = None
    note: Optional[str] = Field(None, max_length=200)


class NotificationIn(BaseModel):
    """手机端自动化转发过来的通知原文。"""

    channel: Literal["wechat_notification", "bank_sms", "other"] = "wechat_notification"
    text: str = Field(..., min_length=1, max_length=500)
    title: str = Field("", max_length=120)
    occurred_at: Optional[str] = None


def _with_suggestions(conn, state: dict) -> dict:
    """给每条待确认捕获附上建议分类。

    只是预选，不代表已经归类；猜不出来就不给，前端退回「其他」。
    """
    for item in state.get("pending", []):
        item["suggested"] = suggest_category(
            conn, f"{item.get('merchant', '')} {item.get('raw_text', '')}"
        )
    return state


@router.get("/api/capture/rules")
def capture_rules():
    """当前生效的解析规则。接通知监听之前先拿真实原文对着调。"""
    return {"rules": describe_rules()}


@router.post("/api/capture/parse")
def parse_notification_only(body: NotificationIn):
    """只解析不写入。用来拿真实通知原文验证规则，不会产生任何记录。"""
    return parse_notification(f"{body.title} {body.text}".strip(), body.channel)


@router.post("/api/capture/notification")
def capture_notification(body: NotificationIn):
    """手机端自动化的主入口：转发通知原文，后端解析并落成待确认条目。

    解析不出金额时不写入任何东西，返回 matched=false 由手机端自行决定是否提示。
    """
    parsed = parse_notification(f"{body.title} {body.text}".strip(), body.channel)
    if not parsed["matched"]:
        return {"matched": False, "reason": parsed["reason"], "raw_text": parsed["raw_text"]}
    with db() as conn:
        result = record_capture(
            conn,
            channel=body.channel,
            raw_text=parsed["raw_text"],
            amount=parsed["amount"],
            direction=parsed["direction"],
            merchant=parsed["merchant"],
            occurred_at=body.occurred_at,
        )
        return {"matched": True, "rule": parsed["rule"], **result,
                "capture_state": _with_suggestions(conn, get_capture_state(conn))}


@router.get("/api/capture")
def capture_state(limit: int = 50):
    with db() as conn:
        return _with_suggestions(conn, get_capture_state(conn, limit))


@router.post("/api/capture")
def add_capture(body: CaptureIn):
    """接收一条自动捕获。落成待确认条目，不进入任何统计。"""
    with db() as conn:
        result = record_capture(
            conn,
            channel=body.channel,
            raw_text=body.raw_text,
            amount=body.amount,
            direction=body.direction,
            merchant=body.merchant,
            occurred_at=body.occurred_at,
            note=body.note,
        )
        return {**result, "capture_state": _with_suggestions(conn, get_capture_state(conn))}


@router.post("/api/capture/{capture_id}/confirm")
def confirm_capture(capture_id: int, body: CaptureConfirmIn):
    """把一条捕获转成真正的交易。到这一步之前它不影响任何数字。"""
    with db() as conn:
        capture = get_capture(conn, capture_id)
        note = body.note if body.note is not None else (
            capture["merchant"] or capture["raw_text"]
        )
        transaction = create_transaction(
            conn,
            occurred_on=body.occurred_on or capture["occurred_on"],
            type=capture["direction"],
            amount=capture["amount"],
            source=body.source,
            category=body.category,
            account_id=body.account_id,
            note=note,
        )
        confirmed = mark_capture_confirmed(conn, capture_id, transaction["id"])

        # 用户确认过的归类才是事实，这时才学。
        # 有商户名就用商户名当关键字；没有就不学——
        # 拿整条通知原文当关键字永远不会再命中，只是噪声。
        learned = None
        if capture["direction"] == "expense" and body.category and capture["merchant"]:
            learned = learn_category(conn, capture["merchant"], body.category)

        return {
            "capture": confirmed,
            "transaction": transaction,
            "learned_rule": learned,
            "stats": compute_stats(conn),
            "today": get_today_overview(conn),
            "capture_state": _with_suggestions(conn, get_capture_state(conn)),
        }


@router.post("/api/capture/{capture_id}/dismiss")
def ignore_capture(capture_id: int):
    with db() as conn:
        return {
            "capture": dismiss_capture(conn, capture_id),
            "capture_state": _with_suggestions(conn, get_capture_state(conn)),
        }


@router.get("/api/capture/coverage")
def capture_coverage(month: Optional[str] = None):
    """捕获覆盖率，用来发现监听通道是不是悄悄挂了。"""
    with db() as conn:
        return get_capture_coverage(conn, month)
