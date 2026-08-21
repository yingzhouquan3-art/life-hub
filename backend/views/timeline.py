"""生活轨迹：无需关键词即可浏览跨模块生活条目。"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import HTTPException

from backend.views.activity import LIFE_ITEM_KINDS, LIFE_ITEM_MODULES, collect_life_items


def _validate_date_range(date_from: Optional[str], date_to: Optional[str]) -> None:
    for value, label in ((date_from, "date_from"), (date_to, "date_to")):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise HTTPException(400, f"{label} must be YYYY-MM-DD") from exc
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, "date_from must not be after date_to")


def get_life_timeline(
    conn, *, module: Optional[str] = None, kind: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    offset: int = 0, limit: int = 50,
) -> dict:
    if module and module not in LIFE_ITEM_MODULES:
        raise HTTPException(400, "invalid life timeline module")
    if kind and kind not in LIFE_ITEM_KINDS:
        raise HTTPException(400, "invalid life timeline kind")
    _validate_date_range(date_from, date_to)
    safe_offset = max(int(offset), 0)
    if safe_offset > 100_000:
        raise HTTPException(400, "timeline offset is too large")
    safe_limit = min(max(int(limit), 1), 100)

    results = []
    for item in collect_life_items(conn):
        if module and item["module"] != module:
            continue
        if kind and item["kind"] != kind:
            continue
        occurred_on = item["date"]
        if occurred_on:
            if date_from and occurred_on < date_from:
                continue
            if date_to and occurred_on > date_to:
                continue
        elif date_from or date_to:
            continue
        results.append(item)

    total = len(results)
    page = results[safe_offset:safe_offset + safe_limit]
    return {
        "filters": {"module": module, "kind": kind, "date_from": date_from, "date_to": date_to},
        "summary": {
            "total": total,
            "by_module": {name: sum(item["module"] == name for item in results) for name in LIFE_ITEM_MODULES},
            "by_kind": {name: sum(item["kind"] == name for item in results) for name in LIFE_ITEM_KINDS},
        },
        "results": page,
        "offset": safe_offset,
        "limit": safe_limit,
        "next_offset": safe_offset + len(page),
        "has_more": safe_offset + len(page) < total,
    }
