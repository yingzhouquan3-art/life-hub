"""个人账本模块的 HTTP 接口。

家庭生活费与自主收入在这里保持分离；规划中的预计生活费不会写成一笔收入。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.core.config import EXPENSE_CATEGORIES
from backend.core.db import db
from backend.modules.ledger import (
    compute_monthly,
    compute_stats,
    create_transaction,
    get_accounts,
    get_annual_report,
    get_financial_calendar,
    get_import_batches,
    get_planning,
    get_recent_transfers,
    get_subscription_overview,
    get_today_overview,
    parse_quick_entry,
)

router = APIRouter()


class TransactionIn(BaseModel):
    occurred_on: Optional[str] = None
    type: Literal["income", "expense"]
    source: Optional[
        Literal["family_support", "scholarship", "part_time", "project", "investment", "other"]
    ] = None
    amount: float = Field(..., gt=0)
    category: Optional[
        Literal["food", "transport", "study", "housing", "medical", "entertainment", "social", "digital", "other"]
    ] = None
    account_id: Optional[int] = None
    note: str = ""


class AccountIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=30)
    type: Literal["bank", "wechat", "alipay", "campus", "cash", "other"] = "other"
    opening_balance: float = 0.0


class TransferIn(BaseModel):
    from_account_id: int
    to_account_id: int
    amount: float = Field(..., gt=0)
    occurred_on: Optional[str] = None
    note: str = Field("", max_length=80)


class ReconcileIn(BaseModel):
    actual_balance: float
    occurred_on: Optional[str] = None
    note: str = Field("余额校准", max_length=80)


class PlanningSettingsIn(BaseModel):
    monthly_allowance_amount: float = Field(0.0, ge=0)
    allowance_day: int = Field(1, ge=1, le=28)
    monthly_spending_budget: float = Field(0.0, ge=0)


class SemesterSettingsIn(BaseModel):
    start_date: str
    end_date: str
    total_budget: float = Field(..., ge=0)
    mode: Literal["in_school", "vacation"] = "in_school"


class QuickEntryIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=120)


class SavingsGoalIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    target_amount: float = Field(..., gt=0)
    saved_amount: float = Field(0.0, ge=0)
    target_date: Optional[str] = None


class SavingsGoalProgressIn(BaseModel):
    saved_amount: float = Field(..., ge=0)


class CategoryBudgetsIn(BaseModel):
    budgets: dict[str, float]


class ImportTransactionIn(BaseModel):
    occurred_on: str
    type: Literal["income", "expense"]
    amount: float = Field(..., gt=0)
    source: Optional[
        Literal["family_support", "scholarship", "part_time", "project", "investment", "other"]
    ] = None
    category: Optional[
        Literal["food", "transport", "study", "housing", "medical", "entertainment", "social", "digital", "other"]
    ] = None
    account_id: Optional[int] = None
    note: str = Field("", max_length=120)


class ImportBatchIn(BaseModel):
    filename: str = Field("statement.csv", min_length=1, max_length=255)
    rows: list[ImportTransactionIn] = Field(..., min_length=1, max_length=2000)


class RecurringBillIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=40)
    amount: float = Field(..., gt=0)
    day_of_month: int = Field(..., ge=1, le=28)
    cycle: Literal["monthly", "quarterly", "yearly"] = "monthly"
    # 季付与年付的锚点月份（1-12）。留空表示无法推算，退化成每月提醒。
    anchor_month: Optional[int] = Field(None, ge=1, le=12)
    category: Literal["food", "transport", "study", "housing", "medical", "entertainment", "social", "digital", "other"]
    account_id: int
    note: str = Field("", max_length=100)


class PayRecurringBillIn(BaseModel):
    month: Optional[str] = None
    paid_on: Optional[str] = None


@router.get("/api/today")
def get_today_state():
    with db() as conn:
        return get_today_overview(conn)


@router.post("/api/quick-entry/parse")
def parse_quick_transaction(body: QuickEntryIn):
    with db() as conn:
        return parse_quick_entry(conn, body.text)


@router.get("/api/dashboard")
def get_dashboard(month: Optional[str] = None):
    with db() as conn:
        return {
            "accounts": get_accounts(conn),
            "monthly": compute_monthly(conn, month),
            "stats": compute_stats(conn),
        }


@router.get("/api/search/transactions")
def search_transactions(
    q: str = "",
    tx_type: Optional[str] = Query(None, alias="type"),
    category: Optional[str] = None,
    source: Optional[str] = None,
    account_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
):
    if tx_type not in (None, "", "income", "expense"):
        raise HTTPException(400, "invalid transaction type")
    if category and category not in EXPENSE_CATEGORIES:
        raise HTTPException(400, "invalid category")
    valid_sources = {"family_support", "scholarship", "part_time", "project", "investment", "other"}
    if source and source not in valid_sources:
        raise HTTPException(400, "invalid source")
    if date_from:
        date.fromisoformat(date_from)
    if date_to:
        date.fromisoformat(date_to)
    conditions = []
    params: list[Any] = []
    if q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append("(t.note LIKE ? OR a.name LIKE ? OR CAST(t.amount AS TEXT) LIKE ?)")
        params.extend([pattern, pattern, pattern])
    if tx_type:
        conditions.append("t.type = ?")
        params.append(tx_type)
    if category:
        conditions.append("t.category = ?")
        params.append(category)
    if source:
        conditions.append("t.source = ?")
        params.append(source)
    if account_id:
        conditions.append("t.account_id = ?")
        params.append(account_id)
    if date_from:
        conditions.append("t.occurred_on >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("t.occurred_on <= ?")
        params.append(date_to)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    safe_limit = min(max(limit, 1), 1000)
    safe_offset = max(offset, 0)
    with db() as conn:
        rows = conn.execute(
            f"""SELECT t.*, a.name AS account_name FROM transactions t
                 LEFT JOIN accounts a ON a.id = t.account_id
                 {where}
                 ORDER BY t.occurred_on DESC, t.id DESC LIMIT ? OFFSET ?""",
            (*params, safe_limit, safe_offset),
        ).fetchall()
        summary = conn.execute(
            f"""SELECT COUNT(*) AS count,
                       COALESCE(SUM(CASE WHEN t.type = 'income' THEN t.amount ELSE 0 END), 0) AS income,
                       COALESCE(SUM(CASE WHEN t.type = 'expense' THEN t.amount ELSE 0 END), 0) AS expense
                 FROM transactions t LEFT JOIN accounts a ON a.id = t.account_id {where}""",
            params,
        ).fetchone()
        return {
            "transactions": [dict(row) for row in rows],
            "summary": {
                "count": int(summary["count"] or 0),
                "income": round(float(summary["income"] or 0), 2),
                "expense": round(float(summary["expense"] or 0), 2),
                "net": round(float(summary["income"] or 0) - float(summary["expense"] or 0), 2),
            },
            "limit": safe_limit,
            "offset": safe_offset,
        }


@router.get("/api/reports/annual")
def annual_report(year: int):
    with db() as conn:
        return get_annual_report(conn, year)


@router.get("/api/planning")
def get_planning_state():
    with db() as conn:
        return get_planning(conn)


@router.get("/api/calendar")
def get_calendar_state(month: Optional[str] = None):
    with db() as conn:
        return get_financial_calendar(conn, month)


@router.get("/api/subscriptions")
def subscription_overview():
    """我到底订了多少东西，一个月和一年各要花多少。"""
    with db() as conn:
        return get_subscription_overview(conn)


@router.post("/api/bills")
def add_recurring_bill(body: RecurringBillIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "bill name is required")
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM accounts WHERE id = ? AND is_active = 1", (body.account_id,)
        ).fetchone():
            raise HTTPException(400, "invalid account")
        anchor = body.anchor_month
        if body.cycle != "monthly" and anchor is None:
            anchor = date.today().month  # 没指定就以建单当月为锚点
        cur = conn.execute(
            """INSERT INTO recurring_bills
               (name, amount, day_of_month, category, account_id, note, is_active,
                created_at, cycle, anchor_month)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (name, body.amount, body.day_of_month, body.category,
             body.account_id, body.note.strip(), datetime.now().isoformat(),
             body.cycle, anchor),
        )
        return {
            "bill_id": cur.lastrowid,
            "calendar": get_financial_calendar(conn),
            "subscriptions": get_subscription_overview(conn),
        }


