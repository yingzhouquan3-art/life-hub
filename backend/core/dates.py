"""共享的日期换算。

[POS] backend/core/dates.py — 不认识任何模块的表，只做纯日期计算
"""
from __future__ import annotations

from datetime import date, timedelta


def month_start(value: date) -> date:
    return value.replace(day=1)


def shift_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + value.month - 1 + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def get_week_bounds(anchor: date) -> tuple[date, date]:
    start = anchor - timedelta(days=anchor.weekday())
    return start, start + timedelta(days=6)
