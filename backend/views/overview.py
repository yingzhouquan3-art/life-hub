"""生活总览视图。

只读取各模块公开的摘要来汇总当日状态，不直接修改任何模块的记录。
"""
from __future__ import annotations

from datetime import date

from backend.modules.fitness import get_fitness_state
from backend.modules.ledger import get_today_overview
from backend.modules.nutrition import get_nutrition_state
from backend.modules.recovery import get_recovery_state
from backend.modules.reflection import get_reflection_state
from backend.modules.rhythm import get_rhythm_state
from backend.modules.study import get_study_state


def get_life_overview(conn) -> dict:
    finance = get_today_overview(conn)
    fitness = get_fitness_state(conn)
    nutrition = get_nutrition_state(conn)
    recovery = get_recovery_state(conn)
    study = get_study_state(conn)
    rhythm = get_rhythm_state(conn)
    reflection = get_reflection_state(conn)
    actions = []
    if rhythm["task_summary"]["overdue"]:
        actions.append({"module": "rhythm", "title": f"处理 {rhythm['task_summary']['overdue']} 项逾期待办", "detail": "可以完成、改期或删除；逾期只是日期状态。"})
    elif rhythm["task_summary"]["today_pending"]:
        actions.append({"module": "rhythm", "title": "完成下一项今日待办", "detail": "只选择眼前最具体的一件事。"})
    elif rhythm["habit_summary"]["pending_today"]:
        actions.append({"module": "rhythm", "title": "给一个每日习惯打卡", "detail": "打卡记录实践，不评价好坏。"})
    elif rhythm["task_summary"]["today_total"] == 0 and rhythm["habit_summary"]["total"] == 0:
        actions.append({"module": "rhythm", "title": "建立今天的个人节奏", "detail": "添加一项待办或一个每日习惯即可。"})
    if reflection["selected"] is None:
        actions.append({"module": "reflection", "title": "写下一条今日回顾", "detail": "亮点、困难、感谢或自由记录，任选一项即可。"})
    if fitness["today"]["count"] == 0:
        actions.append({"module": "fitness", "title": "记录一次身体活动", "detail": "散步、拉伸或正式训练都可以。"})
    if nutrition["today"]["count"] == 0:
        actions.append({"module": "nutrition", "title": "记下今天第一餐", "detail": "营养数值可以留空，先建立记录习惯。"})
    if recovery["today"] is None:
        actions.append({"module": "recovery", "title": "记录今天的恢复状态", "detail": "睡眠、精力或心情任选一项即可。"})
    if study["today"]["count"] == 0:
        actions.append({"module": "study", "title": "留下一段学习专注", "detail": "完成后记录时长，不需要先制定复杂计划。"})
    if finance.get("available_today") is None:
        actions.append({"module": "finance", "title": "补充本月或学期预算", "detail": "让账本给出今天可用金额。"})
    finance_signal = finance.get("available_today") is not None or float(finance.get("today_expense") or 0) > 0
    rhythm_signal = rhythm["task_summary"]["today_done"] > 0 or rhythm["habit_summary"]["completed_today"] > 0
    completed = sum([
        finance_signal,
        fitness["today"]["count"] > 0,
        nutrition["today"]["count"] > 0,
        recovery["today"] is not None,
        study["today"]["count"] > 0,
        rhythm_signal,
    ])
    return {
        "date": date.today().isoformat(),
        "headline": "今天的生活轨迹已经很完整" if completed >= 4 else ("今天已经留下生活轨迹" if completed else "从一条真实记录开始今天"),
        "completed_signals": completed,
        "finance": finance,
        "fitness": fitness,
        "nutrition": nutrition,
        "recovery": recovery,
        "study": study,
        "rhythm": rhythm,
        "reflection": reflection,
        "actions": actions[:5],
    }