@router.delete("/api/bills/{bill_id}")
def delete_recurring_bill(bill_id: int):
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM recurring_bills WHERE id = ? AND is_active = 1", (bill_id,)
        ).fetchone():
            raise HTTPException(404, "bill not found")
        conn.execute("UPDATE recurring_bills SET is_active = 0 WHERE id = ?", (bill_id,))
        return {
            "deleted_bill": bill_id,
            "calendar": get_financial_calendar(conn),
            "subscriptions": get_subscription_overview(conn),
        }


@router.post("/api/bills/{bill_id}/pay")
def pay_recurring_bill(bill_id: int, body: PayRecurringBillIn):
    paid_on = body.paid_on or date.today().isoformat()
    try:
        paid_date = date.fromisoformat(paid_on)
    except ValueError as exc:
        raise HTTPException(400, "paid_on must be YYYY-MM-DD") from exc
    month_key = body.month or paid_date.strftime("%Y-%m")
    try:
        date.fromisoformat(f"{month_key}-01")
    except ValueError as exc:
        raise HTTPException(400, "month must be YYYY-MM") from exc
    with db() as conn:
        bill = conn.execute(
            """SELECT b.*, a.name AS account_name FROM recurring_bills b
               JOIN accounts a ON a.id = b.account_id
               WHERE b.id = ? AND b.is_active = 1 AND a.is_active = 1""",
            (bill_id,),
        ).fetchone()
        if not bill:
            raise HTTPException(404, "bill not found")
        existing = conn.execute(
            """SELECT p.*, t.id AS transaction_exists FROM recurring_bill_payments p
               LEFT JOIN transactions t ON t.id = p.transaction_id
               WHERE p.bill_id = ? AND p.month = ?""",
            (bill_id, month_key),
        ).fetchone()
        if existing and existing["transaction_exists"]:
            raise HTTPException(409, "this bill is already paid for the month")
        if existing:
            conn.execute("DELETE FROM recurring_bill_payments WHERE id = ?", (existing["id"],))
        before = compute_stats(conn)
        cur = conn.execute(
            """INSERT INTO transactions
               (occurred_on, type, source, category, account_id, amount, note, created_at)
               VALUES (?, 'expense', 'expense', ?, ?, ?, ?, ?)""",
            (paid_on, bill["category"], bill["account_id"], bill["amount"],
             f"固定支出：{bill['name']}", datetime.now().isoformat()),
        )
        tx_id = cur.lastrowid
        conn.execute(
            """INSERT INTO recurring_bill_payments
               (bill_id, month, transaction_id, paid_on, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (bill_id, month_key, tx_id, paid_on, datetime.now().isoformat()),
        )
        after = compute_stats(conn)
        return {
            "transaction_id": tx_id,
            "stats": after,
            "accounts": get_accounts(conn),
            "monthly": compute_monthly(conn),
            "planning": get_planning(conn),
            "calendar": get_financial_calendar(conn, month_key),
            "lit_before": before["lit_count"],
            "lit_after": after["lit_count"],
        }


@router.delete("/api/bills/{bill_id}/payments/{month_key}")
def undo_recurring_bill_payment(bill_id: int, month_key: str):
    try:
        date.fromisoformat(f"{month_key}-01")
    except ValueError as exc:
        raise HTTPException(400, "month must be YYYY-MM") from exc
    with db() as conn:
        payment = conn.execute(
            "SELECT * FROM recurring_bill_payments WHERE bill_id = ? AND month = ?",
            (bill_id, month_key),
        ).fetchone()
        if not payment:
            raise HTTPException(404, "bill payment not found")
        before = compute_stats(conn)
        if payment["transaction_id"]:
            conn.execute("DELETE FROM transactions WHERE id = ?", (payment["transaction_id"],))
        conn.execute("DELETE FROM recurring_bill_payments WHERE id = ?", (payment["id"],))
        after = compute_stats(conn)
        return {
            "deleted_payment": payment["id"],
            "stats": after,
            "accounts": get_accounts(conn),
            "monthly": compute_monthly(conn),
            "planning": get_planning(conn),
            "calendar": get_financial_calendar(conn, month_key),
            "lit_before": before["lit_count"],
            "lit_after": after["lit_count"],
        }


@router.post("/api/planning/settings")
def set_planning_settings(body: PlanningSettingsIn):
    with db() as conn:
        conn.execute(
            """INSERT INTO planning_settings
               (id, monthly_allowance_amount, allowance_day, monthly_spending_budget, updated_at)
               VALUES (1, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 monthly_allowance_amount = excluded.monthly_allowance_amount,
                 allowance_day = excluded.allowance_day,
                 monthly_spending_budget = excluded.monthly_spending_budget,
                 updated_at = excluded.updated_at""",
            (body.monthly_allowance_amount, body.allowance_day,
             body.monthly_spending_budget, datetime.now().isoformat()),
        )
        return get_planning(conn)


@router.post("/api/planning/semester")
def set_semester_settings(body: SemesterSettingsIn):
    try:
        start = date.fromisoformat(body.start_date)
        end = date.fromisoformat(body.end_date)
    except ValueError as exc:
        raise HTTPException(400, "semester dates must be YYYY-MM-DD") from exc
    if end < start:
        raise HTTPException(400, "semester end date must not be before start date")
    if (end - start).days > 730:
        raise HTTPException(400, "semester period is too long")
    with db() as conn:
        conn.execute(
            """INSERT INTO semester_settings
               (id, start_date, end_date, total_budget, mode, updated_at)
               VALUES (1, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 start_date = excluded.start_date,
                 end_date = excluded.end_date,
                 total_budget = excluded.total_budget,
                 mode = excluded.mode,
                 updated_at = excluded.updated_at""",
            (start.isoformat(), end.isoformat(), body.total_budget,
             body.mode, datetime.now().isoformat()),
        )
        return {"planning": get_planning(conn), "today": get_today_overview(conn)}


@router.post("/api/budgets/categories")
def set_category_budgets(body: CategoryBudgetsIn):
    unknown = set(body.budgets) - set(EXPENSE_CATEGORIES)
    if unknown:
        raise HTTPException(400, f"invalid budget categories: {', '.join(sorted(unknown))}")
    if any(float(amount) < 0 for amount in body.budgets.values()):
        raise HTTPException(400, "budget amount must be non-negative")
    with db() as conn:
        now = datetime.now().isoformat()
        for category in EXPENSE_CATEGORIES:
            amount = round(float(body.budgets.get(category, 0) or 0), 2)
            if amount <= 0:
                conn.execute("DELETE FROM category_budgets WHERE category = ?", (category,))
            else:
                conn.execute(
                    """INSERT INTO category_budgets (category, amount, updated_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(category) DO UPDATE SET
                         amount = excluded.amount, updated_at = excluded.updated_at""",
                    (category, amount, now),
                )
        return get_planning(conn)


@router.post("/api/goals")
def add_savings_goal(body: SavingsGoalIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "goal name is required")
    target_date = body.target_date or None
    if target_date:
        date.fromisoformat(target_date)
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO savings_goals
               (name, target_amount, saved_amount, target_date, is_active, created_at)
               VALUES (?, ?, ?, ?, 1, ?)""",
            (name, body.target_amount, body.saved_amount, target_date,
             datetime.now().isoformat()),
        )
        planning = get_planning(conn)
        return {
            "goal": next(goal for goal in planning["goals"] if goal["id"] == cur.lastrowid),
            **planning,
        }


@router.post("/api/goals/{goal_id}/progress")
def update_savings_goal_progress(goal_id: int, body: SavingsGoalProgressIn):
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM savings_goals WHERE id = ? AND is_active = 1", (goal_id,)
        ).fetchone():
            raise HTTPException(404, "goal not found")
        conn.execute(
            "UPDATE savings_goals SET saved_amount = ? WHERE id = ?",
            (body.saved_amount, goal_id),
        )
        return get_planning(conn)


@router.delete("/api/goals/{goal_id}")
def delete_savings_goal(goal_id: int):
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM savings_goals WHERE id = ? AND is_active = 1", (goal_id,)
        ).fetchone():
            raise HTTPException(404, "goal not found")
        conn.execute("UPDATE savings_goals SET is_active = 0 WHERE id = ?", (goal_id,))
        return get_planning(conn)


@router.post("/api/import/transactions")
def import_transactions(body: ImportBatchIn):
    with db() as conn:
        accounts = {account["id"]: account for account in get_accounts(conn)}
        if not accounts:
            raise HTTPException(400, "no active account")
        default_account_id = next(iter(accounts))
        normalized = []
        for index, row in enumerate(body.rows, start=1):
            try:
                date.fromisoformat(row.occurred_on)
            except ValueError as exc:
                raise HTTPException(400, f"invalid date at row {index}") from exc
            account_id = row.account_id or default_account_id
            if account_id not in accounts:
                raise HTTPException(400, f"invalid account at row {index}")
            source = (row.source or "family_support") if row.type == "income" else "expense"
            category = "income" if row.type == "income" else (row.category or "other")
            normalized.append({
                "occurred_on": row.occurred_on,
                "type": row.type,
                "source": source,
                "category": category,
                "account_id": account_id,
                "amount": round(float(row.amount), 2),
                "note": row.note.strip(),
            })

        canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if conn.execute(
            "SELECT 1 FROM import_batches WHERE content_hash = ?", (content_hash,)
        ).fetchone():
            raise HTTPException(409, "this statement content has already been imported")

        before = compute_stats(conn)
        cur = conn.execute(
            """INSERT INTO import_batches (filename, content_hash, row_count, created_at)
               VALUES (?, ?, ?, ?)""",
            (body.filename.strip() or "statement.csv", content_hash,
             len(normalized), datetime.now().isoformat()),
        )
        batch_id = cur.lastrowid
        for row_number, row in enumerate(normalized, start=1):
            conn.execute(
                """INSERT INTO transactions
                   (occurred_on, type, source, category, account_id, amount, note,
                    created_at, import_batch_id, import_row_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (row["occurred_on"], row["type"], row["source"], row["category"],
                 row["account_id"], row["amount"], row["note"],
                 datetime.now().isoformat(), batch_id, row_number),
            )
        after = compute_stats(conn)
        return {
            "batch": {
                "id": batch_id,
                "filename": body.filename.strip() or "statement.csv",
                "row_count": len(normalized),
            },
            "imported_count": len(normalized),
            "stats": after,
            "accounts": get_accounts(conn),
            "monthly": compute_monthly(conn),
            "planning": get_planning(conn),
            "calendar": get_financial_calendar(conn),
            "lit_before": before["lit_count"],
            "lit_after": after["lit_count"],
        }


@router.get("/api/import/batches")
def list_import_batches(limit: int = 20):
    with db() as conn:
        return {"batches": get_import_batches(conn, min(max(limit, 1), 100))}


@router.delete("/api/import/batches/{batch_id}")
def delete_import_batch(batch_id: int):
    with db() as conn:
        batch = conn.execute(
            "SELECT * FROM import_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if not batch:
            raise HTTPException(404, "import batch not found")
        before = compute_stats(conn)
        deleted_rows = conn.execute(
            "SELECT COUNT(*) AS count FROM transactions WHERE import_batch_id = ?",
            (batch_id,),
        ).fetchone()["count"]
        conn.execute("DELETE FROM transactions WHERE import_batch_id = ?", (batch_id,))
        conn.execute("DELETE FROM import_batches WHERE id = ?", (batch_id,))
        after = compute_stats(conn)
        return {
            "deleted_batch": batch_id,
            "deleted_transactions": deleted_rows,
            "stats": after,
            "accounts": get_accounts(conn),
            "monthly": compute_monthly(conn),
            "planning": get_planning(conn),
            "import_batches": get_import_batches(conn),
            "calendar": get_financial_calendar(conn),
            "lit_before": before["lit_count"],
            "lit_after": after["lit_count"],
        }


@router.get("/api/accounts")
def list_accounts():
    with db() as conn:
        return {"accounts": get_accounts(conn)}


@router.post("/api/accounts")
def add_account(body: AccountIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "account name is required")
    with db() as conn:
        if conn.execute(
            "SELECT 1 FROM accounts WHERE is_active = 1 AND lower(name) = lower(?)",
            (name,),
        ).fetchone():
            raise HTTPException(409, "account name already exists")
        cur = conn.execute(
            """INSERT INTO accounts (name, type, opening_balance, is_active, created_at)
               VALUES (?, ?, ?, 1, ?)""",
            (name, body.type, body.opening_balance, datetime.now().isoformat()),
        )
        account_id = cur.lastrowid
        account = next(item for item in get_accounts(conn) if item["id"] == account_id)
        return {"account": account, "accounts": get_accounts(conn), "stats": compute_stats(conn),
                "planning": get_planning(conn)}


@router.get("/api/transfers")
def list_transfers(limit: int = 50):
    with db() as conn:
        return {"transfers": get_recent_transfers(conn, min(max(limit, 1), 200))}


@router.post("/api/transfers")
def add_transfer(body: TransferIn):
    if body.from_account_id == body.to_account_id:
        raise HTTPException(400, "source and destination accounts must differ")
    when = body.occurred_on or date.today().isoformat()
    date.fromisoformat(when)
    with db() as conn:
        accounts = {account["id"]: account for account in get_accounts(conn)}
        source = accounts.get(body.from_account_id)
        destination = accounts.get(body.to_account_id)
        if not source or not destination:
            raise HTTPException(400, "invalid account")
        if float(source["balance"]) + 0.005 < body.amount:
            raise HTTPException(400, "insufficient account balance")
        cur = conn.execute(
            """INSERT INTO account_transfers
               (from_account_id, to_account_id, amount, occurred_on, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (body.from_account_id, body.to_account_id, body.amount, when,
             body.note.strip(), datetime.now().isoformat()),
        )
        transfer = dict(conn.execute(
            """SELECT tr.*, source.name AS from_account_name, destination.name AS to_account_name
               FROM account_transfers tr
               JOIN accounts source ON source.id = tr.from_account_id
               JOIN accounts destination ON destination.id = tr.to_account_id
               WHERE tr.id = ?""",
            (cur.lastrowid,),
        ).fetchone())
        return {
            "transfer": transfer,
            "accounts": get_accounts(conn),
            "stats": compute_stats(conn),
            "monthly": compute_monthly(conn),
            "transfers": get_recent_transfers(conn),
            "planning": get_planning(conn),
        }


@router.delete("/api/transfers/{transfer_id}")
def delete_transfer(transfer_id: int):
    with db() as conn:
        if not conn.execute(
            "SELECT 1 FROM account_transfers WHERE id = ?", (transfer_id,)
        ).fetchone():
            raise HTTPException(404, "transfer not found")
        conn.execute("DELETE FROM account_transfers WHERE id = ?", (transfer_id,))
        return {
            "deleted": transfer_id,
            "accounts": get_accounts(conn),
            "stats": compute_stats(conn),
            "monthly": compute_monthly(conn),
            "transfers": get_recent_transfers(conn),
            "planning": get_planning(conn),
        }


@router.post("/api/accounts/{account_id}/reconcile")
def reconcile_account(account_id: int, body: ReconcileIn):
    when = body.occurred_on or date.today().isoformat()
    date.fromisoformat(when)
    with db() as conn:
        accounts = {account["id"]: account for account in get_accounts(conn)}
        account = accounts.get(account_id)
        if not account:
            raise HTTPException(404, "account not found")
        delta = round(body.actual_balance - float(account["balance"]), 2)
        adjustment = None
        if abs(delta) >= 0.005:
            cur = conn.execute(
                """INSERT INTO account_adjustments
                   (account_id, delta, actual_balance, occurred_on, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (account_id, delta, body.actual_balance, when,
                 body.note.strip(), datetime.now().isoformat()),
            )
            adjustment = dict(conn.execute(
                "SELECT * FROM account_adjustments WHERE id = ?", (cur.lastrowid,)
            ).fetchone())
        return {
            "adjustment": adjustment,
            "accounts": get_accounts(conn),
            "stats": compute_stats(conn),
            "monthly": compute_monthly(conn),
            "transfers": get_recent_transfers(conn),
            "planning": get_planning(conn),
        }


@router.post("/api/transactions")
def add_transaction(body: TransactionIn):
    with db() as conn:
        before = compute_stats(conn)
        tx = create_transaction(
            conn,
            occurred_on=body.occurred_on,
            type=body.type,
            amount=body.amount,
            source=body.source,
            category=body.category,
            account_id=body.account_id,
            note=body.note,
        )
        after = compute_stats(conn)
        delta = after["lit_count"] - before["lit_count"]
        animation = "light_up" if delta > 0 else ("extinguish" if delta < 0 else "none")
        return {
            "transaction": tx,
            "stats": after,
            "accounts": get_accounts(conn),
            "monthly": compute_monthly(conn),
            "planning": get_planning(conn),
            "calendar": get_financial_calendar(conn),
            "today": get_today_overview(conn),
            "lit_before": before["lit_count"],
            "lit_after": after["lit_count"],
            "delta": delta,
            "animation": animation,
        }


@router.delete("/api/transactions/{tx_id}")
def delete_transaction(tx_id: int):
    with db() as conn:
        if not conn.execute("SELECT 1 FROM transactions WHERE id = ?", (tx_id,)).fetchone():
            raise HTTPException(404, "transaction not found")
        before = compute_stats(conn)
        conn.execute("DELETE FROM recurring_bill_payments WHERE transaction_id = ?", (tx_id,))
        conn.execute("DELETE FROM transactions WHERE id = ?", (tx_id,))
        after = compute_stats(conn)
        delta = after["lit_count"] - before["lit_count"]
        animation = "light_up" if delta > 0 else ("extinguish" if delta < 0 else "none")
        return {
            "deleted": tx_id,
            "stats": after,
            "accounts": get_accounts(conn),
            "monthly": compute_monthly(conn),
            "planning": get_planning(conn),
            "calendar": get_financial_calendar(conn),
            "today": get_today_overview(conn),
            "lit_before": before["lit_count"],
            "lit_after": after["lit_count"],
            "delta": delta,
            "animation": animation,
        }


@router.get("/api/transactions")
def list_transactions(limit: int = 200, offset: int = 0):
    with db() as conn:
        rows = conn.execute(
            """SELECT t.*, a.name AS account_name FROM transactions t
               LEFT JOIN accounts a ON a.id = t.account_id
               ORDER BY t.occurred_on DESC, t.id DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()
        return {"transactions": [dict(r) for r in rows]}
