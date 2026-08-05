"""平台级备份。

导出哪些表、导出哪些列，全部由模块注册表决定；
新增模块只要在自己的 MODULE 里声明表，备份就会自动覆盖到。
"""
from __future__ import annotations

from datetime import datetime

from backend.core.config import SNAPSHOT_VERSION
from backend.modules import SNAPSHOT_COLUMNS
from backend.modules.ledger import compute_stats


def build_snapshot(conn) -> dict:
    tables = {}
    for table, columns in SNAPSHOT_COLUMNS.items():
        column_sql = ", ".join(columns)
        rows = conn.execute(f"SELECT {column_sql} FROM {table}").fetchall()
        tables[table] = [dict(row) for row in rows]
    stats = compute_stats(conn)
    return {
        "format": "wealth-lighthouse-snapshot",
        "version": SNAPSHOT_VERSION,
        "exported_at": datetime.now().isoformat(),
        "summary": {
            "transactions": len(tables["transactions"]),
            "accounts": len(tables["accounts"]),
            "goals": len(tables["savings_goals"]),
            "bills": len(tables["recurring_bills"]),
            "fitness_sessions": len(tables["fitness_sessions"]),
            "nutrition_entries": len(tables["nutrition_entries"]),
            "recovery_checkins": len(tables["recovery_checkins"]),
            "study_sessions": len(tables["study_sessions"]),
            "personal_tasks": len(tables["personal_tasks"]),
            "active_habits": sum(1 for row in tables["habits"] if row["is_active"]),
            "daily_reflections": len(tables["daily_reflections"]),
            "life_goals": len(tables["life_goals"]),
            "goal_milestones": len(tables["goal_milestones"]),
            "current_balance": stats["current_balance"],
        },
        "tables": tables,
    }
