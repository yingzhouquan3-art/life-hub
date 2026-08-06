"""跨模块标签。

一个 `#考研` 可以同时贴在学习记录、待办和一笔支出上。
标签是唯一横穿所有模块的东西，所以它的边界要格外清楚：

- 标签**不拥有**任何生活数据，只保存「哪个模块的哪条记录被贴了什么」；
- 链接里刻意不设外键——设了就等于让标签模块依赖其他模块的表结构，
  代价是**链接可能指向已经被删掉的记录**，这一点由读取侧负责识别；
- 删除一个标签只删链接，不动任何来源记录。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from fastapi import HTTPException

from backend.core.registry import LifeModule

# 可以被贴标签的模块。加新模块时在这里登记，读取侧再补一条解析规则。
TAGGABLE_MODULES = {
    "finance": "个人账本",
    "fitness": "个人健身",
    "nutrition": "个人饮食",
    "recovery": "睡眠与恢复",
    "body": "身体指标",
    "study": "学习与专注",
    "rhythm": "日程与习惯",
    "goals": "个人目标",
    "reflection": "日记与复盘",
    "inbox": "收集箱",
}

_NAME_PATTERN = re.compile(r"^[^\s#,，、]{1,20}$")


def normalise_tag_name(raw: str) -> str:
    """统一去掉前导 #，并压掉空白。`#考研` 与 `考研` 是同一个标签。"""
    name = (raw or "").strip().lstrip("#＃").strip()
    if not _NAME_PATTERN.match(name):
        raise HTTPException(400, "标签名不能为空，且不能含空格、# 或逗号，最长 20 字")
    return name


def get_or_create_tag(conn, name: str) -> dict:
    clean = normalise_tag_name(name)
    row = conn.execute("SELECT * FROM tags WHERE name = ?", (clean,)).fetchone()
    if row:
        return dict(row)
    cur = conn.execute(
        "INSERT INTO tags (name, created_at) VALUES (?, ?)",
        (clean, datetime.now().isoformat()),
    )
    return dict(conn.execute("SELECT * FROM tags WHERE id = ?", (cur.lastrowid,)).fetchone())


def attach_tag(conn, *, name: str, module: str, record_id: int) -> dict:
    """给某条记录贴一个标签。重复贴同一个不会产生第二条链接。"""
    if module not in TAGGABLE_MODULES:
        raise HTTPException(400, f"这个模块不支持标签：{module}")
    if record_id is None or record_id <= 0:
        raise HTTPException(400, "record_id 必须是正整数")
    tag = get_or_create_tag(conn, name)
    conn.execute(
        """INSERT OR IGNORE INTO tag_links (tag_id, module, record_id, created_at)
           VALUES (?, ?, ?, ?)""",
        (tag["id"], module, record_id, datetime.now().isoformat()),
    )
    return tag


def detach_tag(conn, *, name: str, module: str, record_id: int) -> int:
    """撕掉一个标签。只删链接，来源记录一动不动。"""
    tag = conn.execute(
        "SELECT * FROM tags WHERE name = ?", (normalise_tag_name(name),)
    ).fetchone()
    if not tag:
        raise HTTPException(404, "tag not found")
    cur = conn.execute(
        "DELETE FROM tag_links WHERE tag_id = ? AND module = ? AND record_id = ?",
        (tag["id"], module, record_id),
    )
    return cur.rowcount


def delete_tag(conn, tag_id: int) -> int:
    """删掉一个标签及其全部链接。不影响任何来源记录。"""
    if not conn.execute("SELECT 1 FROM tags WHERE id = ?", (tag_id,)).fetchone():
        raise HTTPException(404, "tag not found")
    conn.execute("DELETE FROM tag_links WHERE tag_id = ?", (tag_id,))
    conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    return tag_id


def get_record_tags(conn, module: str, record_id: int) -> list[str]:
    rows = conn.execute(
        """SELECT t.name FROM tag_links l JOIN tags t ON t.id = l.tag_id
           WHERE l.module = ? AND l.record_id = ? ORDER BY t.name""",
        (module, record_id),
    ).fetchall()
    return [row["name"] for row in rows]


def get_tag_links(conn, name: str) -> list[dict]:
    """某个标签贴在哪些记录上。链接可能指向已删除的记录，由读取侧识别。"""
    rows = conn.execute(
        """SELECT l.module, l.record_id, l.created_at FROM tag_links l
           JOIN tags t ON t.id = l.tag_id
           WHERE t.name = ? ORDER BY l.module, l.record_id""",
        (normalise_tag_name(name),),
    ).fetchall()
    return [dict(row) for row in rows]


def get_tags_state(conn, limit: int = 100) -> dict:
    """标签清单与各自的链接数。

    链接数只统计链接，不保证目标记录仍然存在——
    要看真实存在的条数，用只读视图 views/tags.py。
    """
    rows = conn.execute(
        """SELECT t.id, t.name, t.created_at, COUNT(l.id) AS link_count
           FROM tags t LEFT JOIN tag_links l ON l.tag_id = t.id
           GROUP BY t.id ORDER BY link_count DESC, t.name
           LIMIT ?""",
        (max(1, min(limit, 500)),),
    ).fetchall()
    return {
        "tags": [dict(row) for row in rows],
        "modules": TAGGABLE_MODULES,
        "note": "链接数只统计链接本身，不保证目标记录仍然存在。",
    }


def prune_dead_links(conn, alive: dict[str, set[int]]) -> int:
    """删掉指向已不存在记录的链接。

    存活清单由读取侧提供——标签模块不认识其他模块的表。
    """
    removed = 0
    for row in conn.execute("SELECT id, module, record_id FROM tag_links").fetchall():
        surviving = alive.get(row["module"])
        if surviving is None or row["record_id"] in surviving:
            continue
        conn.execute("DELETE FROM tag_links WHERE id = ?", (row["id"],))
        removed += 1
    return removed


SCHEMA = """
CREATE TABLE IF NOT EXISTS tags (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tag_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  module TEXT NOT NULL,
  record_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (tag_id, module, record_id)
);
CREATE INDEX IF NOT EXISTS idx_tag_link_target ON tag_links(module, record_id);
"""

MODULE = LifeModule(
    key="tags",
    label="跨模块标签",
    schema=SCHEMA,
    tables={
        "tags": ["id", "name", "created_at"],
        "tag_links": ["id", "tag_id", "module", "record_id", "created_at"],
    },
    optional_tables=frozenset({"tags", "tag_links"}),
)
