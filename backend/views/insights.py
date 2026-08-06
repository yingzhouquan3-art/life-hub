"""跨模块同期变化。

把各模块按天对齐，看看两个指标是不是一起动。这是整个平台最容易被误读的地方，
所以规矩定死：

- 只呈现**同期变化**，绝不宣称因果。睡得多那天学得久，可能是因为那天是周末。
- 只统计**两个指标都有记录**的那些天。缺一边的天直接跳过，不补零——
  「没记录」和「是 0」完全是两回事。
- 配对天数太少就**不给数字**，而不是给一个看起来很确定的小数。
- 结果里永远带着样本量和这段话的适用边界。

这里不写入任何数据，也不修改来源记录。
"""
from __future__ import annotations

from datetime import date, timedelta
from math import sqrt
from typing import Optional

from fastapi import HTTPException

# 少于这么多配对天数就不给相关系数：三四个点能拟合出任何结论。
MIN_PAIRED_DAYS = 7

# 指标 -> (中文名, 单位, 取数 SQL)。SQL 必须返回 occurred_on 与 value 两列。
METRICS = {
    "sleep_hours": ("睡眠时长", "小时",
                    "SELECT occurred_on, sleep_hours AS value FROM recovery_checkins "
                    "WHERE sleep_hours IS NOT NULL"),
    "energy": ("精力", "1-5",
               "SELECT occurred_on, energy AS value FROM recovery_checkins "
               "WHERE energy IS NOT NULL"),
    "mood": ("心情", "1-5",
             "SELECT occurred_on, mood AS value FROM recovery_checkins "
             "WHERE mood IS NOT NULL"),
    "study_minutes": ("学习时长", "分钟",
                      "SELECT occurred_on, SUM(duration_minutes) AS value FROM study_sessions "
                      "GROUP BY occurred_on"),
    "fitness_minutes": ("运动时长", "分钟",
                        "SELECT occurred_on, SUM(duration_minutes) AS value FROM fitness_sessions "
                        "GROUP BY occurred_on"),
    "training_volume": ("训练容量", "kg",
                        "SELECT f.occurred_on, SUM(s.reps * s.weight_kg) AS value "
                        "FROM workout_sets s JOIN fitness_sessions f ON f.id = s.session_id "
                        "WHERE s.reps IS NOT NULL AND s.weight_kg IS NOT NULL "
                        "GROUP BY f.occurred_on"),
    "expense": ("支出", "元",
                "SELECT occurred_on, SUM(amount) AS value FROM transactions "
                "WHERE type = 'expense' GROUP BY occurred_on"),
    "calories": ("热量", "kcal",
                 "SELECT occurred_on, SUM(calories) AS value FROM nutrition_entries "
                 "WHERE calories IS NOT NULL GROUP BY occurred_on"),
    "water_ml": ("饮水", "ml",
                 "SELECT occurred_on, SUM(water_ml) AS value FROM nutrition_entries "
                 "WHERE water_ml IS NOT NULL GROUP BY occurred_on"),
    "weight_kg": ("体重", "kg",
                  "SELECT occurred_on, weight_kg AS value FROM body_measurements "
                  "WHERE weight_kg IS NOT NULL"),
}

# 默认观察的几组。挑的是「有人可能真的想看」而不是「相关系数最好看」的组合。
DEFAULT_PAIRS = (
    ("sleep_hours", "study_minutes"),
    ("sleep_hours", "energy"),
    ("fitness_minutes", "mood"),
    ("training_volume", "weight_kg"),
    ("expense", "mood"),
    ("calories", "weight_kg"),
)


def _series(conn, metric: str, start: str) -> dict[str, float]:
    if metric not in METRICS:
        raise HTTPException(400, f"未知指标：{metric}")
    _, _, sql = METRICS[metric]
    rows = conn.execute(
        f"SELECT occurred_on, value FROM ({sql}) WHERE occurred_on >= ? AND value IS NOT NULL",
        (start,),
    ).fetchall()
    return {row["occurred_on"]: float(row["value"]) for row in rows}


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    dx = [x - mean_x for x in xs]
    dy = [y - mean_y for y in ys]
    denominator = sqrt(sum(v * v for v in dx)) * sqrt(sum(v * v for v in dy))
    if denominator == 0:
        return None  # 有一边全程没变，相关系数无意义
    return round(sum(a * b for a, b in zip(dx, dy)) / denominator, 3)


