"""跨模块同期变化与数据健康度的 HTTP 接口。全部只读。"""
from __future__ import annotations

from fastapi import APIRouter

from backend.core.db import db
from backend.views.insights import compare_metrics, get_data_health, get_insights
from backend.views.trends import get_trends

router = APIRouter()


@router.get("/api/insights")
def insights(days: int = 90):
    """默认几组同期变化。这里全部是相关，不是因果。"""
    with db() as conn:
        return get_insights(conn, days)


@router.get("/api/insights/compare")
def compare(metric_a: str, metric_b: str, days: int = 90):
    with db() as conn:
        return compare_metrics(conn, metric_a, metric_b, days)


@router.get("/api/insights/health")
def data_health(days: int = 30):
    """各指标最近有没有在记。衡量的是模块还在不在被使用，不是自律程度。"""
    with db() as conn:
        return get_data_health(conn, days)


@router.get("/api/insights/trends")
def trends(period: str = "week", count: int = 6):
    """每个指标最近几期的走势。变化按日均算，只描述不评价。"""
    with db() as conn:
        return get_trends(conn, period, count)
