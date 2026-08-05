"""平台级接口：整体状态、个人资料与备份恢复。

备份覆盖哪些表由模块注册表决定，新增模块不需要回来改这里。
恢复前会先把当前数据库整份另存为回退文件。
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.backup import build_snapshot
from backend.core.config import SNAPSHOT_VERSION
from backend.core.db import current_path as current_db_path
from backend.core.db import db
from backend.modules import DELETE_ORDER, OPTIONAL_SNAPSHOT_TABLES, SNAPSHOT_COLUMNS
from backend.modules.fitness import get_fitness_state
from backend.modules.goals import get_life_goals_state
from backend.modules.ledger import (
    compute_monthly,
    compute_stats,
    get_accounts,
    get_financial_calendar,
    get_import_batches,
    get_planning,
    get_recent_transfers,
    get_settings,
    get_today_overview,
)
from backend.modules.nutrition import get_nutrition_state
from backend.modules.recovery import get_recovery_state
from backend.modules.reflection import get_reflection_state
from backend.modules.rhythm import get_rhythm_state
from backend.modules.study import get_study_state
from backend.views.overview import get_life_overview

router = APIRouter()


class SettingsIn(BaseModel):
    birth_date: str = Field(..., description="YYYY-MM-DD")
    target_age: int = Field(80, ge=1, le=150)
    currency: str = "CNY"
    show_past: bool = False
    use_initial_assets: bool = False
    initial_assets: float = Field(0.0, ge=0)
    tracking_days_override: int = Field(0, ge=0)
    avg_daily_expense_override: float = Field(0.0, ge=0)


class RestoreSnapshotIn(BaseModel):
    snapshot: dict[str, Any]
    confirmation: Literal["RESTORE"]


@router.get("/api/state")
def get_state():
    with db() as conn:
        s = get_settings(conn)
        stats = compute_stats(conn)
        accounts = get_accounts(conn)
        monthly = compute_monthly(conn)
        txs = conn.execute(
            """SELECT t.*, a.name AS account_name
               FROM transactions t LEFT JOIN accounts a ON a.id = t.account_id
               ORDER BY t.occurred_on DESC, t.id DESC LIMIT 50"""
        ).fetchall()
        return {
            "settings": s,
            "stats": stats,
            "accounts": accounts,
            "monthly": monthly,
            "planning": get_planning(conn),
            "today": get_today_overview(conn),
            "life": get_life_overview(conn),
            "fitness": get_fitness_state(conn),
            "nutrition": get_nutrition_state(conn),
            "recovery": get_recovery_state(conn),
            "study": get_study_state(conn),
            "rhythm": get_rhythm_state(conn),
            "reflection": get_reflection_state(conn),
            "goals": get_life_goals_state(conn),
            "import_batches": get_import_batches(conn),
            "calendar": get_financial_calendar(conn),
            "transfers": get_recent_transfers(conn),
            "transactions": [dict(t) for t in txs],
        }


@router.get("/api/backup/export")
def export_backup():
    with db() as conn:
        return build_snapshot(conn)


@router.post("/api/backup/restore")
def restore_backup(body: RestoreSnapshotIn):
    snapshot = body.snapshot
    if snapshot.get("format") != "wealth-lighthouse-snapshot" or snapshot.get("version") != SNAPSHOT_VERSION:
        raise HTTPException(400, "unsupported snapshot format or version")
    tables = snapshot.get("tables")
    if not isinstance(tables, dict):
        raise HTTPException(400, "snapshot tables are missing")
    for table in SNAPSHOT_COLUMNS:
        if table in OPTIONAL_SNAPSHOT_TABLES and table not in tables:
            tables[table] = []
        if not isinstance(tables.get(table), list):
            raise HTTPException(400, f"snapshot table missing: {table}")
        if len(tables[table]) > 200000:
            raise HTTPException(400, f"snapshot table too large: {table}")
    if not tables["accounts"]:
        raise HTTPException(400, "snapshot must contain at least one account")

    backup_name = f"ledger-auto-before-restore-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.db"
    backup_path = current_db_path().parent / backup_name
    # 两个顺序都由模块注册表推导：写入按模块注册顺序（父表在前），
    # 清空按反向顺序（子表在前）。新增模块不需要回来改这里。
    delete_order = DELETE_ORDER
    insert_order = list(SNAPSHOT_COLUMNS)
    with db() as conn:
        backup_conn = sqlite3.connect(backup_path)
        try:
            conn.backup(backup_conn)
        finally:
            backup_conn.close()
        try:
            for table in delete_order:
                conn.execute(f"DELETE FROM {table}")
            for table in insert_order:
                columns = SNAPSHOT_COLUMNS[table]
                column_sql = ", ".join(columns)
                placeholders = ", ".join("?" for _ in columns)
                for row in tables[table]:
                    if not isinstance(row, dict):
                        raise HTTPException(400, f"invalid row in {table}")
                    conn.execute(
                        f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})",
                        [row.get(column) for column in columns],
                    )
            foreign_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_errors:
                raise HTTPException(400, "snapshot contains broken references")
            orphan_accounts = conn.execute(
                """SELECT COUNT(*) AS count FROM transactions t
                   LEFT JOIN accounts a ON a.id = t.account_id
                   WHERE t.account_id IS NOT NULL AND a.id IS NULL"""
            ).fetchone()["count"]
            if orphan_accounts:
                raise HTTPException(400, "snapshot contains transactions with missing accounts")
        except HTTPException:
            raise
        except sqlite3.Error as exc:
            raise HTTPException(400, f"snapshot restore failed: {exc}") from exc
        restored = build_snapshot(conn)
        return {
            "restored": True,
            "automatic_backup": backup_name,
            "summary": restored["summary"],
            "stats": compute_stats(conn),
        }


@router.post("/api/settings")
def set_settings(body: SettingsIn):
    date.fromisoformat(body.birth_date)  # validate
    now = datetime.now().isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO settings (id, birth_date, target_age, currency, show_past, use_initial_assets, initial_assets, tracking_days_override, avg_daily_expense_override, created_at)
               VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 birth_date                  = excluded.birth_date,
                 target_age                  = excluded.target_age,
                 currency                    = excluded.currency,
                 show_past                   = excluded.show_past,
                 use_initial_assets          = excluded.use_initial_assets,
                 initial_assets              = excluded.initial_assets,
                 tracking_days_override      = excluded.tracking_days_override,
                 avg_daily_expense_override  = excluded.avg_daily_expense_override""",
            (body.birth_date, body.target_age, body.currency,
             int(body.show_past), int(body.use_initial_assets), float(body.initial_assets),
             int(body.tracking_days_override), float(body.avg_daily_expense_override), now),
        )
        return {"settings": get_settings(conn), "stats": compute_stats(conn),
                "planning": get_planning(conn)}
