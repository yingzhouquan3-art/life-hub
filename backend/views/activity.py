"""跨模块生活条目的统一只读表示。

[POS] backend/views/activity.py — 搜索、轨迹等跨模块视图共同使用的深模块
[INPUT] 各来源模块公开存储的生活事实、安排与长期条目
[OUTPUT] collect_life_items(conn) -> 统一条目列表

这个模块只负责翻译，不拥有任何来源数据。调用者不需要知道表名、字段名或中文标签，
但编辑、删除和状态变化仍必须回到来源模块。
"""
from __future__ import annotations

LIFE_ITEM_MODULES = frozenset(
    {"finance", "fitness", "body", "nutrition", "recovery", "study", "rhythm", "reflection", "goals"}
)
LIFE_ITEM_KINDS = frozenset({"fact", "arrangement", "reference"})

SOURCE_LABELS = {
    "family_support": "家庭生活费", "scholarship": "奖助学金", "part_time": "兼职实习",
    "project": "个人项目", "investment": "投资所得", "other": "其他",
}
CATEGORY_LABELS = {
    "food": "餐饮", "transport": "交通", "study": "学习", "housing": "住宿",
    "medical": "医疗", "entertainment": "娱乐", "social": "社交", "digital": "数字服务",
    "other": "其他", "personal": "个人", "health": "身体", "finance": "财务",
}
ACTIVITY_LABELS = {
    "strength": "力量", "cardio": "有氧", "sport": "运动", "mobility": "拉伸", "other": "活动",
}
MEAL_LABELS = {"breakfast": "早餐", "lunch": "午餐", "dinner": "晚餐", "snack": "加餐"}


def _item(module: str, kind: str, source_id: int, occurred_on: str, title: str, detail: str) -> dict:
    return {
        "module": module, "kind": kind, "id": source_id,
        "date": occurred_on or None, "title": title, "detail": detail,
    }


