"""生活日历视图。

只读投影：不创建生活记录，也不修改来源模块的数据。
生活事实与生活安排分开展示；没有标记只代表没有记录，不能推导当天没有活动。
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date
from typing import Optional

from fastapi import HTTPException

from backend.core.dates import shift_month
from backend.modules.ledger import get_financial_calendar


def get_life_calendar(
    conn, target_month: Optional[str] = None, selected_date: Optional[str] = None,
) -> dict:
    selected = None
    if selected_date:
        try:
            selected = date.fromisoformat(selected_date)
        except ValueError as exc:
            raise HTTPException(400, "date must be YYYY-MM-DD") from exc
    if target_month:
        if not re.fullmatch(r"\d{4}-\d{2}", target_month):
            raise HTTPException(400, "month must be YYYY-MM")
        try:
            start = date.fromisoformat(f"{target_month}-01")
        except ValueError as exc:
            raise HTTPException(400, "month must be YYYY-MM") from exc
    elif selected:
        start = selected.replace(day=1)
    else:
        start = date.today().replace(day=1)
    month_key = start.strftime("%Y-%m")
    if selected and selected.strftime("%Y-%m") != month_key:
        raise HTTPException(400, "selected date must be inside requested month")
    if selected is None:
        today = date.today()
        selected = today if today.strftime("%Y-%m") == month_key else start
    next_month = shift_month(start, 1)
    end_key = next_month.isoformat()
    days_in_month = monthrange(start.year, start.month)[1]
    days = {
        date(start.year, start.month, day_number).isoformat(): {
            "date": date(start.year, start.month, day_number).isoformat(),
            "fact_count": 0,
            "arrangement_count": 0,
            "modules": [],
        }
        for day_number in range(1, days_in_month + 1)
    }

    fact_sources = (
        ("finance", "transactions", "occurred_on"),
        ("fitness", "fitness_sessions", "occurred_on"),
        ("nutrition", "nutrition_entries", "occurred_on"),
        ("recovery", "recovery_checkins", "occurred_on"),
        ("study", "study_sessions", "occurred_on"),
        ("rhythm", "habit_checkins", "occurred_on"),
        ("reflection", "daily_reflections", "occurred_on"),
    )
    for module, table, date_column in fact_sources:
        rows = conn.execute(
            f"""SELECT {date_column} AS occurred_on, COUNT(*) AS count FROM {table}
                WHERE {date_column} >= ? AND {date_column} < ? GROUP BY {date_column}""",
            (start.isoformat(), end_key),
        ).fetchall()
        for row in rows:
            day = days.get(row["occurred_on"])
            if day:
                day["fact_count"] += int(row["count"] or 0)
                if module not in day["modules"]:
                    day["modules"].append(module)

    task_rows = conn.execute(
        """SELECT due_on, COUNT(*) AS count FROM personal_tasks
           WHERE due_on >= ? AND due_on < ? GROUP BY due_on""",
        (start.isoformat(), end_key),
    ).fetchall()
    for row in task_rows:
        day = days.get(row["due_on"])
        if day:
            day["arrangement_count"] += int(row["count"] or 0)
            if "rhythm" not in day["modules"]:
                day["modules"].append("rhythm")

    for table, date_column in (("life_goals", "target_date"), ("goal_milestones", "target_date")):
        rows = conn.execute(
            f"""SELECT {date_column} AS target_date, COUNT(*) AS count FROM {table}
                WHERE {date_column} >= ? AND {date_column} < ? GROUP BY {date_column}""",
            (start.isoformat(), end_key),
        ).fetchall()
        for row in rows:
            day = days.get(row["target_date"])
            if day:
                day["arrangement_count"] += int(row["count"] or 0)
                if "goals" not in day["modules"]:
                    day["modules"].append("goals")

    financial_calendar = get_financial_calendar(conn, month_key)
    for bill in financial_calendar["bills"]:
        day = days.get(bill["due_date"])
        if day:
            day["arrangement_count"] += 1
            if "finance" not in day["modules"]:
                day["modules"].append("finance")

    selected_key = selected.isoformat()
    facts = []
    transaction_rows = conn.execute(
        """SELECT t.*, a.name AS account_name FROM transactions t
           LEFT JOIN accounts a ON a.id = t.account_id
           WHERE t.occurred_on = ? ORDER BY t.id""",
        (selected_key,),
    ).fetchall()
    for row in transaction_rows:
        item = dict(row)
        direction = "收入" if item["type"] == "income" else "支出"
        facts.append({
            "module": "finance", "kind": "fact", "id": item["id"],
            "title": item["note"] or f"{direction} ¥{round(float(item['amount']), 2):g}",
            "detail": f"{direction} ¥{round(float(item['amount']), 2):g} · {item['account_name'] or '未命名账户'}",
        })
    for row in conn.execute(
        "SELECT * FROM fitness_sessions WHERE occurred_on = ? ORDER BY id", (selected_key,)
    ).fetchall():
        item = dict(row)
        facts.append({
            "module": "fitness", "kind": "fact", "id": item["id"],
            "title": item["note"] or "身体活动",
            "detail": f"{item['duration_minutes']} 分钟 · 强度 {item['intensity']}/10",
        })
    for row in conn.execute(
        "SELECT * FROM nutrition_entries WHERE occurred_on = ? ORDER BY id", (selected_key,)
    ).fetchall():
        item = dict(row)
        nutrition_facts = []
        if item["calories"] is not None:
            nutrition_facts.append(f"{float(item['calories']):g} kcal")
        if item["protein_g"] is not None:
            nutrition_facts.append(f"蛋白质 {float(item['protein_g']):g}g")
        if item["water_ml"] is not None:
            nutrition_facts.append(f"饮水 {float(item['water_ml']):g}ml")
        facts.append({
            "module": "nutrition", "kind": "fact", "id": item["id"],
            "title": item["name"], "detail": " · ".join(nutrition_facts) or "未填写营养数值",
        })
    recovery = conn.execute(
        "SELECT * FROM recovery_checkins WHERE occurred_on = ?", (selected_key,)
    ).fetchone()
    if recovery:
        item = dict(recovery)
        recovery_facts = []
        if item["sleep_hours"] is not None:
            recovery_facts.append(f"睡眠 {float(item['sleep_hours']):g} 小时")
        if item["energy"] is not None:
            recovery_facts.append(f"精力 {item['energy']}/5")
        if item["mood"] is not None:
            recovery_facts.append(f"心情 {item['mood']}/5")
        facts.append({
            "module": "recovery", "kind": "fact", "id": item["id"],
            "title": item["note"] or "恢复记录", "detail": " · ".join(recovery_facts) or "仅填写了主观感受",
        })
    for row in conn.execute(
        "SELECT * FROM study_sessions WHERE occurred_on = ? ORDER BY id", (selected_key,)
    ).fetchall():
        item = dict(row)
        facts.append({
            "module": "study", "kind": "fact", "id": item["id"],
            "title": item["subject"],
            "detail": f"{item['duration_minutes']} 分钟 · 专注 {item['focus']}/5",
        })
    for row in conn.execute(
        """SELECT c.id, h.name, h.category FROM habit_checkins c
           JOIN habits h ON h.id = c.habit_id WHERE c.occurred_on = ? ORDER BY c.id""",
        (selected_key,),
    ).fetchall():
        item = dict(row)
        facts.append({
            "module": "rhythm", "kind": "fact", "id": item["id"],
            "title": item["name"], "detail": "习惯打卡",
        })
    reflection = conn.execute(
        "SELECT * FROM daily_reflections WHERE occurred_on = ?", (selected_key,)
    ).fetchone()
    if reflection:
        item = dict(reflection)
        values = [item["highlight"], item["challenge"], item["gratitude"], item["note"]]
        preview = next((value for value in values if value), "每日回顾")
        facts.append({
            "module": "reflection", "kind": "fact", "id": item["id"],
            "title": preview, "detail": f"填写了 {sum(bool(value) for value in values)} 项",
        })

    arrangements = []
    for row in conn.execute(
        "SELECT * FROM personal_tasks WHERE due_on = ? ORDER BY status, priority DESC, id",
        (selected_key,),
    ).fetchall():
        item = dict(row)
        arrangements.append({
            "module": "rhythm", "kind": "arrangement", "id": item["id"],
            "title": item["title"],
            "detail": f"待办 · {'已完成' if item['status'] == 'done' else '未完成'}",
            "status": item["status"],
        })
    for row in conn.execute(
        "SELECT * FROM life_goals WHERE target_date = ? ORDER BY status, id", (selected_key,)
    ).fetchall():
        item = dict(row)
        status_label = {"active": "进行中", "paused": "已暂停", "completed": "已完成"}[item["status"]]
        arrangements.append({
            "module": "goals", "kind": "arrangement", "id": item["id"],
            "title": item["title"], "detail": f"生活目标日期 · {status_label}",
            "status": item["status"],
        })
    for row in conn.execute(
        """SELECT m.*, g.title AS goal_title FROM goal_milestones m
           JOIN life_goals g ON g.id = m.goal_id
           WHERE m.target_date = ? ORDER BY m.status, m.id""",
        (selected_key,),
    ).fetchall():
        item = dict(row)
        arrangements.append({
            "module": "goals", "kind": "arrangement", "id": item["id"],
            "title": item["title"],
            "detail": f"里程碑 · {item['goal_title']} · {'已完成' if item['status'] == 'done' else '未完成'}",
            "status": item["status"],
        })
    for bill in financial_calendar["bills"]:
        if bill["due_date"] == selected_key:
            arrangements.append({
                "module": "finance", "kind": "arrangement", "id": bill["id"],
                "title": bill["name"],
                "detail": f"固定账单 ¥{float(bill['amount']):g} · {'已支付' if bill['is_paid'] else '未支付'}",
                "status": bill["status"],
            })

    day_values = list(days.values())
    return {
        "month": month_key,
        "selected_date": selected_key,
        "today": date.today().isoformat(),
        "days_in_month": days_in_month,
        "first_weekday": start.weekday(),
        "days": day_values,
        "summary": {
            "active_days": sum(1 for day in day_values if day["fact_count"] or day["arrangement_count"]),
            "fact_count": sum(day["fact_count"] for day in day_values),
            "arrangement_count": sum(day["arrangement_count"] for day in day_values),
        },
        "selected": {"date": selected_key, "facts": facts, "arrangements": arrangements},
    }
