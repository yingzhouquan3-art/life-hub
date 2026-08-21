"""跨模块只读视图的 HTTP 接口。

这些接口不写入任何数据，编辑与删除仍由来源模块负责。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from backend.core.db import db
from backend.views.calendar import get_life_calendar
from backend.views.overview import get_life_overview
from backend.views.search import search_life
from backend.views.timeline import get_life_timeline

router = APIRouter()


@router.get("/api/life/overview")
def life_overview():
    with db() as conn:
        return get_life_overview(conn)


@router.get("/api/life-calendar")
def life_calendar(month: Optional[str] = None, calendar_date: Optional[str] = Query(None, alias="date")):
    with db() as conn:
        return get_life_calendar(conn, month, calendar_date)


@router.get("/api/life-search")
def life_search(
    q: str = "", module: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    limit: int = 100,
):
    with db() as conn:
        return search_life(
            conn, query=q, module=module, date_from=date_from, date_to=date_to, limit=limit,
        )


@router.get("/api/life-timeline")
def life_timeline(
    module: Optional[str] = None, kind: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    offset: int = 0, limit: int = 50,
):
    with db() as conn:
        return get_life_timeline(
            conn, module=module, kind=kind, date_from=date_from, date_to=date_to,
            offset=offset, limit=limit,
        )
