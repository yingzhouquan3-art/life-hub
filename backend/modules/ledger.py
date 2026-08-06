"""个人账本模块。

账户、交易、预算、账单、学期与财务报告。
家庭支持永远不计入自主收入；规划中的预计生活费不会自动成为收入。
"""
from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from math import floor
from typing import Optional

from fastapi import HTTPException

from backend.core.config import EXPENSE_CATEGORIES
from backend.core.dates import month_start, shift_month
from backend.core.registry import LifeModule


def get_accounts(conn, active_only: bool = True) -> list[dict]:
    where = "WHERE a.is_active = 1" if active_only else ""
    rows = conn.execute(
        f"""WITH tx AS (
               SELECT account_id,
                      SUM(CASE WHEN type = 'income' THEN amount ELSE -amount END) AS net,
                      COUNT(*) AS count
               FROM transactions GROUP BY account_id
             ), transfer_out AS (
               SELECT from_account_id AS account_id, SUM(amount) AS total, COUNT(*) AS count
               FROM account_transfers GROUP BY from_account_id
             ), transfer_in AS (
               SELECT to_account_id AS account_id, SUM(amount) AS total, COUNT(*) AS count
               FROM account_transfers GROUP BY to_account_id
             ), adjustments AS (
               SELECT account_id, SUM(delta) AS total, COUNT(*) AS count
               FROM account_adjustments GROUP BY account_id
             )
            SELECT a.*,
                   a.opening_balance
                     + COALESCE(tx.net, 0)
                     + COALESCE(transfer_in.total, 0)
                     - COALESCE(transfer_out.total, 0)
                     + COALESCE(adjustments.total, 0) AS balance,
                   COALESCE(tx.count, 0) AS transaction_count,
                   COALESCE(transfer_in.count, 0) + COALESCE(transfer_out.count, 0) AS transfer_count,
                   COALESCE(adjustments.count, 0) AS adjustment_count,
                   COALESCE(tx.count, 0) + COALESCE(transfer_in.count, 0)
                     + COALESCE(transfer_out.count, 0) + COALESCE(adjustments.count, 0) AS activity_count
            FROM accounts a
            LEFT JOIN tx ON tx.account_id = a.id
            LEFT JOIN transfer_out ON transfer_out.account_id = a.id
            LEFT JOIN transfer_in ON transfer_in.account_id = a.id
            LEFT JOIN adjustments ON adjustments.account_id = a.id
            {where}
            ORDER BY a.is_active DESC, a.id"""
    ).fetchall()
    return [
        {
            **dict(row),
            "opening_balance": round(float(row["opening_balance"] or 0), 2),
            "balance": round(float(row["balance"] or 0), 2),
            "is_active": bool(row["is_active"]),
        }
        for row in rows
    ]


