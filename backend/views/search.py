"""全局生活搜索视图。

只读：不得因为查询而创建、更新或删除任何来源数据。
搜索结果必须标注来源模块；没有结果只表示当前条件下没有匹配。
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from backend.views.activity import LIFE_ITEM_MODULES, collect_life_items
from backend.views.timeline import _validate_date_range


def search_life(
    conn, *, query: str, module: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None, limit: int = 100,
) -> dict:
    query = query.strip()
    if not query:
        raise HTTPException(400, "search query is required")
    if len(query) > 100:
        raise HTTPException(400, "search query is too long")
    if module and module not in LIFE_ITEM_MODULES:
        raise HTTPException(400, "invalid life search module")
    _validate_date_range(date_from, date_to)
    safe_limit = min(max(int(limit), 1), 200)
    needle = query.casefold()
    results = []
    for item in collect_life_items(conn):
        if module and item["module"] != module:
            continue
        occurred_on = item["date"]
        if occurred_on:
            if date_from and occurred_on < date_from:
                continue
            if date_to and occurred_on > date_to:
                continue
        elif date_from or date_to:
            continue
        if needle not in f"{item['title']} {item['detail']}".casefold():
            continue
        results.append(item)
    total = len(results)
    by_module = {name: sum(item["module"] == name for item in results) for name in LIFE_ITEM_MODULES}
    return {
        "query": query,
        "filters": {"module": module, "date_from": date_from, "date_to": date_to},
        "summary": {"total": total, "by_module": by_module},
        "results": results[:safe_limit],
        "limit": safe_limit,
        "truncated": total > safe_limit,
    }
