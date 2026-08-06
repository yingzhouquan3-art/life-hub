"""收集箱的 HTTP 接口。"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.inbox import (
    add_inbox_item,
    delete_inbox_item,
    drop_inbox_item,
    file_inbox_item,
    get_inbox_state,
    reopen_inbox_item,
)

router = APIRouter()


class InboxItemIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)
    source: Literal["desktop", "mobile", "capture", "other"] = "desktop"
    note: str = Field("", max_length=200)


class InboxFileIn(BaseModel):
    target_module: Literal[
        "finance", "fitness", "nutrition", "recovery", "body",
        "study", "rhythm", "goals", "reflection",
    ]
    note: str = Field("", max_length=200)


@router.get("/api/inbox")
def inbox_state(limit: int = 50, status: Optional[str] = None):
    with db() as conn:
        return get_inbox_state(conn, limit, status)


@router.post("/api/inbox")
def add_item(body: InboxItemIn):
    with db() as conn:
        item = add_inbox_item(conn, content=body.content, source=body.source, note=body.note)
        return {"item": item, "inbox": get_inbox_state(conn)}


@router.post("/api/inbox/{item_id}/file")
def file_item(item_id: int, body: InboxFileIn):
    """标记这条去了哪个模块。只写标记，不复制内容。"""
    with db() as conn:
        return {
            "item": file_inbox_item(conn, item_id, body.target_module, body.note),
            "inbox": get_inbox_state(conn),
        }


@router.post("/api/inbox/{item_id}/drop")
def drop_item(item_id: int):
    with db() as conn:
        return {"item": drop_inbox_item(conn, item_id), "inbox": get_inbox_state(conn)}


@router.post("/api/inbox/{item_id}/reopen")
def reopen_item(item_id: int):
    with db() as conn:
        return {"item": reopen_inbox_item(conn, item_id), "inbox": get_inbox_state(conn)}


@router.delete("/api/inbox/{item_id}")
def remove_item(item_id: int):
    with db() as conn:
        return {"deleted": delete_inbox_item(conn, item_id), "inbox": get_inbox_state(conn)}
