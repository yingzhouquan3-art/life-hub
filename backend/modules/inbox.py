"""收集箱模块。

一个随手输入的地方：想到什么先扔进来，之后再决定它属于哪儿。
没有它，其他模块的记录率会持续下降——因为「现在就得想清楚这属于哪个模块」
本身就是一道门槛，而念头往往出现在最不方便分类的时候。

三条规则：

- 收集箱里的条目**不是任何模块的事实**，不进入任何统计；
- 归档只是标记「这条去了哪里」，不会把内容复制过去，
  也不会在目标模块里凭空造出一条记录；
- 丢弃只表示不打算处理，不代表这件事没发生过。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException

from backend.core.registry import LifeModule

SOURCES = ("desktop", "mobile", "capture", "other")
STATUSES = ("open", "filed", "dropped")

# 归档去向必须是一个真实存在的模块，否则「去了哪里」就没有意义
FILE_TARGETS = {
    "finance": "个人账本",
    "fitness": "个人健身",
    "nutrition": "个人饮食",
    "recovery": "睡眠与恢复",
    "body": "身体指标",
    "study": "学习与专注",
    "rhythm": "日程与习惯",
    "goals": "个人目标",
    "reflection": "日记与复盘",
}


def add_inbox_item(conn, *, content: str, source: str = "desktop", note: str = "") -> dict:
    clean = " ".join((content or "").strip().split())
    if not clean:
        raise HTTPException(400, "收集箱条目不能为空")
    if source not in SOURCES:
        raise HTTPException(400, f"未知来源：{source}")
    cur = conn.execute(
        """INSERT INTO inbox_items (content, source, status, note, created_at)
           VALUES (?, ?, 'open', ?, ?)""",
        (clean[:500], source, note.strip(), datetime.now().isoformat()),
    )
    return dict(conn.execute("SELECT * FROM inbox_items WHERE id = ?", (cur.lastrowid,)).fetchone())


def get_inbox_item(conn, item_id: int) -> dict:
    row = conn.execute("SELECT * FROM inbox_items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404, "inbox item not found")
    return dict(row)


def file_inbox_item(conn, item_id: int, target_module: str, note: str = "") -> dict:
    """标记这条已经处理，并记下它去了哪个模块。

    只写标记，不复制内容：真正的记录由用户在目标模块自己创建，
    否则收集箱就成了第二份事实来源。
    """
    item = get_inbox_item(conn, item_id)
    if item["status"] != "open":
        raise HTTPException(400, "这条已经处理过了")
    if target_module not in FILE_TARGETS:
        raise HTTPException(400, f"未知的归档去向：{target_module}")
    conn.execute(
        """UPDATE inbox_items
           SET status = 'filed', filed_module = ?, note = ?, resolved_at = ?
           WHERE id = ?""",
        (target_module, note.strip() or item["note"], datetime.now().isoformat(), item_id),
    )
    return get_inbox_item(conn, item_id)


def drop_inbox_item(conn, item_id: int) -> dict:
    """不打算处理了。这不代表这件事没发生过，只是不进任何模块。"""
    item = get_inbox_item(conn, item_id)
    if item["status"] != "open":
        raise HTTPException(400, "这条已经处理过了")
    conn.execute(
        "UPDATE inbox_items SET status = 'dropped', resolved_at = ? WHERE id = ?",
        (datetime.now().isoformat(), item_id),
    )
    return get_inbox_item(conn, item_id)


def reopen_inbox_item(conn, item_id: int) -> dict:
    """处理错了可以放回去。归档只是标记，撤回不会影响任何模块的数据。"""
    item = get_inbox_item(conn, item_id)
    if item["status"] == "open":
        return item
    conn.execute(
        """UPDATE inbox_items SET status = 'open', filed_module = NULL, resolved_at = NULL
           WHERE id = ?""",
        (item_id,),
    )
    return get_inbox_item(conn, item_id)


def delete_inbox_item(conn, item_id: int) -> int:
    get_inbox_item(conn, item_id)
    conn.execute("DELETE FROM inbox_items WHERE id = ?", (item_id,))
    return item_id


def get_inbox_state(conn, limit: int = 50, status: Optional[str] = None) -> dict:
    """未处理列表与轻量汇总。

    「最久的一条放了多少天」用来发现收集箱正在变成垃圾堆——
    它衡量的是这个箱子有没有被清理，不是用户勤不勤快。
    """
    if status is not None and status not in STATUSES:
        raise HTTPException(400, f"未知状态：{status}")
    clause = "WHERE status = ?" if status else "WHERE status = 'open'"
    params = (status,) if status else ()
    rows = conn.execute(
        f"""SELECT * FROM inbox_items {clause}
            ORDER BY created_at DESC, id DESC LIMIT ?""",
        (*params, max(1, min(limit, 200))),
    ).fetchall()

    counts = {
        row["status"]: int(row["count"])
        for row in conn.execute(
            "SELECT status, COUNT(*) AS count FROM inbox_items GROUP BY status"
        ).fetchall()
    }
    oldest = conn.execute(
        "SELECT created_at FROM inbox_items WHERE status = 'open' ORDER BY created_at LIMIT 1"
    ).fetchone()
    oldest_days = None
    if oldest:
        oldest_days = (date.today() - datetime.fromisoformat(oldest["created_at"]).date()).days

    by_target = {
        row["filed_module"]: int(row["count"])
        for row in conn.execute(
            """SELECT filed_module, COUNT(*) AS count FROM inbox_items
               WHERE status = 'filed' AND filed_module IS NOT NULL GROUP BY filed_module"""
        ).fetchall()
    }

    return {
        "items": [dict(row) for row in rows],
        "summary": {
            "open": counts.get("open", 0),
            "filed": counts.get("filed", 0),
            "dropped": counts.get("dropped", 0),
            "oldest_open_days": oldest_days,
            "filed_by_module": by_target,
        },
        "targets": FILE_TARGETS,
    }


SCHEMA = """
CREATE TABLE IF NOT EXISTS inbox_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  content TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'desktop' CHECK (source IN ('desktop','mobile','capture','other')),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','filed','dropped')),
  filed_module TEXT,
  note TEXT DEFAULT '',
  resolved_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inbox_status ON inbox_items(status, created_at);
"""

MODULE = LifeModule(
    key="inbox",
    label="收集箱",
    schema=SCHEMA,
    tables={
        "inbox_items": ["id", "content", "source", "status", "filed_module",
                        "note", "resolved_at", "created_at"],
    },
    optional_tables=frozenset({"inbox_items"}),
)