def collect_life_items(conn) -> list[dict]:
    """把所有来源翻译成同一只读表示，并按日期倒序返回。"""
    items: list[dict] = []

    for row in conn.execute(
        """SELECT t.*, a.name AS account_name FROM transactions t
           LEFT JOIN accounts a ON a.id = t.account_id"""
    ).fetchall():
        value = dict(row)
        direction = "收入" if value["type"] == "income" else "支出"
        classification = (
            SOURCE_LABELS.get(value["source"], value["source"])
            if value["type"] == "income"
            else CATEGORY_LABELS.get(value["category"], value["category"])
        )
        items.append(_item(
            "finance", "fact", value["id"], value["occurred_on"],
            value["note"] or f"{direction} ¥{float(value['amount']):g}",
            f"{direction} ¥{float(value['amount']):g} · {value['account_name'] or '未命名账户'} · {classification}",
        ))

    for row in conn.execute("SELECT * FROM recurring_bills WHERE is_active = 1").fetchall():
        value = dict(row)
        cycle = value.get("cycle") or "monthly"
        day = value["day_of_month"]
        if cycle == "yearly" and value.get("anchor_month"):
            schedule = f"每年 {value['anchor_month']} 月 {day} 日"
        elif cycle == "quarterly" and value.get("anchor_month"):
            schedule = f"每季度（从 {value['anchor_month']} 月起）{day} 日"
        else:
            schedule = f"每月 {day} 日"
        items.append(_item(
            "finance", "arrangement", value["id"], "", value["name"],
            f"固定支出 · {schedule} · ¥{float(value['amount']):g} · {CATEGORY_LABELS.get(value['category'], value['category'])}",
        ))

    for row in conn.execute("SELECT * FROM fitness_sessions").fetchall():
        value = dict(row)
        activity = ACTIVITY_LABELS.get(value["activity"], value["activity"])
        items.append(_item(
            "fitness", "fact", value["id"], value["occurred_on"], value["note"] or activity,
            f"{activity} · {value['duration_minutes']} 分钟 · 强度 {value['intensity']}/10",
        ))

    for row in conn.execute("SELECT * FROM body_measurements").fetchall():
        value = dict(row)
        detail = []
        if value["weight_kg"] is not None:
            detail.append(f"体重 {float(value['weight_kg']):g}kg")
        if value["body_fat_pct"] is not None:
            detail.append(f"体脂 {float(value['body_fat_pct']):g}%")
        for field, label in (("neck_cm", "颈围"), ("chest_cm", "胸围"), ("waist_cm", "腰围"),
                             ("hip_cm", "臀围"), ("arm_cm", "上臂围"), ("thigh_cm", "大腿围")):
            if value[field] is not None:
                detail.append(f"{label} {float(value[field]):g}cm")
        if value["note"]:
            detail.append(value["note"])
        items.append(_item(
            "body", "fact", value["id"], value["occurred_on"], value["note"] or "身体指标",
            " · ".join(detail) or "身体指标记录",
        ))

    for row in conn.execute("SELECT * FROM nutrition_entries").fetchall():
        value = dict(row)
        detail = [MEAL_LABELS.get(value["meal_type"], value["meal_type"])]
        if value["calories"] is not None:
            detail.append(f"{float(value['calories']):g} kcal")
        if value["protein_g"] is not None:
            detail.append(f"蛋白质 {float(value['protein_g']):g}g")
        if value["water_ml"] is not None:
            detail.append(f"饮水 {float(value['water_ml']):g}ml")
        if value["note"]:
            detail.append(value["note"])
        items.append(_item(
            "nutrition", "fact", value["id"], value["occurred_on"], value["name"], " · ".join(detail)
        ))

    for row in conn.execute("SELECT * FROM recovery_checkins").fetchall():
        value = dict(row)
        detail = []
        if value["sleep_hours"] is not None:
            detail.append(f"睡眠 {float(value['sleep_hours']):g} 小时")
        if value["energy"] is not None:
            detail.append(f"精力 {value['energy']}/5")
        if value["mood"] is not None:
            detail.append(f"心情 {value['mood']}/5")
        items.append(_item(
            "recovery", "fact", value["id"], value["occurred_on"], value["note"] or "恢复记录",
            " · ".join(detail) or "恢复与睡眠记录",
        ))

    for row in conn.execute("SELECT * FROM study_sessions").fetchall():
        value = dict(row)
        note = f" · {value['note']}" if value["note"] else ""
        items.append(_item(
            "study", "fact", value["id"], value["occurred_on"], value["subject"],
            f"学习 {value['duration_minutes']} 分钟 · 专注 {value['focus']}/5{note}",
        ))

    for row in conn.execute("SELECT * FROM personal_tasks").fetchall():
        value = dict(row)
        note = f" · {value['note']}" if value["note"] else ""
        items.append(_item(
            "rhythm", "arrangement", value["id"], value["due_on"], value["title"],
            f"待办 · {CATEGORY_LABELS.get(value['category'], value['category'])} · {'已完成' if value['status'] == 'done' else '未完成'}{note}",
        ))

    for row in conn.execute("SELECT * FROM habits").fetchall():
        value = dict(row)
        items.append(_item(
            "rhythm", "reference", value["id"], value["created_at"][:10], value["name"],
            f"每日习惯 · {CATEGORY_LABELS.get(value['category'], value['category'])} · {'使用中' if value['is_active'] else '已归档'}",
        ))

    for row in conn.execute(
        """SELECT c.id, c.occurred_on, h.name, h.category FROM habit_checkins c
           JOIN habits h ON h.id = c.habit_id"""
    ).fetchall():
        value = dict(row)
        items.append(_item(
            "rhythm", "fact", value["id"], value["occurred_on"], value["name"],
            f"习惯打卡 · {CATEGORY_LABELS.get(value['category'], value['category'])}",
        ))

    for row in conn.execute("SELECT * FROM daily_reflections").fetchall():
        value = dict(row)
        sections = [("亮点", value["highlight"]), ("困难", value["challenge"]),
                    ("感谢", value["gratitude"]), ("记录", value["note"])]
        non_empty = [f"{label}：{text}" for label, text in sections if text]
        items.append(_item(
            "reflection", "fact", value["id"], value["occurred_on"],
            next((text for _, text in sections if text), "每日回顾"), " · ".join(non_empty),
        ))

    for row in conn.execute("SELECT * FROM life_goals").fetchall():
        value = dict(row)
        status = {"active": "进行中", "paused": "已暂停", "completed": "已完成"}[value["status"]]
        motivation = f" · {value['motivation']}" if value["motivation"] else ""
        items.append(_item(
            "goals", "arrangement", value["id"], value["target_date"] or value["created_at"][:10], value["title"],
            f"生活目标 · {CATEGORY_LABELS.get(value['category'], value['category'])} · {status}{motivation}",
        ))

    for row in conn.execute(
        """SELECT m.*, g.title AS goal_title FROM goal_milestones m
           JOIN life_goals g ON g.id = m.goal_id"""
    ).fetchall():
        value = dict(row)
        items.append(_item(
            "goals", "arrangement", value["id"], value["target_date"] or value["created_at"][:10], value["title"],
            f"里程碑 · {value['goal_title']} · {'已完成' if value['status'] == 'done' else '未完成'}",
        ))

    items.sort(key=lambda value: (value["date"] or "", value["module"], value["id"]), reverse=True)
    return items
