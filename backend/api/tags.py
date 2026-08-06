"""跨模块标签的 HTTP 接口。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.tags import attach_tag, delete_tag, detach_tag, get_tags_state
from backend.views.tags import (
    assert_module_supported,
    cleanup_dead_links,
    get_tag_overview,
    get_tagged_records,
)

router = APIRouter()


class TagLinkIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=21)
    module: str = Field(..., min_length=1, max_length=20)
    record_id: int = Field(..., gt=0)


@router.get("/api/tags")
def tags_state(limit: int = 100):
    with db() as conn:
        return get_tags_state(conn, limit)


@router.get("/api/tags/overview")
def tag_overview(limit: int = 50):
    """每个标签下真实存在的记录数与跨了哪些模块。"""
    with db() as conn:
        return get_tag_overview(conn, limit)


@router.get("/api/tags/{name}")
def tagged_records(name: str):
    with db() as conn:
        return get_tagged_records(conn, name)


@router.post("/api/tags/attach")
def attach(body: TagLinkIn):
    assert_module_supported(body.module)
    with db() as conn:
        tag = attach_tag(conn, name=body.name, module=body.module, record_id=body.record_id)
        return {"tag": tag, "tags": get_tags_state(conn)}


@router.post("/api/tags/detach")
def detach(body: TagLinkIn):
    """撕掉一个标签。只删链接，来源记录一动不动。"""
    assert_module_supported(body.module)
    with db() as conn:
        removed = detach_tag(conn, name=body.name, module=body.module, record_id=body.record_id)
        return {"removed": removed, "tags": get_tags_state(conn)}


@router.delete("/api/tags/{tag_id}")
def remove_tag(tag_id: int):
    """删掉整个标签及其全部链接。不影响任何来源记录。"""
    with db() as conn:
        return {"deleted": delete_tag(conn, tag_id), "tags": get_tags_state(conn)}


@router.post("/api/tags/cleanup")
def cleanup():
    """清掉指向已删除记录的失效链接。显式动作，不在读取时悄悄执行。"""
    with db() as conn:
        return cleanup_dead_links(conn)
