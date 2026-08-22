"""示例数据的 HTTP 接口。

装入和移除都要用户在界面上点，不提供任何"顺手就执行"的入口——
它写入的是几百条记录，误触的代价不小。
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.demo import DEFAULT_DAYS, MAX_DAYS, get_demo_state, load_demo, remove_demo

router = APIRouter()


class DemoLoadIn(BaseModel):
    days: int = Field(DEFAULT_DAYS, ge=7, le=MAX_DAYS)


@router.get("/api/demo")
def demo_state():
    """装没装过示例数据，以及库里有多少是你自己的记录。"""
    with db() as conn:
        return get_demo_state(conn)


@router.post("/api/demo")
def demo_load(body: DemoLoadIn):
    """写入一批跨模块示例记录。不删除任何已有数据；已经装过会拒绝。"""
    with db() as conn:
        return load_demo(conn, body.days)


@router.delete("/api/demo")
def demo_remove():
    """精确移除示例数据。只删登记在册的那些，不碰你自己的记录。"""
    with db() as conn:
        return remove_demo(conn)