def get_recent_transfers(conn, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """SELECT tr.*, source.name AS from_account_name, destination.name AS to_account_name
           FROM account_transfers tr
           JOIN accounts source ON source.id = tr.from_account_id
           JOIN accounts destination ON destination.id = tr.to_account_id
           ORDER BY tr.occurred_on DESC, tr.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_import_batches(conn, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        """SELECT b.*, COUNT(t.id) AS remaining_rows
           FROM import_batches b
           LEFT JOIN transactions t ON t.import_batch_id = b.id
           GROUP BY b.id
           ORDER BY b.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def compute_monthly(conn, target_month: Optional[str] = None) -> dict:
    if target_month:
        try:
            start = date.fromisoformat(f"{target_month}-01")
        except ValueError as exc:
            raise HTTPException(400, "month must be YYYY-MM") from exc
    else:
        start = month_start(date.today())
    end = shift_month(start, 1)
    params = (start.isoformat(), end.isoformat())

    totals = {"income": 0.0, "expense": 0.0}
    for row in conn.execute(
        """SELECT type, SUM(amount) AS total FROM transactions
           WHERE occurred_on >= ? AND occurred_on < ? GROUP BY type""",
        params,
    ).fetchall():
        totals[row["type"]] = float(row["total"] or 0)

    sources = {
        "family_support": 0.0,
        "scholarship": 0.0,
        "part_time": 0.0,
        "project": 0.0,
        "investment": 0.0,
        "other": 0.0,
    }
    for row in conn.execute(
        """SELECT source, SUM(amount) AS total FROM transactions
           WHERE type = 'income' AND occurred_on >= ? AND occurred_on < ?
           GROUP BY source""",
        params,
    ).fetchall():
        source = row["source"] if row["source"] in sources else "family_support"
        sources[source] += float(row["total"] or 0)

    categories = {
        "food": 0.0,
        "transport": 0.0,
        "study": 0.0,
        "housing": 0.0,
        "medical": 0.0,
        "entertainment": 0.0,
        "social": 0.0,
        "digital": 0.0,
        "other": 0.0,
    }
    for row in conn.execute(
        """SELECT category, SUM(amount) AS total FROM transactions
           WHERE type = 'expense' AND occurred_on >= ? AND occurred_on < ?
           GROUP BY category""",
        params,
    ).fetchall():
        category = row["category"] if row["category"] in categories else "other"
        categories[category] += float(row["total"] or 0)

    independent = sum(value for key, value in sources.items() if key != "family_support")
    autonomy_rate = round(independent / totals["expense"] * 100, 1) if totals["expense"] else None

    trend = []
    for offset in range(-5, 1):
        trend_start = shift_month(start, offset)
        trend_end = shift_month(trend_start, 1)
        row = conn.execute(
            """SELECT
                 COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0) AS expense,
                 COALESCE(SUM(CASE WHEN type = 'income' AND source != 'family_support' THEN amount ELSE 0 END), 0) AS independent
               FROM transactions WHERE occurred_on >= ? AND occurred_on < ?""",
            (trend_start.isoformat(), trend_end.isoformat()),
        ).fetchone()
        trend.append({
            "month": trend_start.strftime("%Y-%m"),
            "expense": round(float(row["expense"] or 0), 2),
            "independent": round(float(row["independent"] or 0), 2),
        })

    return {
        "month": start.strftime("%Y-%m"),
        "total_income": round(totals["income"], 2),
        "total_expense": round(totals["expense"], 2),
        "family_support": round(sources["family_support"], 2),
        "independent_income": round(independent, 2),
        "net_cashflow": round(totals["income"] - totals["expense"], 2),
        "autonomy_coverage_rate": autonomy_rate,
        "income_sources": {key: round(value, 2) for key, value in sources.items()},
        "expense_categories": {key: round(value, 2) for key, value in categories.items()},
        "trend": trend,
    }


def compute_stats(conn) -> dict:
    rows = conn.execute(
        "SELECT type, SUM(amount) AS total FROM transactions GROUP BY type"
    ).fetchall()
    totals = {"income": 0.0, "expense": 0.0}
    for r in rows:
        totals[r["type"]] = float(r["total"] or 0)

    source_rows = conn.execute(
        """SELECT source, SUM(amount) AS total
           FROM transactions WHERE type = 'income' GROUP BY source"""
    ).fetchall()
    income_sources = {
        "family_support": 0.0,
        "scholarship": 0.0,
        "part_time": 0.0,
        "project": 0.0,
        "investment": 0.0,
        "other": 0.0,
    }
    for r in source_rows:
        source = r["source"] if r["source"] in income_sources else "family_support"
        income_sources[source] += float(r["total"] or 0)

    family_support_income = income_sources["family_support"]
    independent_income = sum(
        amount for source, amount in income_sources.items() if source != "family_support"
    )

    extrema = conn.execute(
        "SELECT MIN(occurred_on) AS first, MAX(occurred_on) AS last FROM transactions"
    ).fetchone()
    first_str = extrema["first"]
    last_str = extrema["last"]

    today = date.today()
    first_record = date.fromisoformat(first_str) if first_str else None
    last_record = date.fromisoformat(last_str) if last_str else None
    if first_record and last_record:
        # 记账天数：从第一笔到最后一笔（含未来记账日），全跨度
        tracking_days = max((last_record - first_record).days + 1, 1)
    else:
        tracking_days = 0

    s = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    keys = set(s.keys()) if s else set()
    accounts = get_accounts(conn)
    opening_assets = sum(float(account["opening_balance"]) for account in accounts)
    adjustment_total = float(conn.execute(
        "SELECT COALESCE(SUM(delta), 0) AS total FROM account_adjustments"
    ).fetchone()["total"] or 0)
    show_past = bool(s["show_past"]) if s and "show_past" in keys else False

    # 手动覆盖（> 0 即生效，0 = 用派生值）
    td_override = int(s["tracking_days_override"]) if s and "tracking_days_override" in keys else 0
    avg_override = float(s["avg_daily_expense_override"]) if s and "avg_daily_expense_override" in keys else 0.0
    if td_override > 0:
        tracking_days = td_override
    derived_avg = (
        totals["expense"] / tracking_days
        if tracking_days > 0 and totals["expense"] > 0
        else 0.0
    )
    avg = avg_override if avg_override > 0 else derived_avg

    # 双口径：蓝色表示家庭支持/起始存款形成的余额，金色表示自主所得留存。
    # 已发生支出优先消耗支持资金；只有超出支持资金的部分才消耗自主所得。
    starting_assets = opening_assets + adjustment_total
    support_pool = starting_assets + family_support_income
    support_balance = max(support_pool - totals["expense"], 0.0)
    expenses_beyond_support = max(totals["expense"] - support_pool, 0.0)
    independent_balance = max(independent_income - expenses_beyond_support, 0.0)
    current_balance = sum(float(account["balance"]) for account in accounts)
    net_savings = totals["income"] - totals["expense"]

    runway_days = floor(current_balance / avg) if avg > 0 and current_balance > 0 else 0
    support_freedom = min(
        floor(support_balance / avg) if avg > 0 and support_balance > 0 else 0,
        runway_days,
    )
    independent_freedom = max(runway_days - support_freedom, 0)
    independent_coverage_days = (
        floor(independent_income / avg) if avg > 0 and independent_income > 0 else 0
    )
    autonomy_coverage_rate = (
        round(independent_income / totals["expense"] * 100, 1)
        if totals["expense"] > 0
        else None
    )

    # 兼容 Canvas 既有字段：asset 段现在代表支持资金，income 段代表自主所得。
    asset_freedom = support_freedom
    income_freedom = independent_freedom
    freedom_days_bought = runway_days

    future_cells = 0
    past_cells = 0
    if s:
        birth = date.fromisoformat(s["birth_date"])
        try:
            end = birth.replace(year=birth.year + s["target_age"])
        except ValueError:
            end = birth.replace(year=birth.year + s["target_age"], day=28)
        future_cells = max((end - today).days, 0)
        past_cells = max((today - birth).days, 0)

    total_cells = (past_cells + future_cells) if show_past else future_cells

    asset_lit = min(asset_freedom, future_cells) if future_cells > 0 else asset_freedom
    income_lit = min(income_freedom, max(0, future_cells - asset_lit)) if future_cells > 0 else income_freedom
    lit = asset_lit + income_lit
    overflow = max(freedom_days_bought - future_cells, 0) if future_cells > 0 else 0

    # tracked_past_cells = past 区间中从今天倒推到第一笔记账日的格数
    if first_record and first_record < today and show_past:
        tracked_past_cells = min(past_cells, (today - first_record).days)
    else:
        tracked_past_cells = 0

    return {
        "total_income": round(totals["income"], 2),
        "total_expense": round(totals["expense"], 2),
        "family_support_income": round(family_support_income, 2),
        "independent_income": round(independent_income, 2),
        "income_sources": {k: round(v, 2) for k, v in income_sources.items()},
        "support_balance": round(support_balance, 2),
        "independent_balance": round(independent_balance, 2),
        "current_balance": round(current_balance, 2),
        "net_savings": round(net_savings, 2),
        "runway_days": runway_days,
        "independent_coverage_days": independent_coverage_days,
        "autonomy_coverage_rate": autonomy_coverage_rate,
        "tracking_days": tracking_days,
        "avg_daily_expense": round(avg, 4),
        "freedom_days_bought": freedom_days_bought,
        "asset_freedom": asset_freedom,
        "income_freedom": income_freedom,
        "asset_lit": asset_lit,
        "income_lit": income_lit,
        "lit_count": lit,
        "total_cells": total_cells,
        "future_cells": future_cells,
        "past_cells": past_cells if show_past else 0,
        "tracked_past_cells": tracked_past_cells,
        "show_past": show_past,
        "use_initial_assets": opening_assets > 0,
        "initial_assets": round(opening_assets, 2),
        "account_adjustments": round(adjustment_total, 2),
        "overflow": overflow,
        "first_record": first_str,
        "last_record": last_str,
    }


def get_settings(conn) -> Optional[dict]:
    s = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    return dict(s) if s else None


def get_semester(conn) -> dict:
    row = conn.execute("SELECT * FROM semester_settings WHERE id = 1").fetchone()
    semester = dict(row) if row else {
        "id": 1,
        "start_date": None,
        "end_date": None,
        "total_budget": 0.0,
        "mode": "in_school",
        "updated_at": None,
    }
    semester["total_budget"] = round(float(semester["total_budget"] or 0), 2)
    semester["mode"] = semester.get("mode") or "in_school"
    semester.update({
        "configured": False,
        "status": "unset",
        "actual_expense": 0.0,
        "remaining_budget": None,
        "usage_rate": None,
        "elapsed_rate": None,
        "total_days": 0,
        "elapsed_days": 0,
        "remaining_days": 0,
        "recommended_daily_budget": None,
        "pace_status": "unset",
    })
    if not semester.get("start_date") or not semester.get("end_date") or semester["total_budget"] <= 0:
        return semester

    try:
        start = date.fromisoformat(semester["start_date"])
        end = date.fromisoformat(semester["end_date"])
    except ValueError:
        return semester
    if end < start:
        return semester

    today = date.today()
    total_days = (end - start).days + 1
    if today < start:
        status = "upcoming"
        elapsed_days = 0
        remaining_days = total_days
    elif today > end:
        status = "completed"
        elapsed_days = total_days
        remaining_days = 0
    else:
        status = "active"
        elapsed_days = (today - start).days + 1
        remaining_days = (end - today).days + 1
    actual = float(conn.execute(
        """SELECT COALESCE(SUM(amount), 0) FROM transactions
           WHERE type = 'expense' AND occurred_on BETWEEN ? AND ?""",
        (start.isoformat(), min(today, end).isoformat()),
    ).fetchone()[0] or 0)
    remaining = semester["total_budget"] - actual
    usage_rate = actual / semester["total_budget"] * 100
    elapsed_rate = elapsed_days / total_days * 100
    if remaining < 0:
        pace_status = "over"
    elif status == "active" and usage_rate > elapsed_rate + 10:
        pace_status = "warning"
    else:
        pace_status = "safe"
    semester.update({
        "configured": True,
        "status": status,
        "actual_expense": round(actual, 2),
        "remaining_budget": round(remaining, 2),
        "usage_rate": round(usage_rate, 1),
        "elapsed_rate": round(elapsed_rate, 1),
        "total_days": total_days,
        "elapsed_days": elapsed_days,
        "remaining_days": remaining_days,
        "recommended_daily_budget": round(max(remaining, 0) / remaining_days, 2) if remaining_days > 0 else 0.0,
        "pace_status": pace_status,
    })
    return semester


def get_planning(conn) -> dict:
    row = conn.execute("SELECT * FROM planning_settings WHERE id = 1").fetchone()
    settings = dict(row) if row else {
        "id": 1,
        "monthly_allowance_amount": 0.0,
        "allowance_day": 1,
        "monthly_spending_budget": 0.0,
        "updated_at": None,
    }
    settings["monthly_allowance_amount"] = round(float(settings["monthly_allowance_amount"] or 0), 2)
    settings["monthly_spending_budget"] = round(float(settings["monthly_spending_budget"] or 0), 2)
    settings["allowance_day"] = int(settings["allowance_day"] or 1)

    goals = [dict(goal) for goal in conn.execute(
        """SELECT * FROM savings_goals WHERE is_active = 1
           ORDER BY CASE WHEN target_date IS NULL OR target_date = '' THEN 1 ELSE 0 END,
                    target_date, id"""
    ).fetchall()]
    for goal in goals:
        goal["target_amount"] = round(float(goal["target_amount"] or 0), 2)
        goal["saved_amount"] = round(float(goal["saved_amount"] or 0), 2)
        goal["progress_rate"] = round(
            goal["saved_amount"] / goal["target_amount"] * 100, 1
        ) if goal["target_amount"] > 0 else 0.0
        goal["is_active"] = bool(goal["is_active"])

    today = date.today()
    days_in_month = monthrange(today.year, today.month)[1]
    remaining_days = max(days_in_month - today.day, 0)
    monthly = compute_monthly(conn)
    stats = compute_stats(conn)
    saved_budgets = {
        row["category"]: round(float(row["amount"] or 0), 2)
        for row in conn.execute("SELECT category, amount FROM category_budgets").fetchall()
    }
    category_budget_status = []
    for category in EXPENSE_CATEGORIES:
        budget_amount = saved_budgets.get(category, 0.0)
        actual_amount = round(float(monthly["expense_categories"].get(category, 0) or 0), 2)
        usage_rate = round(actual_amount / budget_amount * 100, 1) if budget_amount > 0 else None
        status = (
            "unset" if budget_amount <= 0 else
            "over" if actual_amount > budget_amount else
            "warning" if actual_amount >= budget_amount * 0.8 else
            "safe"
        )
        category_budget_status.append({
            "category": category,
            "budget": budget_amount,
            "actual": actual_amount,
            "remaining": round(budget_amount - actual_amount, 2) if budget_amount > 0 else None,
            "usage_rate": usage_rate,
            "status": status,
        })
    budget = settings["monthly_spending_budget"]
    if budget > 0:
        daily_rate = budget / days_in_month
        basis = "monthly_budget"
    elif float(monthly["total_expense"] or 0) > 0:
        daily_rate = float(monthly["total_expense"]) / max(today.day, 1)
        basis = "current_month_pace"
    elif float(stats["avg_daily_expense"] or 0) > 0:
        daily_rate = float(stats["avg_daily_expense"])
        basis = "ledger_average"
    else:
        daily_rate = 0.0
        basis = "no_sample"

    allowance_day = settings["allowance_day"]
    this_occurrence = date(today.year, today.month, min(allowance_day, days_in_month))
    if this_occurrence > today:
        next_allowance = this_occurrence
    else:
        next_month = shift_month(month_start(today), 1)
        next_allowance = date(
            next_month.year,
            next_month.month,
            min(allowance_day, monthrange(next_month.year, next_month.month)[1]),
        )
    days_until_allowance = max((next_allowance - today).days, 0)
    expected_before_month_end = (
        settings["monthly_allowance_amount"]
        if next_allowance.year == today.year and next_allowance.month == today.month
        else 0.0
    )
    current_balance = float(stats["current_balance"] or 0)
    projected_remaining_expense = daily_rate * remaining_days
    projected_month_end = current_balance - projected_remaining_expense + expected_before_month_end
    projected_before_allowance = current_balance - daily_rate * days_until_allowance
    allocated = sum(float(goal["saved_amount"] or 0) for goal in goals)

    return {
        "settings": settings,
        "semester": get_semester(conn),
        "goals": goals,
        "budget_status": {
            "month": monthly["month"],
            "total_budget": budget,
            "total_actual": round(float(monthly["total_expense"] or 0), 2),
            "total_remaining": round(budget - float(monthly["total_expense"] or 0), 2) if budget > 0 else None,
            "total_usage_rate": round(float(monthly["total_expense"] or 0) / budget * 100, 1) if budget > 0 else None,
            "total_status": (
                "unset" if budget <= 0 else
                "over" if float(monthly["total_expense"] or 0) > budget else
                "warning" if float(monthly["total_expense"] or 0) >= budget * 0.8 else
                "safe"
            ),
            "categories": category_budget_status,
        },
        "forecast": {
            "as_of": today.isoformat(),
            "days_in_month": days_in_month,
            "remaining_days": remaining_days,
            "spending_basis": basis,
            "daily_spending_rate": round(daily_rate, 2),
            "projected_remaining_expense": round(projected_remaining_expense, 2),
            "expected_allowance_before_month_end": round(expected_before_month_end, 2),
            "projected_month_end_balance": round(projected_month_end, 2),
            "next_allowance_date": next_allowance.isoformat(),
            "days_until_next_allowance": days_until_allowance,
            "projected_balance_before_allowance": round(projected_before_allowance, 2),
            "allocated_to_goals": round(allocated, 2),
            "unallocated_balance": round(current_balance - allocated, 2),
        },
    }


def get_financial_calendar(conn, target_month: Optional[str] = None) -> dict:
    if target_month:
        try:
            start = date.fromisoformat(f"{target_month}-01")
        except ValueError as exc:
            raise HTTPException(400, "month must be YYYY-MM") from exc
    else:
        start = month_start(date.today())
    month_key = start.strftime("%Y-%m")
    days_in_month = monthrange(start.year, start.month)[1]
    today = date.today()
    rows = conn.execute(
        """SELECT b.*, a.name AS account_name,
                  p.id AS payment_id, p.transaction_id, p.paid_on,
                  t.id AS transaction_exists
           FROM recurring_bills b
           JOIN accounts a ON a.id = b.account_id
           LEFT JOIN recurring_bill_payments p
             ON p.bill_id = b.id AND p.month = ?
           LEFT JOIN transactions t ON t.id = p.transaction_id
           WHERE b.is_active = 1
           ORDER BY b.day_of_month, b.id""",
        (month_key,),
    ).fetchall()
    bills = []
    for row in rows:
        item = dict(row)
        # 季付与年付只在到期的那个月出现，否则日历会月月提醒一笔并不会扣的钱
        if not bill_due_in_month(item, start.year, start.month):
            continue
        due_date = date(start.year, start.month, min(int(item["day_of_month"]), days_in_month))
        is_paid = bool(item["payment_id"] and item["transaction_exists"])
        days_until = (due_date - today).days if start.year == today.year and start.month == today.month else None
        if is_paid:
            status = "paid"
        elif days_until is not None and days_until < 0:
            status = "overdue"
        elif days_until is not None and days_until <= 3:
            status = "due_soon"
        else:
            status = "upcoming"
        item.update({
            "amount": round(float(item["amount"] or 0), 2),
            "is_active": bool(item["is_active"]),
            "due_date": due_date.isoformat(),
            "days_until_due": days_until,
            "is_paid": is_paid,
            "status": status,
        })
        bills.append(item)

    monthly = compute_monthly(conn, month_key)
    previous_month = shift_month(start, -1).strftime("%Y-%m")
    previous = compute_monthly(conn, previous_month)
    top_category = max(
        monthly["expense_categories"].items(), key=lambda item: item[1]
    ) if monthly["expense_categories"] else ("other", 0.0)
    if float(top_category[1] or 0) <= 0:
        top_category = (None, 0.0)
    income = float(monthly["total_income"] or 0)
    expense = float(monthly["total_expense"] or 0)
    net = income - expense
    expense_change_rate = (
        round((expense - float(previous["total_expense"])) / float(previous["total_expense"]) * 100, 1)
        if float(previous["total_expense"] or 0) > 0 else None
    )
    transaction_count = conn.execute(
        "SELECT COUNT(*) AS count FROM transactions WHERE occurred_on >= ? AND occurred_on < ?",
        (start.isoformat(), shift_month(start, 1).isoformat()),
    ).fetchone()["count"]
    observations = []
    if transaction_count == 0:
        observations.append("本月尚无交易记录，先从真实支出开始积累复盘样本。")
    else:
        if expense > 0 and top_category[0]:
            observations.append(f"本月最大支出分类占比 {round(float(top_category[1]) / expense * 100, 1)}%。")
        if net < 0:
            observations.append("本月现金流为负，支出高于已记录收入。")
        elif net > 0:
            observations.append("本月现金流为正，仍可结合未到期固定账单判断可用余额。")
        if expense_change_rate is not None:
            direction = "增加" if expense_change_rate > 0 else "减少"
            observations.append(f"本月支出较上月{direction} {abs(expense_change_rate)}%。")

    scheduled = sum(float(item["amount"]) for item in bills)
    paid = sum(float(item["amount"]) for item in bills if item["is_paid"])
    return {
        "month": month_key,
        "days_in_month": days_in_month,
        "first_weekday": start.weekday(),
        "bills": bills,
        "summary": {
            "scheduled_amount": round(scheduled, 2),
            "paid_amount": round(paid, 2),
            "unpaid_amount": round(scheduled - paid, 2),
            "paid_count": sum(1 for item in bills if item["is_paid"]),
            "unpaid_count": sum(1 for item in bills if not item["is_paid"]),
            "overdue_count": sum(1 for item in bills if item["status"] == "overdue"),
            "due_soon_count": sum(1 for item in bills if item["status"] == "due_soon"),
        },
        "review": {
            "transaction_count": transaction_count,
            "total_income": round(income, 2),
            "total_expense": round(expense, 2),
            "net_cashflow": round(net, 2),
            "savings_rate": round(net / income * 100, 1) if income > 0 else None,
            "top_expense_category": top_category[0],
            "top_expense_amount": round(float(top_category[1] or 0), 2),
            "previous_month_expense": round(float(previous["total_expense"] or 0), 2),
            "expense_change_rate": expense_change_rate,
            "observations": observations,
        },
    }


def get_today_overview(conn) -> dict:
    today = date.today()
    stats = compute_stats(conn)
    planning = get_planning(conn)
    calendar = get_financial_calendar(conn)
    monthly_budget = planning["budget_status"]
    semester = planning["semester"]
    today_expense = float(conn.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type = 'expense' AND occurred_on = ?",
        (today.isoformat(),),
    ).fetchone()[0] or 0)

    daily_caps = []
    monthly_remaining = monthly_budget.get("total_remaining")
    if monthly_remaining is not None:
        days_left = monthrange(today.year, today.month)[1] - today.day + 1
        daily_caps.append(max(float(monthly_remaining), 0) / max(days_left, 1))
    if semester.get("configured") and semester.get("status") in {"active", "upcoming"}:
        semester_daily = semester.get("recommended_daily_budget")
        if semester_daily is not None:
            daily_caps.append(max(float(semester_daily), 0))
    suggested_daily = min(daily_caps) if daily_caps else None
    available_today = max(suggested_daily - today_expense, 0) if suggested_daily is not None else None

    upcoming_bills = [
        bill for bill in calendar["bills"]
        if not bill["is_paid"] and (bill["status"] == "overdue" or (bill["days_until_due"] is not None and bill["days_until_due"] <= 7))
    ][:5]
    goals = planning["goals"][:3]
    overdue_count = sum(1 for bill in upcoming_bills if bill["status"] == "overdue")
    if overdue_count:
        headline = f"有 {overdue_count} 项固定账单已经到期，先处理确定性支出。"
        tone = "alert"
    elif suggested_daily is None:
        headline = "先设置月预算或学期预算，今日可花才有可靠依据。"
        tone = "neutral"
    elif today_expense > suggested_daily:
        headline = "今天已经超过建议额度，后续消费可以更谨慎一些。"
        tone = "warning"
    elif upcoming_bills:
        headline = f"未来 7 天有 {len(upcoming_bills)} 项固定账单，今日额度已为预算留出空间。"
        tone = "notice"
    else:
        headline = "今天没有紧急账单，按建议额度正常生活即可。"
        tone = "safe"

    return {
        "date": today.isoformat(),
        "headline": headline,
        "tone": tone,
        "current_balance": round(float(stats["current_balance"] or 0), 2),
        "today_expense": round(today_expense, 2),
        "suggested_daily_budget": round(suggested_daily, 2) if suggested_daily is not None else None,
        "available_today": round(available_today, 2) if available_today is not None else None,
        "monthly_budget_remaining": monthly_remaining,
        "monthly_budget_status": monthly_budget.get("total_status", "unset"),
        "next_allowance_date": planning["forecast"].get("next_allowance_date"),
        "days_until_next_allowance": planning["forecast"].get("days_until_next_allowance"),
        "projected_balance_before_allowance": planning["forecast"].get("projected_balance_before_allowance"),
        "semester": semester,
        "upcoming_bills": upcoming_bills,
        "goals": goals,
    }


