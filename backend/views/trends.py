"""按周 / 按月看每个指标的走势。

平台原本只有两种时间尺度：今天（生活总览）和全年（年度报告），中间是空的。
「这周比上周怎么样」这种最常问的问题，之前没有地方回答。

指标定义直接复用 insights.METRICS，不另起一套：同一件事在「趋势」和
「同期变化」里必须是同一个数，否则两个页面会互相拆台。

四条规矩：

1. **只统计有记录的天，不补零。** 「没记」和「是 0」完全是两回事——
   没记录那天的睡眠不是 0 小时。

2. **变化一律按「有记录那些天的日均」算，不按总和。** 这一条最要紧：
   本周记了 7 天、上周只记了 2 天，总和翻三倍不代表你真花得更多，
   只代表你这周记得更勤。总和照样显示，但它只是参考，不参与比较。

3. **两期记录疏密悬殊就不给变化数字**，而不是给一个看起来很确定的百分比。
   注意挡的是「悬殊」不是「稀疏」——一周只练两次力量的人也该看得到走势。

4. **只描述变化，不评价。** 支出涨了不等于"变差了"，睡眠变少也可能是
   那几天在赶due。这里不替用户下结论。
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Optional

from fastapi import HTTPException

from backend.views.insights import METRICS

# 一个点算不出平均值，两个点才勉强算得上一期的水平。
MIN_DAYS_PER_PERIOD = 2

# 两期的记录天数不能悬殊：稀疏那期至少要有稠密那期的一半。
#
# 这两条一起工作。真正要防的是**覆盖度悬殊**而不是绝对天数——
# 上周记 2 天、本周记 6 天，日均看着可比，其实那 2 天代表不了上周。
#
# 曾经的写法是「两期都得满 3 天」，那会把一整类合理的使用方式静默排除掉：
# 一周练两次力量的人永远拿不到训练容量的趋势，一周量两次体重的人
# 永远看不到体重变化。稀疏不等于不可比，悬殊才不可比。
MIN_COVERAGE_RATIO = 0.5

# 每个指标该怎么归并到一期。
# sum  ：这一期一共多少（学习时长、支出这类累计量）
# mean ：这一期平均什么水平（睡眠、心情、体重这类状态量，加总没有意义）
AGGREGATIONS = {
    "sleep_hours": "mean",
    "energy": "mean",
    "mood": "mean",
    "weight_kg": "mean",
    "study_minutes": "sum",
    "fitness_minutes": "sum",
    "training_volume": "sum",
    "expense": "sum",
    "calories": "sum",
    "water_ml": "sum",
}

PERIODS = {"week": "周", "month": "月"}


def _week_starts(today: date, count: int) -> list[tuple[date, date, str]]:
    this_monday = today - timedelta(days=today.weekday())
    bounds = []
    for offset in range(count - 1, -1, -1):
        start = this_monday - timedelta(weeks=offset)
        end = start + timedelta(days=6)
        label = "本周" if offset == 0 else ("上周" if offset == 1 else f"{start.month}/{start.day} 那周")
        bounds.append((start, end, label))
    return bounds


def _month_starts(today: date, count: int) -> list[tuple[date, date, str]]:
    bounds = []
    year, month = today.year, today.month
    for offset in range(count - 1, -1, -1):
        total = (year * 12 + month - 1) - offset
        y, m = divmod(total, 12)
        m += 1
        start = date(y, m, 1)
        end = date(y, m, monthrange(y, m)[1])
        label = "本月" if offset == 0 else ("上月" if offset == 1 else f"{y}-{m:02d}")
        bounds.append((start, end, label))
    return bounds


def _bounds(period: str, count: int, today: date):
    if period not in PERIODS:
        raise HTTPException(400, f"未知的周期：{period}")
    return _week_starts(today, count) if period == "week" else _month_starts(today, count)


def _daily_values(conn, metric: str, start: str) -> dict[str, float]:
    _, _, sql = METRICS[metric]
    rows = conn.execute(
        f"SELECT occurred_on, value FROM ({sql}) WHERE occurred_on >= ? AND value IS NOT NULL",
        (start,),
    ).fetchall()
    return {row["occurred_on"]: float(row["value"]) for row in rows}


def _describe_change(current: Optional[dict], previous: Optional[dict]) -> dict:
    """只比较日均，并且两期都得有足够的记录天数。"""
    if not current or not previous:
        return {"comparable": False, "reason": "还没有可比的上一期"}
    if current["days"] < MIN_DAYS_PER_PERIOD or previous["days"] < MIN_DAYS_PER_PERIOD:
        return {
            "comparable": False,
            "reason": f"至少要有 {MIN_DAYS_PER_PERIOD} 天记录才算得出一期的水平，"
                      f"这一期记了 {current['days']} 天、上一期 {previous['days']} 天",
        }
    thin, thick = sorted((current["days"], previous["days"]))
    if thin < thick * MIN_COVERAGE_RATIO:
        return {
            "comparable": False,
            "reason": f"两期记录多少差太远（{previous['days']} 天 对 {current['days']} 天），"
                      f"少的那期代表不了整期，比出来的差别多半是记录疏密造成的",
        }
    before, after = previous["average"], current["average"]
    delta = round(after - before, 2)
    percent = round(delta / before * 100, 1) if before else None
    return {
        "comparable": True,
        "delta": delta,
        "percent": percent,
        "direction": "up" if delta > 0 else ("down" if delta < 0 else "flat"),
        "basis": "按有记录那些天的日均比较，不按总和",
    }


def get_trends(conn, period: str = "week", count: int = 6) -> dict:
    """每个指标最近几期的走势，以及最新一期和上一期的差别。只读。"""
    if count < 2 or count > 24:
        raise HTTPException(400, "count out of range")
    today = date.today()
    bounds = _bounds(period, count, today)
    earliest = bounds[0][0].isoformat()

    tracked, untracked = [], []
    for key, (label, unit, _) in METRICS.items():
        values = _daily_values(conn, key, earliest)
        how = AGGREGATIONS[key]
        buckets = []
        for start, end, bucket_label in bounds:
            days = [v for day, v in values.items() if start.isoformat() <= day <= end.isoformat()]
            if not days:
                buckets.append({
                    "label": bucket_label, "start": start.isoformat(), "end": end.isoformat(),
                    "days": 0, "total": None, "average": None,
                })
                continue
            total = round(sum(days), 2)
            buckets.append({
                "label": bucket_label, "start": start.isoformat(), "end": end.isoformat(),
                "days": len(days),
                "total": total if how == "sum" else None,
                "average": round(total / len(days), 2),
            })

        recorded = [b for b in buckets if b["days"]]
        entry = {
            "key": key, "label": label, "unit": unit, "aggregation": how,
            "buckets": buckets,
            "recorded_periods": len(recorded),
            "change": _describe_change(
                buckets[-1] if buckets[-1]["days"] else None,
                buckets[-2] if len(buckets) > 1 and buckets[-2]["days"] else None,
            ),
        }
        (tracked if recorded else untracked).append(entry)

    # 有记录的排前面，记得越连续越靠前——空的那些沉到底下，用一句话带过。
    tracked.sort(key=lambda item: -item["recorded_periods"])
    return {
        "period": period,
        "period_label": PERIODS[period],
        "count": count,
        "generated_on": today.isoformat(),
        "metrics": tracked,
        "untracked": [{"key": m["key"], "label": m["label"]} for m in untracked],
        "note": (
            "只统计有记录的那些天，不补零；变化按日均算，因为记得勤不等于花得多。"
            "这里只描述变化，不评价好坏。"
        ),
    }
