"""全局生活搜索视图。

只读：不得因为查询而创建、更新或删除任何来源数据。
搜索结果必须标注来源模块；没有结果只表示当前条件下没有匹配。
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import HTTPException


def search_life(
    conn, *, query: str, module: Optional[str] = None,
    date_from: Optional[str] = None, date_to: Optional[str] = None, limit: int = 100,
) -> dict:
    query = query.strip()
    if not query:
        raise HTTPException(400, "search query is required")
    if len(query) > 100:
        raise HTTPException(400, "search query is too long")
    modules = {"finance", "fitness", "nutrition", "recovery", "study", "rhythm", "reflection", "goals"}
    if module and module not in modules:
        raise HTTPException(400, "invalid life search module")
    for value, label in ((date_from, "date_from"), (date_to, "date_to")):
        if value:
            try:
                date.fromisoformat(value)
            except ValueError as exc:
                raise HTTPException(400, f"{label} must be YYYY-MM-DD") from exc
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, "date_from must not be after date_to")
    safe_limit = min(max(int(limit), 1), 200)
    needle = query.casefold()
    results: list[dict] = []
    source_labels = {
        "family_support": "家庭生活费", "scholarship": "奖助学金", "part_time": "兼职实习",
        "project": "个人项目", "investment": "投资所得", "other": "其他",
    }
    category_labels = {
        "food": "餐饮", "transport": "交通", "study": "学习", "housing": "住宿",
        "medical": "医疗", "entertainment": "娱乐", "social": "社交", "digital": "数字服务",
        "other": "其他", "personal": "个人", "health": "身体", "finance": "财务",
    }
    activity_labels = {"strength": "力量", "cardio": "有氧", "sport": "运动", "mobility": "拉伸", "other": "活动"}
    meal_labels = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐"}

    def add_result(source_module: str, kind: str, source_id: int, occurred_on: str, title: str, detail: str):
        if module and module != source_module:
            return
        if occurred_on:
            if date_from and occurred_on < date_from:
                return
            if date_to and occurred_on > date_to:
                return
        elif date_from or date_to:
            return
        haystack = f"{title} {detail}".casefold()
        if needle not in haystack:
            return
        results.append({
            "module": source_module, "kind": kind, "id": source_id,
            "date": occurred_on or None, "title": title, "detail": detail,
        })

    for row in conn.execute(
        """SELECT t.*, a.name AS account_name FROM transactions t
           LEFT JOIN accounts a ON a.id = t.account_id"""
    ).fetchall():
        item = dict(row)
        direction = "收入" if item["type"] == "income" else "支出"
        classification = source_labels.get(item["source"], item["source"]) if item["type"] == "income" else category_labels.get(item["category"], item["category"])
        add_result(
            "finance", "fact", item["id"], item["occurred_on"],
            item["note"] or f"{direction} ¥{float(item['amount']):g}",
            f"{direction} ¥{float(item['amount']):g} · {item['account_name'] or '未命名账户'} · {classification}",
        )
    for row in conn.execute("SELECT * FROM recurring_bills WHERE is_active = 1").fetchall():
        item = dict(row)
        add_result(
            "finance", "arrangement", item["id"], "", item["name"],
            f"每月 {item['day_of_month']} 日 · ¥{float(item['amount']):g} · {category_labels.get(item['category'], item['category'])}",
        )
    for row in conn.execute("SELECT * FROM fitness_sessions").fetchall():
        item = dict(row)
        activity = activity_labels.get(item["activity"], item["activity"])
        add_result(
            "fitness", "fact", item["id"], item["occurred_on"], item["note"] or activity,
            f"{activity} · {item['duration_minutes']} 分钟 · 强度 {item['intensity']}/10",
        )
    for row in conn.execute("SELECT * FROM nutrition_entries").fetchall():
        item = dict(row)
        detail_parts = [meal_labels.get(item["meal_type"], item["meal_type"])]
        if item["calories"] is not None:
            detail_parts.append(f"{float(item['calories']):g} kcal")
        if item["protein_g"] is not None:
            detail_parts.append(f"蛋白质 {float(item['protein_g']):g}g")
        if item["water_ml"] is not None:
            detail_parts.append(f"饮水 {float(item['water_ml']):g}ml")
        if item["note"]:
            detail_parts.append(item["note"])
        add_result("nutrition", "fact", item["id"], item["occurred_on"], item["name"], " · ".join(detail_parts))
    for row in conn.execute("SELECT * FROM recovery_checkins").fetchall():
        item = dict(row)
        detail_parts = []
        if item["sleep_hours"] is not None:
            detail_parts.append(f"睡眠 {float(item['sleep_hours']):g} 小时")
        if item["energy"] is not None:
            detail_parts.append(f"精力 {item['energy']}/5")
        if item["mood"] is not None:
            detail_parts.append(f"心情 {item['mood']}/5")
        add_result(
            "recovery", "fact", item["id"], item["occurred_on"], item["note"] or "恢复记录",
            " · ".join(detail_parts) or "恢复与睡眠记录",
        )
    for row in conn.execute("SELECT * FROM study_sessions").fetchall():
        item = dict(row)
        add_result(
            "study", "fact", item["id"], item["occurred_on"], item["subject"],
            f"学习 {item['duration_minutes']} 分钟 · 专注 {item['focus']}/5{f' · {item['note']}' if item['note'] else ''}",
        )
    for row in conn.execute("SELECT * FROM personal_tasks").fetchall():
        item = dict(row)
        add_result(
            "rhythm", "arrangement", item["id"], item["due_on"], item["title"],
            f"待办 · {category_labels.get(item['category'], item['category'])} · {'已完成' if item['status'] == 'done' else '未完成'}{f' · {item['note']}' if item['note'] else ''}",
        )
    for row in conn.execute("SELECT * FROM habits").fetchall():
        item = dict(row)
        add_result(
            "rhythm", "reference", item["id"], item["created_at"][:10], item["name"],
            f"每日习惯 · {category_labels.get(item['category'], item['category'])} · {'使用中' if item['is_active'] else '已归档'}",
        )
    for row in conn.execute(
        """SELECT c.id, c.occurred_on, h.name, h.category FROM habit_checkins c
           JOIN habits h ON h.id = c.habit_id"""
    ).fetchall():
        item = dict(row)
        add_result(
            "rhythm", "fact", item["id"], item["occurred_on"], item["name"],
            f"习惯打卡 · {category_labels.get(item['category'], item['category'])}",
        )
    for row in conn.execute("SELECT * FROM daily_reflections").fetchall():
        item = dict(row)
        sections = [
            ("亮点", item["highlight"]), ("困难", item["challenge"]),
            ("感谢", item["gratitude"]), ("记录", item["note"]),
        ]
        non_empty = [f"{label}：{value}" for label, value in sections if value]
        add_result(
            "reflection", "fact", item["id"], item["occurred_on"],
            next((value for _, value in sections if value), "每日回顾"), " · ".join(non_empty),
        )
    for row in conn.execute("SELECT * FROM life_goals").fetchall():
        item = dict(row)
        status = {"active": "进行中", "paused": "已暂停", "completed": "已完成"}[item["status"]]
        add_result(
            "goals", "arrangement", item["id"], item["target_date"] or item["created_at"][:10], item["title"],
            f"生活目标 · {category_labels.get(item['category'], item['category'])} · {status}{f' · {item['motivation']}' if item['motivation'] else ''}",
        )
    for row in conn.execute(
        """SELECT m.*, g.title AS goal_title FROM goal_milestones m
           JOIN life_goals g ON g.id = m.goal_id"""
    ).fetchall():
        item = dict(row)
        add_result(
            "goals", "arrangement", item["id"], item["target_date"] or item["created_at"][:10], item["title"],
            f"里程碑 · {item['goal_title']} · {'已完成' if item['status'] == 'done' else '未完成'}",
        )
    results.sort(key=lambda item: (item["date"] or "", item["module"], item["id"]), reverse=True)
    total = len(results)
    by_module = {name: sum(1 for item in results if item["module"] == name) for name in modules}
    return {
        "query": query,
        "filters": {"module": module, "date_from": date_from, "date_to": date_to},
        "summary": {"total": total, "by_module": by_module},
        "results": results[:safe_limit],
        "limit": safe_limit,
        "truncated": total > safe_limit,
    }