def parse_quick_entry(conn, raw_text: str) -> dict:
    text = " ".join(raw_text.strip().split())
    if not text:
        raise HTTPException(400, "请输入一句记账内容")
    working = text
    when = date.today()
    date_signal = False
    explicit_date = re.search(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", working)
    month_day = re.search(r"(?<!\d)(\d{1,2})月(\d{1,2})日", working)
    if explicit_date:
        try:
            when = date(int(explicit_date.group(1)), int(explicit_date.group(2)), int(explicit_date.group(3)))
        except ValueError as exc:
            raise HTTPException(400, "日期无法识别") from exc
        working = working.replace(explicit_date.group(0), " ")
        date_signal = True
    elif month_day:
        try:
            when = date(date.today().year, int(month_day.group(1)), int(month_day.group(2)))
        except ValueError as exc:
            raise HTTPException(400, "日期无法识别") from exc
        working = working.replace(month_day.group(0), " ")
        date_signal = True
    elif "前天" in working:
        when = date.today() - timedelta(days=2)
        working = working.replace("前天", " ")
        date_signal = True
    elif "昨天" in working:
        when = date.today() - timedelta(days=1)
        working = working.replace("昨天", " ")
        date_signal = True
    elif "今天" in working:
        working = working.replace("今天", " ")
        date_signal = True

    currency_amount = re.search(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)", working)
    amount_match = currency_amount or re.search(r"(?<!\d)(\d+(?:\.\d{1,2})?)(?!\d)", working)
    if not amount_match:
        raise HTTPException(400, "没有识别到金额，例如：午饭 16.5 支付宝")
    amount = float(amount_match.group(1))
    if amount <= 0:
        raise HTTPException(400, "金额必须大于 0")

    income_sources = [
        ("scholarship", ("奖学金", "助学金")),
        ("part_time", ("兼职", "实习", "工资")),
        ("project", ("项目", "稿费", "创作")),
        ("investment", ("利息", "分红", "投资收益")),
        ("family_support", ("生活费", "家里", "父母", "家庭支持")),
    ]
    source = None
    for source_key, keywords in income_sources:
        if any(keyword in text for keyword in keywords):
            source = source_key
            break
    is_income = source is not None or any(keyword in text for keyword in ("收入", "到账", "进账"))
    tx_type = "income" if is_income else "expense"
    if tx_type == "income" and source is None:
        source = "other"

    category_keywords = [
        ("food", ("早餐", "午饭", "晚饭", "吃饭", "餐", "奶茶", "咖啡", "外卖", "水果", "零食", "食堂")),
        ("transport", ("地铁", "公交", "打车", "滴滴", "高铁", "火车", "机票", "骑行", "交通")),
        ("study", ("书", "教材", "打印", "考试", "课程", "文具", "学习")),
        ("housing", ("房租", "住宿", "宿舍", "水费", "电费", "燃气")),
        ("medical", ("医院", "药", "体检", "医疗")),
        ("entertainment", ("电影", "游戏", "演出", "娱乐", "旅游")),
        ("social", ("聚餐", "请客", "礼物", "社交")),
        ("digital", ("会员", "软件", "订阅", "流量", "话费", "网费", "数字")),
    ]
    category = "income" if tx_type == "income" else "other"
    category_signal = False
    if tx_type == "expense":
        for category_key, keywords in category_keywords:
            if any(keyword in text for keyword in keywords):
                category = category_key
                category_signal = True
                break

    accounts = [dict(row) for row in conn.execute(
        "SELECT id, name, type FROM accounts WHERE is_active = 1 ORDER BY id"
    ).fetchall()]
    if not accounts:
        raise HTTPException(400, "当前没有可用账户")
    account = next((item for item in sorted(accounts, key=lambda item: len(item["name"]), reverse=True) if item["name"] in text), None)
    if account is None:
        account_aliases = {
            "wechat": ("微信",), "alipay": ("支付宝",), "campus": ("校园卡", "饭卡"),
            "cash": ("现金",), "bank": ("银行卡", "银行"),
        }
        wanted_type = next((kind for kind, aliases in account_aliases.items() if any(alias in text for alias in aliases)), None)
        account = next((item for item in accounts if item["type"] == wanted_type), None) if wanted_type else None
    account_signal = account is not None
    if account is None:
        account = accounts[0]

    warnings = []
    if tx_type == "expense" and not category_signal:
        warnings.append("未识别具体支出分类，暂归为“其他”")
    if not account_signal:
        warnings.append(f"未识别账户，暂使用“{account['name']}”")
    confidence = 0.5 + (0.2 if category_signal or tx_type == "income" else 0) + (0.2 if account_signal else 0) + (0.1 if date_signal else 0)
    return {
        "input": text,
        "confidence": round(min(confidence, 0.99), 2),
        "warnings": warnings,
        "transaction": {
            "type": tx_type,
            "source": source if tx_type == "income" else None,
            "category": category if tx_type == "expense" else None,
            "account_id": account["id"],
            "account_name": account["name"],
            "amount": round(amount, 2),
            "occurred_on": when.isoformat(),
            "note": text,
        },
    }

def get_annual_report(conn, year: int) -> dict:
    if year < 1900 or year > 2200:
        raise HTTPException(400, "year out of range")
    start = date(year, 1, 1)
    end = date(year + 1, 1, 1)
    monthly = []
    for month in range(1, 13):
        month_data = compute_monthly(conn, f"{year}-{month:02d}")
        monthly.append({
            "month": month_data["month"],
            "income": month_data["total_income"],
            "expense": month_data["total_expense"],
            "family_support": month_data["family_support"],
            "independent_income": month_data["independent_income"],
            "net_cashflow": month_data["net_cashflow"],
        })
    totals = conn.execute(
        """SELECT
             COUNT(*) AS transaction_count,
             COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) AS income,
             COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0) AS expense,
             COALESCE(SUM(CASE WHEN type = 'income' AND source = 'family_support' THEN amount ELSE 0 END), 0) AS family,
             COALESCE(SUM(CASE WHEN type = 'income' AND source != 'family_support' THEN amount ELSE 0 END), 0) AS independent
           FROM transactions WHERE occurred_on >= ? AND occurred_on < ?""",
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    category_rows = conn.execute(
        """SELECT category, SUM(amount) AS amount FROM transactions
           WHERE type = 'expense' AND occurred_on >= ? AND occurred_on < ?
           GROUP BY category ORDER BY amount DESC""",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    source_rows = conn.execute(
        """SELECT source, SUM(amount) AS amount FROM transactions
           WHERE type = 'income' AND occurred_on >= ? AND occurred_on < ?
           GROUP BY source ORDER BY amount DESC""",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    income = float(totals["income"] or 0)
    expense = float(totals["expense"] or 0)
    net = income - expense
    active_months = [item for item in monthly if item["income"] or item["expense"]]
    best_month = max(active_months, key=lambda item: item["net_cashflow"], default=None)
    highest_expense_month = max(active_months, key=lambda item: item["expense"], default=None)
    return {
        "year": year,
        "summary": {
            "transaction_count": int(totals["transaction_count"] or 0),
            "total_income": round(income, 2),
            "total_expense": round(expense, 2),
            "net_cashflow": round(net, 2),
            "family_support": round(float(totals["family"] or 0), 2),
            "independent_income": round(float(totals["independent"] or 0), 2),
            "savings_rate": round(net / income * 100, 1) if income > 0 else None,
            "active_months": len(active_months),
        },
        "monthly": monthly,
        "expense_categories": [
            {"category": row["category"], "amount": round(float(row["amount"] or 0), 2)}
            for row in category_rows
        ],
        "income_sources": [
            {"source": row["source"], "amount": round(float(row["amount"] or 0), 2)}
            for row in source_rows
        ],
        "best_cashflow_month": best_month,
        "highest_expense_month": highest_expense_month,
    }


def create_transaction(
    conn, *, occurred_on: Optional[str] = None, type: str, amount: float,
    source: Optional[str] = None, category: Optional[str] = None,
    account_id: Optional[int] = None, note: str = "",
) -> dict:
    """写入一笔交易，返回带账户名的完整记录。

    收入的 source 与支出的 category 在这里归一，不接受两者混用；
    没有指定账户时落到第一个启用账户。
    """
    when = occurred_on or date.today().isoformat()
    date.fromisoformat(when)
    if type not in ("income", "expense"):
        raise HTTPException(400, "type must be income or expense")
    if amount is None or amount <= 0:
        raise HTTPException(400, "金额必须大于 0")
    resolved_source = (source or "family_support") if type == "income" else "expense"
    resolved_category = "income" if type == "income" else (category or "other")
    if account_id is None:
        default_account = conn.execute(
            "SELECT id FROM accounts WHERE is_active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if not default_account:
            raise HTTPException(400, "no active account")
        account_id = default_account["id"]
    if not conn.execute(
        "SELECT 1 FROM accounts WHERE id = ? AND is_active = 1", (account_id,)
    ).fetchone():
        raise HTTPException(400, "invalid account")
    cur = conn.execute(
        """INSERT INTO transactions
           (occurred_on, type, source, category, account_id, amount, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (when, type, resolved_source, resolved_category, account_id, amount, note,
         datetime.now().isoformat()),
    )
    return dict(conn.execute(
        """SELECT t.*, a.name AS account_name FROM transactions t
           LEFT JOIN accounts a ON a.id = t.account_id WHERE t.id = ?""",
        (cur.lastrowid,),
    ).fetchone())


# ---------- 订阅与固定支出 ----------

CYCLES = {"monthly": 1, "quarterly": 3, "yearly": 12}
CYCLE_LABELS = {"monthly": "每月", "quarterly": "每季", "yearly": "每年"}


def bill_due_in_month(bill: dict, year: int, month: int) -> bool:
    """这笔固定支出在指定月份是否到期。

    每月的每月都到期；季付与年付按锚点月份推算。
    没有锚点月份的非月付账单，保守地按「首次记录的那个月」为锚点是做不到的
    （建单时没记），所以退化成每月——宁可多提醒，不要漏提醒。
    """
    cycle = bill.get("cycle") or "monthly"
    if cycle == "monthly":
        return True
    step = CYCLES.get(cycle)
    if not step:
        return True
    anchor = bill.get("anchor_month")
    if not anchor:
        return True
    return (month - int(anchor)) % step == 0


def get_subscription_overview(conn) -> dict:
    """我到底订了多少东西，一个月和一年各要花多少。

    月均成本是把年付摊到每个月，方便横向比较；
    它是一个换算值，不是某个月真的会扣这么多。
    """
    rows = conn.execute(
        """SELECT b.*, a.name AS account_name FROM recurring_bills b
           JOIN accounts a ON a.id = b.account_id
           WHERE b.is_active = 1
           ORDER BY b.day_of_month, b.id"""
    ).fetchall()

    today = date.today()
    items = []
    monthly_total = 0.0
    by_category: dict[str, float] = {}
    for row in rows:
        bill = dict(row)
        cycle = bill.get("cycle") or "monthly"
        months = CYCLES.get(cycle, 1)
        amount = float(bill["amount"])
        per_month = round(amount / months, 2)
        monthly_total += per_month
        by_category[bill["category"]] = round(
            by_category.get(bill["category"], 0.0) + per_month, 2
        )

        next_due = None
        for offset in range(0, 13):
            candidate = shift_month(month_start(today), offset)
            if not bill_due_in_month(bill, candidate.year, candidate.month):
                continue
            days_in_month = monthrange(candidate.year, candidate.month)[1]
            due = date(candidate.year, candidate.month,
                       min(int(bill["day_of_month"]), days_in_month))
            if due >= today:
                next_due = due
                break

        items.append({
            **bill,
            "cycle": cycle,
            "cycle_label": CYCLE_LABELS.get(cycle, cycle),
            "monthly_cost": per_month,
            "yearly_cost": round(amount * (12 / months), 2),
            "next_due": next_due.isoformat() if next_due else None,
            "days_until_due": (next_due - today).days if next_due else None,
        })

    items.sort(key=lambda item: (item["days_until_due"] is None, item["days_until_due"] or 0))
    return {
        "items": items,
        "summary": {
            "count": len(items),
            "monthly_total": round(monthly_total, 2),
            "yearly_total": round(monthly_total * 12, 2),
            "by_category": by_category,
            "due_within_7_days": [
                item["name"] for item in items
                if item["days_until_due"] is not None and item["days_until_due"] <= 7
            ],
        },
        "cycle_labels": CYCLE_LABELS,
        "note": "月均成本把年付摊到每个月，方便比较；它是换算值，不是某个月真会扣这么多。",
    }


def migrate(conn) -> None:
    """旧库兼容：补列、回填分类与来源、确保存在一个默认账户。

    历史收入保守地归为家庭生活费，避免升级后把既有生活费误算成自主收入。
    """
    # migration: 添加新增列（旧库兼容）
    cols = [r[1] for r in conn.execute("PRAGMA table_info(settings)").fetchall()]
    if "show_past" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN show_past INTEGER NOT NULL DEFAULT 0")
    if "initial_assets" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN initial_assets REAL NOT NULL DEFAULT 0")
    if "use_initial_assets" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN use_initial_assets INTEGER NOT NULL DEFAULT 0")
    if "tracking_days_override" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN tracking_days_override INTEGER NOT NULL DEFAULT 0")
    if "avg_daily_expense_override" not in cols:
        conn.execute("ALTER TABLE settings ADD COLUMN avg_daily_expense_override REAL NOT NULL DEFAULT 0")

    tx_cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
    if "source" not in tx_cols:
        # 当前产品用于大学生生活账本：历史收入保守地归为家庭生活费，
        # 避免升级后把既有生活费误算成自主收入。
        conn.execute("ALTER TABLE transactions ADD COLUMN source TEXT NOT NULL DEFAULT 'family_support'")
    if "category" not in tx_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN category TEXT NOT NULL DEFAULT 'other'")
    if "account_id" not in tx_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN account_id INTEGER")
    if "import_batch_id" not in tx_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN import_batch_id INTEGER")
    if "import_row_number" not in tx_cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN import_row_number INTEGER")
    conn.execute("UPDATE transactions SET source = 'expense' WHERE type = 'expense'")
    conn.execute(
        """UPDATE transactions SET source = 'family_support'
           WHERE type = 'income' AND source NOT IN
           ('family_support','scholarship','part_time','project','investment','other')"""
    )
    conn.execute("UPDATE transactions SET category = 'income' WHERE type = 'income'")
    conn.execute(
        """UPDATE transactions SET category = 'other'
           WHERE type = 'expense' AND category NOT IN
           ('food','transport','study','housing','medical','entertainment','social','digital','other')"""
    )

    # 固定账单原本隐含「每月一次」；补上计费周期与年付/季付的锚点月份。
    # 旧数据一律按每月处理，语义不变。
    bill_cols = [r[1] for r in conn.execute("PRAGMA table_info(recurring_bills)").fetchall()]
    if "cycle" not in bill_cols:
        conn.execute(
            "ALTER TABLE recurring_bills ADD COLUMN cycle TEXT NOT NULL DEFAULT 'monthly'"
        )
    if "anchor_month" not in bill_cols:
        conn.execute("ALTER TABLE recurring_bills ADD COLUMN anchor_month INTEGER")

    default_account = conn.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()
    if not default_account:
        settings = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        opening_balance = 0.0
        if settings:
            setting_keys = set(settings.keys())
            if "use_initial_assets" in setting_keys and bool(settings["use_initial_assets"]):
                opening_balance = float(settings["initial_assets"] or 0)
        cur = conn.execute(
            """INSERT INTO accounts (name, type, opening_balance, is_active, created_at)
               VALUES (?, ?, ?, 1, ?)""",
            ("日常资金", "other", opening_balance, datetime.now().isoformat()),
        )
        default_account_id = cur.lastrowid
    else:
        default_account_id = default_account["id"]
    conn.execute(
        "UPDATE transactions SET account_id = ? WHERE account_id IS NULL",
        (default_account_id,),
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          birth_date TEXT NOT NULL,
          target_age INTEGER NOT NULL DEFAULT 80,
          currency TEXT DEFAULT 'CNY',
          show_past INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS transactions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          occurred_on TEXT NOT NULL,
          type TEXT NOT NULL CHECK (type IN ('income','expense')),
          source TEXT NOT NULL DEFAULT 'family_support',
          amount REAL NOT NULL CHECK (amount > 0),
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          type TEXT NOT NULL DEFAULT 'other',
          opening_balance REAL NOT NULL DEFAULT 0,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS account_transfers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          from_account_id INTEGER NOT NULL REFERENCES accounts(id),
          to_account_id INTEGER NOT NULL REFERENCES accounts(id),
          amount REAL NOT NULL CHECK (amount > 0),
          occurred_on TEXT NOT NULL,
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL,
          CHECK (from_account_id != to_account_id)
        );
CREATE TABLE IF NOT EXISTS account_adjustments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL REFERENCES accounts(id),
          delta REAL NOT NULL CHECK (delta != 0),
          actual_balance REAL NOT NULL,
          occurred_on TEXT NOT NULL,
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS planning_settings (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          monthly_allowance_amount REAL NOT NULL DEFAULT 0 CHECK (monthly_allowance_amount >= 0),
          allowance_day INTEGER NOT NULL DEFAULT 1 CHECK (allowance_day BETWEEN 1 AND 28),
          monthly_spending_budget REAL NOT NULL DEFAULT 0 CHECK (monthly_spending_budget >= 0),
          updated_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS semester_settings (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          start_date TEXT,
          end_date TEXT,
          total_budget REAL NOT NULL DEFAULT 0 CHECK (total_budget >= 0),
          mode TEXT NOT NULL DEFAULT 'in_school' CHECK (mode IN ('in_school','vacation')),
          updated_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS savings_goals (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          target_amount REAL NOT NULL CHECK (target_amount > 0),
          saved_amount REAL NOT NULL DEFAULT 0 CHECK (saved_amount >= 0),
          target_date TEXT,
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS category_budgets (
          category TEXT PRIMARY KEY,
          amount REAL NOT NULL CHECK (amount >= 0),
          updated_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS import_batches (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          filename TEXT NOT NULL,
          content_hash TEXT NOT NULL UNIQUE,
          row_count INTEGER NOT NULL CHECK (row_count > 0),
          created_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS recurring_bills (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          amount REAL NOT NULL CHECK (amount > 0),
          day_of_month INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 28),
          category TEXT NOT NULL,
          account_id INTEGER NOT NULL REFERENCES accounts(id),
          note TEXT DEFAULT '',
          is_active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS recurring_bill_payments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          bill_id INTEGER NOT NULL REFERENCES recurring_bills(id),
          month TEXT NOT NULL,
          transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
          paid_on TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE (bill_id, month)
        );
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(occurred_on);
CREATE INDEX IF NOT EXISTS idx_transfer_date ON account_transfers(occurred_on);
CREATE INDEX IF NOT EXISTS idx_adjustment_date ON account_adjustments(occurred_on);
CREATE INDEX IF NOT EXISTS idx_bill_payment_month ON recurring_bill_payments(month);
"""


MODULE = LifeModule(
    key="ledger",
    label="个人账本",
    schema=SCHEMA,
    tables={
        "settings": ["id", "birth_date", "target_age", "currency", "show_past", "created_at", "initial_assets", "use_initial_assets", "tracking_days_override", "avg_daily_expense_override"],
        "accounts": ["id", "name", "type", "opening_balance", "is_active", "created_at"],
        "import_batches": ["id", "filename", "content_hash", "row_count", "created_at"],
        "transactions": ["id", "occurred_on", "type", "source", "amount", "note", "created_at", "category", "account_id", "import_batch_id", "import_row_number"],
        "account_transfers": ["id", "from_account_id", "to_account_id", "amount", "occurred_on", "note", "created_at"],
        "account_adjustments": ["id", "account_id", "delta", "actual_balance", "occurred_on", "note", "created_at"],
        "planning_settings": ["id", "monthly_allowance_amount", "allowance_day", "monthly_spending_budget", "updated_at"],
        "semester_settings": ["id", "start_date", "end_date", "total_budget", "mode", "updated_at"],
        "savings_goals": ["id", "name", "target_amount", "saved_amount", "target_date", "is_active", "created_at"],
        "category_budgets": ["category", "amount", "updated_at"],
        "recurring_bills": ["id", "name", "amount", "day_of_month", "category", "account_id",
                           "note", "is_active", "created_at", "cycle", "anchor_month"],
        "recurring_bill_payments": ["id", "bill_id", "month", "transaction_id", "paid_on", "created_at"],
    },
    optional_tables=frozenset({"semester_settings"}),
    delete_order=(
        "recurring_bill_payments",
        "recurring_bills",
        "account_transfers",
        "account_adjustments",
        "transactions",
        "import_batches",
        "savings_goals",
        "category_budgets",
        "semester_settings",
        "planning_settings",
        "accounts",
        "settings",
    ),
    migrate=migrate,
)
