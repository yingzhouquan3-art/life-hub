"""商户分类记忆。

确认一笔捕获时要选分类。同一个商户反复出现，每次都从头选一遍很浪费。
这里保存「关键字 → 分类」的对应关系，下次遇到同一个商户直接预选。

三条边界：

1. **只影响预选，不自动写入。** 规则命中只是把下拉框默认值挑好，
   用户仍然要确认。猜错的代价必须停留在「多点一下」。
2. **只在用户确认时学习。** 确认是用户给出的事实；解析阶段的猜测不算数，
   否则一次误判会自我强化。
3. **规则可以查看和删除。** 一条学错的规则如果没法撤销，
   就会一直错下去，而用户不知道为什么每次都预选错。

规则形式参考 Beancount-Trans 的做法（关键字 + 收款方 → 账户）：
https://github.com/dhr2333/Beancount-Trans
那边没有内置词典，靠用户自己积累；这里预置一小批常见商户当起点，
它们和学来的规则一样可以删掉。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException

from backend.core.config import EXPENSE_CATEGORIES
from backend.core.registry import LifeModule

# 预置的起点。只是常见商户，不求全——真正准的规则来自用户自己的确认。
SEED_RULES = (
    # 餐饮
    ("星巴克", "food"), ("瑞幸", "food"), ("麦当劳", "food"), ("肯德基", "food"),
    ("美团", "food"), ("饿了么", "food"), ("食堂", "food"), ("餐厅", "food"),
    ("奶茶", "food"), ("咖啡", "food"), ("面馆", "food"), ("烧烤", "food"),
    # 交通
    ("滴滴", "transport"), ("高德", "transport"), ("地铁", "transport"),
    ("公交", "transport"), ("铁路12306", "transport"), ("航空", "transport"),
    ("加油", "transport"), ("停车", "transport"), ("哈啰", "transport"), ("青桔", "transport"),
    # 学习
    ("新华书店", "study"), ("书店", "study"), ("图书", "study"),
    ("打印", "study"), ("文具", "study"), ("知网", "study"),
    # 居住
    ("电费", "housing"), ("水费", "housing"), ("燃气", "housing"),
    ("物业", "housing"), ("房租", "housing"),
    # 医疗
    ("医院", "medical"), ("药房", "medical"), ("药店", "medical"), ("体检", "medical"),
    # 娱乐
    ("影城", "entertainment"), ("电影", "entertainment"), ("KTV", "entertainment"),
    ("Steam", "entertainment"), ("游戏", "entertainment"),
    # 数字服务
    ("腾讯视频", "digital"), ("爱奇艺", "digital"), ("哔哩哔哩", "digital"),
    ("网易云", "digital"), ("QQ音乐", "digital"), ("iCloud", "digital"),
    ("话费", "digital"), ("流量", "digital"), ("会员", "digital"),
    # 购物归其他，避免把「超市」一律算成餐饮
    ("超市", "other"), ("便利店", "other"), ("淘宝", "other"),
    ("京东", "other"), ("拼多多", "other"),
)


def _normalise(text: str) -> str:
    return " ".join((text or "").strip().split())


def suggest_category(conn, text: str) -> Optional[dict]:
    """按文本猜一个分类。猜不出来返回 None，不硬给一个默认值。

    多条规则同时命中时取关键字最长的那条：关键字越长越具体，
    「星巴克」应当压过「咖啡」。
    """
    haystack = _normalise(text)
    if not haystack:
        return None
    rows = conn.execute(
        "SELECT * FROM merchant_rules WHERE is_active = 1 ORDER BY LENGTH(keyword) DESC"
    ).fetchall()
    for row in rows:
        if row["keyword"] and row["keyword"] in haystack:
            return {
                "category": row["category"],
                "keyword": row["keyword"],
                "source": row["source"],
                "hits": row["hits"],
            }
    return None


def learn_category(conn, text: str, category: str, keyword: Optional[str] = None) -> Optional[dict]:
    """从一次确认里学。只在用户确认时调用。

    keyword 留空时用整段文本当关键字——那通常是商户名。
    文本为空就不学：拿原始通知全文当关键字永远不会再命中。
    """
    if category not in EXPENSE_CATEGORIES:
        raise HTTPException(400, f"未知分类：{category}")
    key = _normalise(keyword or text)
    if not key or len(key) > 40:
        return None

    now = datetime.now().isoformat()
    existing = conn.execute(
        "SELECT * FROM merchant_rules WHERE keyword = ?", (key,)
    ).fetchone()
    if existing:
        # 改判过就跟着改，并把它重新启用——用户最近一次的选择最可信
        conn.execute(
            """UPDATE merchant_rules
               SET category = ?, hits = hits + 1, is_active = 1,
                   source = CASE WHEN source = 'seed' THEN 'learned' ELSE source END,
                   updated_at = ?
               WHERE id = ?""",
            (category, now, existing["id"]),
        )
        rule_id = existing["id"]
    else:
        cur = conn.execute(
            """INSERT INTO merchant_rules (keyword, category, source, hits, is_active, created_at, updated_at)
               VALUES (?, ?, 'learned', 1, 1, ?, ?)""",
            (key, category, now, now),
        )
        rule_id = cur.lastrowid
    return dict(conn.execute("SELECT * FROM merchant_rules WHERE id = ?", (rule_id,)).fetchone())


def list_rules(conn, include_inactive: bool = False) -> list[dict]:
    clause = "" if include_inactive else "WHERE is_active = 1"
    rows = conn.execute(
        f"""SELECT * FROM merchant_rules {clause}
            ORDER BY source, hits DESC, keyword"""
    ).fetchall()
    return [dict(row) for row in rows]


def delete_rule(conn, rule_id: int) -> int:
    if not conn.execute("SELECT 1 FROM merchant_rules WHERE id = ?", (rule_id,)).fetchone():
        raise HTTPException(404, "rule not found")
    conn.execute("DELETE FROM merchant_rules WHERE id = ?", (rule_id,))
    return rule_id


def get_categorize_state(conn) -> dict:
    rules = list_rules(conn)
    learned = [rule for rule in rules if rule["source"] == "learned"]
    return {
        "rules": rules,
        "summary": {
            "total": len(rules),
            "learned": len(learned),
            "seed": len(rules) - len(learned),
        },
        "note": "规则只用来预选分类，不会自动写入。学错了可以直接删掉。",
    }


def seed_rules(conn) -> None:
    """首次建库时放一批常见商户当起点。已经有规则就不动。"""
    if conn.execute("SELECT 1 FROM merchant_rules LIMIT 1").fetchone():
        return
    now = datetime.now().isoformat()
    conn.executemany(
        """INSERT INTO merchant_rules (keyword, category, source, hits, is_active, created_at, updated_at)
           VALUES (?, ?, 'seed', 0, 1, ?, ?)""",
        [(keyword, category, now, now) for keyword, category in SEED_RULES],
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS merchant_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  keyword TEXT NOT NULL UNIQUE,
  category TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'learned' CHECK (source IN ('seed','learned')),
  hits INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_merchant_rule_active ON merchant_rules(is_active);
"""

MODULE = LifeModule(
    key="categorize",
    label="商户分类记忆",
    schema=SCHEMA,
    tables={
        "merchant_rules": ["id", "keyword", "category", "source", "hits",
                           "is_active", "created_at", "updated_at"],
    },
    optional_tables=frozenset({"merchant_rules"}),
    migrate=seed_rules,
)