def compare_metrics(conn, metric_a: str, metric_b: str, days: int = 90) -> dict:
    """两个指标在同一天的变化关系。

    返回的 correlation 只描述这两列数字一起动的程度，不表示谁引起了谁。
    """
    if days < 7 or days > 3650:
        raise HTTPException(400, "days out of range")
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    left = _series(conn, metric_a, start)
    right = _series(conn, metric_b, start)

    shared = sorted(set(left) & set(right))
    xs = [left[day] for day in shared]
    ys = [right[day] for day in shared]

    label_a, unit_a, _ = METRICS[metric_a]
    label_b, unit_b, _ = METRICS[metric_b]
    result = {
        "metric_a": {"key": metric_a, "label": label_a, "unit": unit_a, "days_with_data": len(left)},
        "metric_b": {"key": metric_b, "label": label_b, "unit": unit_b, "days_with_data": len(right)},
        "paired_days": len(shared),
        "days": days,
        "correlation": None,
        "reason": None,
        "note": "这只是同期变化，不能推导因果。两个指标一起动，也可能是第三个原因在起作用。",
    }

    if len(shared) < MIN_PAIRED_DAYS:
        result["reason"] = (
            f"只有 {len(shared)} 天两项都有记录，少于 {MIN_PAIRED_DAYS} 天不给数字——"
            "点太少的时候什么结论都能拟合出来。"
        )
        return result

    correlation = _pearson(xs, ys)
    if correlation is None:
        result["reason"] = "其中一项在这段时间里完全没有变化，算不出关系。"
        return result

    result["correlation"] = correlation
    result["direction"] = "同向" if correlation > 0 else ("反向" if correlation < 0 else "看不出方向")
    return result


def get_insights(conn, days: int = 90) -> dict:
    """默认几组同期变化。样本不够的照样列出来，如实说明为什么没有数字。"""
    comparisons = [compare_metrics(conn, a, b, days) for a, b in DEFAULT_PAIRS]
    usable = [item for item in comparisons if item["correlation"] is not None]
    return {
        "days": days,
        "comparisons": comparisons,
        "usable_count": len(usable),
        "metrics": {key: {"label": label, "unit": unit} for key, (label, unit, _) in METRICS.items()},
        "note": (
            "这里全部是同期变化，不是因果。记录越连续越有参考价值；"
            "没有数字只表示配对天数不够，不代表两者无关。"
        ),
    }


def get_data_health(conn, days: int = 30) -> dict:
    """各指标最近有没有在记。

    它衡量的是「这个模块还在被使用吗」，不是「用户够不够自律」。
    """
    if days < 1 or days > 3650:
        raise HTTPException(400, "days out of range")
    start = (date.today() - timedelta(days=days - 1)).isoformat()
    health = []
    for key, (label, unit, sql) in METRICS.items():
        rows = conn.execute(
            f"SELECT occurred_on FROM ({sql}) WHERE occurred_on >= ? AND value IS NOT NULL",
            (start,),
        ).fetchall()
        recorded_days = {row["occurred_on"] for row in rows}
        last = conn.execute(
            f"SELECT MAX(occurred_on) AS last FROM ({sql}) WHERE value IS NOT NULL"
        ).fetchone()["last"]
        health.append({
            "key": key,
            "label": label,
            "unit": unit,
            "days_recorded": len(recorded_days),
            "window": days,
            "last_recorded_on": last,
            "days_since": (date.today() - date.fromisoformat(last)).days if last else None,
        })
    health.sort(key=lambda item: (item["days_since"] is None, -(item["days_since"] or 0)))
    return {
        "days": days,
        "metrics": health,
        "note": "没有记录不代表没有发生，只代表这段时间没有记。",
    }
