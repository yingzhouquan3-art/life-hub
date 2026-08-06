"""标签的只读视图：把链接解析回真实记录。

标签模块只存「哪个模块的哪条记录」，不认识任何表；
把 record_id 变成一条看得懂的摘要是跨模块的事，所以放在 views。

链接刻意没有外键，于是**来源记录被删除后链接会变成悬空**。
这里的职责就是识别它们：解析时跳过，并如实报出有多少条已经失效，
而不是假装它们不存在。
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from backend.modules.tags import TAGGABLE_MODULES, get_tag_links, prune_dead_links

# 模块 -> (表名, 日期列, 标题列)。加新模块时补一条。
_SOURCES = {
    "finance": ("transactions", "occurred_on", "note"),
    "fitness": ("fitness_sessions", "occurred_on", "note"),
    "nutrition": ("nutrition_entries", "occurred_on", "name"),
    "recovery": ("recovery_checkins", "occurred_on", "note"),
    "body": ("body_measurements", "occurred_on", "note"),
    "study": ("study_sessions", "occurred_on", "subject"),
    "rhythm": ("personal_tasks", "due_on", "title"),
    "goals": ("life_goals", "target_date", "title"),
    "reflection": ("daily_reflections", "occurred_on", "highlight"),
    "inbox": ("inbox_items", "created_at", "content"),
}

assert set(_SOURCES) == set(TAGGABLE_MODULES), "可贴标签的模块与解析规则必须一一对应"


def _resolve(conn, module: str, record_id: int) -> Optional[dict]:
    table, date_column, title_column = _SOURCES[module]
    row = conn.execute(
        f"SELECT id, {date_column} AS occurred_on, {title_column} AS title FROM {table} WHERE id = ?",
        (record_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "module": module,
        "module_label": TAGGABLE_MODULES[module],
        "id": row["id"],
        "occurred_on": row["occurred_on"],
        "title": (row["title"] or "").strip() or TAGGABLE_MODULES[module],
    }


def get_tagged_records(conn, name: str) -> dict:
    """某个标签下的全部记录，按模块分组。

    失效链接不会被算进结果，但会如实报出条数——
    悄悄丢掉它们会让「这个标签下有多少东西」这个数字失去意义。
    """
    links = get_tag_links(conn, name)
    if not links:
        return {
            "tag": name,
            "records": [],
            "by_module": {},
            "total": 0,
            "dead_links": 0,
            "note": "没有结果只表示这个标签当前没有贴在任何记录上。",
        }

    records = []
    dead = 0
    for link in links:
        if link["module"] not in _SOURCES:
            dead += 1
            continue
        resolved = _resolve(conn, link["module"], link["record_id"])
        if resolved is None:
            dead += 1
            continue
        records.append(resolved)

    records.sort(key=lambda item: (item["occurred_on"] or "", item["module"]), reverse=True)
    by_module: dict[str, int] = {}
    for record in records:
        by_module[record["module"]] = by_module.get(record["module"], 0) + 1

    return {
        "tag": name,
        "records": records,
        "by_module": by_module,
        "total": len(records),
        "dead_links": dead,
        "note": "失效链接指向已被删除的来源记录，不计入结果。",
    }


def cleanup_dead_links(conn) -> dict:
    """清掉指向已删除记录的链接。

    这是一次显式的维护动作，不在读取时悄悄执行——
    用户应当先看到「有多少条失效」，再决定要不要清。
    """
    alive = {}
    for module, (table, _, _) in _SOURCES.items():
        alive[module] = {
            row["id"] for row in conn.execute(f"SELECT id FROM {table}").fetchall()
        }
    removed = prune_dead_links(conn, alive)
    return {"removed": removed}


def get_tag_overview(conn, limit: int = 50) -> dict:
    """标签总览：每个标签下真实存在的记录数与跨了哪些模块。"""
    rows = conn.execute(
        "SELECT name FROM tags ORDER BY name LIMIT ?", (max(1, min(limit, 500)),)
    ).fetchall()
    overview = []
    for row in rows:
        resolved = get_tagged_records(conn, row["name"])
        overview.append({
            "name": row["name"],
            "total": resolved["total"],
            "modules": sorted(resolved["by_module"]),
            "dead_links": resolved["dead_links"],
        })
    overview.sort(key=lambda item: (-item["total"], item["name"]))
    return {"tags": overview, "modules": TAGGABLE_MODULES}


def assert_module_supported(module: str) -> None:
    if module not in _SOURCES:
        raise HTTPException(400, f"这个模块不支持标签：{module}")
