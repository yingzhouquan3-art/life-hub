"""示例数据：让空平台能被看见，并且能被干净地撤走。

一个刚装好的生活中枢什么都没有，于是每个分析页面都写着「还没有记录」。
用户没法判断这东西对自己有没有用——他要先投入两周的记录，才能看到
第一张有内容的图。这个模块把那两周先借给他。

**它取代了 backend/seed_demo.py。** 那个脚本第一句是
`DELETE FROM transactions`：谁在有真实数据之后手滑跑一次，账本就没了，
没有备份、没有确认、也退不回来。这里三条硬规矩：

1. **绝不删除任何不是自己写的东西。** 每插一条就把 (表, 主键) 记下来，
   撤销时按这份清单精确删除。没记在清单上的一律不碰。
2. **不覆盖已有数据。** 已经装过一次就拒绝再装，先撤销再说；
   已经有真实记录时会明确告知，由用户决定。
3. **走各模块自己的写入函数**，不直接拼 INSERT。示例数据必须和真实数据
   经过同一套校验，否则它能造出应用自己都处理不了的记录。

数据本身刻意造得**不完美**，但不是一律稀疏：

- 记得勤的（支出、睡眠、学习、运动）密到足以让「趋势」给出真实的变化，
  否则示例满屏「暂不比较」，看起来像个坏掉的产品；
- 饮食是「热情三周然后停掉」——真人身上最常见的模式。它让「数据健康度」
  和趋势里的「暂不比较」在示例里**也能被看到**，那正是这两个设计存在的意义。
  这不是为了演示造出来的假稀疏，是真实会发生的事。

一份每天都记满的示例既不像真人，也会让人以为这些克制的设计是多余的。
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from fastapi import HTTPException

from backend.core.registry import LifeModule

# 各模块的写入函数在 load_demo 里再导入。
# modules/__init__.py 要导入本文件来登记 MODULE，这里如果在模块层反向导入
# backend.modules，就成了循环导入——能不能跑通取决于 MODULES 里的登记顺序，
# 那是迟早会炸的依赖。函数内导入把这个耦合彻底去掉。

# 固定种子：同一个人重装两次看到的示例是一样的，出问题也能复现。
SEED = 20260822
DEFAULT_DAYS = 60
MAX_DAYS = 180

_MEALS = (
    ("breakfast", "豆浆油条", 420.0, 12.0),
    ("lunch", "食堂两荤一素", 680.0, 32.0),
    ("lunch", "牛肉面", 620.0, 28.0),
    ("dinner", "鸡胸肉沙拉", 450.0, 38.0),
    ("dinner", "家常炒菜", 700.0, 25.0),
    ("snack", "酸奶", 150.0, 8.0),
)
_EXPENSES = (
    ("食堂午饭", "food", 12.0, 22.0), ("瑞幸", "food", 15.0, 25.0),
    ("美团外卖", "food", 20.0, 45.0), ("地铁", "transport", 3.0, 8.0),
    ("滴滴", "transport", 15.0, 40.0), ("新华书店", "study", 30.0, 90.0),
    ("电费", "housing", 60.0, 120.0), ("药房", "medical", 20.0, 60.0),
    ("电影", "entertainment", 35.0, 60.0), ("网易云会员", "digital", 11.0, 11.0),
    ("超市", "other", 30.0, 120.0),
)
_SUBJECTS = ("高等数学", "英语", "专业课", "论文")
# 权重让力量训练占到一周两三次——真在练的人就是这个频率，
# 而且只有这样，训练容量和 1RM 曲线在示例里才有连续的走势可看。
_WORKOUTS = (("strength", "力量训练", 40, 70, 6), ("cardio", "跑步", 25, 45, 4),
             ("mobility", "拉伸", 15, 25, 2), ("sport", "羽毛球", 50, 90, 1))
_HABITS = (("每天读半小时", "personal"), ("早睡", "health"), ("背单词", "study"))
_TASKS = (("整理这周的笔记", "study", "normal"), ("交课程项目", "study", "high"),
          ("买跑鞋", "personal", "low"), ("预约体检", "health", "normal"))

# 规划参数是**配置**不是记录：它没有主键可以逐条登记，而且用户随时会改。
# 所以只在它还空着的时候写入，撤销时也只在「值还是我写的那些」时才清掉。
# 用户改过就原样留着并说明——宁可留下一点残留，也不能抹掉他自己的设置。
# 这几个数要互相说得通：生活费要够覆盖固定支出加上日常花销，
# 否则示例一打开就是「预计月底 -855」，第一印象变成「你要破产了」。
# 日常约 70/天≈2100，固定支出约 1130，留一点余量。
_PLANNING = {"monthly_allowance_amount": 3600.0, "allowance_day": 5,
             "monthly_spending_budget": 2400.0}
_BUDGETS = {"food": 900.0, "transport": 200.0, "study": 200.0, "entertainment": 150.0}
_BILLS = (("房租", 800.0, 5, "housing", "monthly", None),
          ("网易云会员", 11.0, 8, "digital", "monthly", None),
          ("健身房", 900.0, 15, "other", "quarterly", 8),
          ("视频网站年费", 258.0, 3, "entertainment", "yearly", 9))
_GOALS = (("换台笔记本", 6000.0, 1800.0, 210), ("旅行基金", 3000.0, 450.0, 300))


# 大部分表的主键叫 id，category_budgets 用的是 category。
# 登记册按文本存主键，这样两种都能装下。
KEY_COLUMNS = {"category_budgets": "category"}

# 配置类的表没有「一条记录」的概念，删掉就是把用户的设置清零。
# 所以撤销前要先确认值还是示例数据写进去的那些——用户改过就不动它。
CONFIG_TABLES = {"planning_settings", "category_budgets"}


def _record(conn, batch: str, table: str, row: dict | None) -> None:
    """把刚写进去的那条记在清单上。撤销时只认这份清单。"""
    key = KEY_COLUMNS.get(table, "id")
    if not row or key not in row:
        return
    conn.execute(
        "INSERT INTO demo_records (batch, table_name, record_id, created_at) VALUES (?, ?, ?, ?)",
        (batch, table, str(row[key]), datetime.now().isoformat()),
    )


def _config_untouched(conn, table: str, key: str) -> bool:
    """这条配置还是示例数据当初写的样子吗？改过就返回 False。"""
    if table == "planning_settings":
        row = conn.execute("SELECT * FROM planning_settings WHERE id = 1").fetchone()
        return bool(row) and all(
            abs(float(row[field]) - float(value)) < 0.005
            for field, value in _PLANNING.items())
    row = conn.execute(
        "SELECT amount FROM category_budgets WHERE category = ?", (key,)).fetchone()
    return bool(row) and abs(float(row["amount"]) - _BUDGETS.get(key, -1)) < 0.005


def get_demo_state(conn) -> dict:
    """装没装过示例数据，以及现在库里有多少真实记录。"""
    rows = conn.execute(
        """SELECT batch, COUNT(*) AS count, MIN(created_at) AS loaded_at
           FROM demo_records GROUP BY batch ORDER BY loaded_at DESC"""
    ).fetchall()
    batches = [dict(row) for row in rows]
    # 「有多少是用户自己的记录」在每次开页面时都要算，所以交给 SQL 去做：
    # 早先的写法是把所有 id 读进内存做集合差，几万条记录时那是每次加载都
    # 全表扫六张表。这里靠 demo_records 上的索引走 NOT EXISTS。
    #
    # 主键统一按文本比对——登记册里存的是文本（category_budgets 的主键
    # 本来就是文本），不转的话 5 永远对不上 "5"，示例记录会被整批误算成
    # 用户自己的记录。
    real = 0
    for table in ("transactions", "fitness_sessions", "study_sessions",
                  "recovery_checkins", "nutrition_entries", "body_measurements"):
        if not batches:
            real += conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            continue
        real += conn.execute(
            f"""SELECT COUNT(*) FROM {table} t
                WHERE NOT EXISTS (
                    SELECT 1 FROM demo_records d
                    WHERE d.table_name = ? AND d.record_id = CAST(t.id AS TEXT))""",
            (table,),
        ).fetchone()[0]
    return {
        "loaded": bool(batches),
        "batches": batches,
        "demo_records": sum(b["count"] for b in batches),
        "real_records": real,
        "note": (
            "示例数据只用来看看这个平台长什么样。它和你自己的记录分开登记，"
            "撤销时只删它写进去的那些，绝不碰别的。"
        ),
    }


def load_demo(conn, days: int = DEFAULT_DAYS) -> dict:
    """写入一批跨模块的示例记录。不删除任何已有数据。"""
    if days < 7 or days > MAX_DAYS:
        raise HTTPException(400, f"天数要在 7 到 {MAX_DAYS} 之间")
    if conn.execute("SELECT 1 FROM demo_records LIMIT 1").fetchone():
        raise HTTPException(400, "已经装过示例数据了。要重装请先移除现有的那批。")

    account = conn.execute(
        "SELECT id FROM accounts WHERE is_active = 1 ORDER BY id LIMIT 1").fetchone()
    if not account:
        raise HTTPException(400, "还没有账户，请先启动一次应用让它建好默认账户")
    account_id = account["id"]

    from backend.modules import (body, fitness, ledger, nutrition, recovery,
                                 reflection, rhythm, study)

    # 每个力量动作给一个起始重量，示例里的进步从这里长出来
    _BASE_WEIGHTS = {"深蹲": 60.0, "硬拉": 80.0, "卧推": 45.0,
                     "引体向上": 0.0, "推举": 30.0, "划船": 40.0}
    strength_ids = [
        (row["id"], _BASE_WEIGHTS.get(row["name"], 30.0))
        for row in conn.execute("SELECT id, name FROM exercises WHERE kind = 'strength'")
        if _BASE_WEIGHTS.get(row["name"], 30.0) > 0
    ]

    rng = random.Random(SEED)
    batch = datetime.now().strftime("%Y%m%d-%H%M%S")
    today = date.today()
    start = today - timedelta(days=days - 1)

    for offset in range(days):
        day = start + timedelta(days=offset)
        iso = day.isoformat()
        weekend = day.weekday() >= 5

        # 支出：几乎每天都有，周末多一点
        for _ in range(rng.choices([0, 1, 2, 3], weights=[1, 4, 4, 2])[0]):
            note, category, low, high = rng.choice(_EXPENSES)
            _record(conn, batch, "transactions", ledger.create_transaction(
                conn, occurred_on=iso, type="expense", category=category,
                account_id=account_id, amount=round(rng.uniform(low, high), 2), note=note))

        # 生活费：每月 5 号
        if day.day == 5:
            _record(conn, batch, "transactions", ledger.create_transaction(
                conn, occurred_on=iso, type="income", source="family_support",
                account_id=account_id,
                amount=_PLANNING["monthly_allowance_amount"], note="生活费"))

        # 恢复：记得比较勤，但不是每天——缺的那些天是故意的
        if rng.random() < 0.88:
            hours = round(rng.gauss(7.4 if not weekend else 8.2, 0.8), 1)
            _record(conn, batch, "recovery_checkins", recovery.save_recovery_checkin(
                conn, occurred_on=iso, sleep_hours=max(4.5, min(10.0, hours)),
                sleep_quality=rng.randint(2, 5), energy=rng.randint(2, 5),
                mood=rng.randint(2, 5)))

        # 学习：工作日为主
        if rng.random() < (0.45 if weekend else 0.88):
            _record(conn, batch, "study_sessions", study.record_study_session(
                conn, occurred_on=iso, subject=rng.choice(_SUBJECTS),
                duration_minutes=rng.choice([25, 45, 60, 90, 120]),
                focus=rng.randint(2, 5)))

        # 运动：一周三四次。力量训练要记到「组」，
        # 否则训练容量和 1RM 那一整块在示例里是空的，等于没演示。
        if rng.random() < 0.62:
            activity, name, low, high, _ = rng.choices(
                _WORKOUTS, weights=[w[4] for w in _WORKOUTS])[0]
            session = fitness.record_workout(
                conn, occurred_on=iso, activity=activity,
                duration_minutes=rng.randint(low, high),
                intensity=rng.randint(3, 8), note=name)
            _record(conn, batch, "fitness_sessions", session)
            if activity == "strength" and strength_ids:
                # 重量随时间缓慢上涨，这样 1RM 曲线才有走势可看
                progress = 1.0 + 0.12 * (offset / max(days - 1, 1))
                for exercise_id, base in rng.sample(strength_ids, min(3, len(strength_ids))):
                    for _ in range(rng.randint(3, 4)):
                        _record(conn, batch, "workout_sets", fitness.record_set(
                            conn, session_id=session["id"], exercise_id=exercise_id,
                            reps=rng.choice([5, 6, 8, 10]),
                            weight_kg=round(base * progress * rng.uniform(0.92, 1.05), 1)))

        # 饮食：前面记得挺勤，后面慢慢就不记了。
        # 这是真人身上最常见的模式——某个模块热情三周然后停掉——
        # 也正好让「数据健康度」和趋势里的「暂不比较」在示例里能被看到。
        # 不是为了演示造出来的假稀疏，是真实会发生的事。
        recorded_share = offset / max(days - 1, 1)
        if rng.random() < (0.75 if recorded_share < 0.7 else 0.12):
            for meal_type, name, kcal, protein in rng.sample(_MEALS, rng.randint(1, 3)):
                _record(conn, batch, "nutrition_entries", nutrition.record_meal(
                    conn, occurred_on=iso, meal_type=meal_type, name=name,
                    calories=round(kcal * rng.uniform(0.85, 1.15), 0),
                    protein_g=protein, water_ml=rng.choice([0, 250, 500])))

        # 体重：每周量一两次，缓慢下降
        if day.weekday() in (0, 4) and rng.random() < 0.75:
            drift = -0.35 * (offset / max(days - 1, 1)) * 4
            _record(conn, batch, "body_measurements", body.save_body_measurement(
                conn, occurred_on=iso,
                weight_kg=round(70.5 + drift + rng.gauss(0, 0.3), 1),
                body_fat_pct=round(18.5 + drift * 0.4 + rng.gauss(0, 0.2), 1)))

        # 回顾：每周写两三次
        if rng.random() < 0.3:
            _record(conn, batch, "daily_reflections", reflection.save_daily_reflection(
                conn, occurred_on=iso,
                highlight=rng.choice(["专注了一整个下午", "跑完了五公里", "把拖了很久的事做掉了"]),
                challenge=rng.choice(["下午很困", "被消息打断很多次", ""])))

    # 习惯与待办：不按天生成，单独建
    for name, category in _HABITS:
        habit = rhythm.create_habit(conn, name=name, category=category)
        _record(conn, batch, "habits", habit)
        for offset in range(days):
            day = start + timedelta(days=offset)
            if rng.random() < 0.62:
                rhythm.toggle_habit_checkin(conn, habit["id"], day.isoformat(), desired=True)
        # 打卡记录跟着习惯一起删，不必逐条登记
    for title, category, priority in _TASKS:
        due = today + timedelta(days=rng.randint(-3, 6))
        _record(conn, batch, "personal_tasks", rhythm.create_personal_task(
            conn, title=title, due_on=due.isoformat(), priority=priority, category=category))

    # 规划参数：只在空着时写，写了就登记，撤销时按值比对再决定动不动
    planning_row = conn.execute("SELECT * FROM planning_settings WHERE id = 1").fetchone()
    if not planning_row or not float(planning_row["monthly_allowance_amount"] or 0):
        ledger.save_planning_settings(conn, **_PLANNING)
        _record(conn, batch, "planning_settings", {"id": 1})
    for category, amount in _BUDGETS.items():
        if not conn.execute(
            "SELECT 1 FROM category_budgets WHERE category = ?", (category,)
        ).fetchone():
            ledger.save_category_budget(conn, category=category, amount=amount)
            _record(conn, batch, "category_budgets", {"category": category})

    for name, amount, day, category, cycle, anchor in _BILLS:
        _record(conn, batch, "recurring_bills", ledger.create_recurring_bill(
            conn, name=name, amount=amount, day_of_month=day, category=category,
            account_id=account_id, cycle=cycle, anchor_month=anchor))
    for name, target, saved, ahead in _GOALS:
        _record(conn, batch, "savings_goals", ledger.create_savings_goal(
            conn, name=name, target_amount=target, saved_amount=saved,
            target_date=(today + timedelta(days=ahead)).isoformat()))

    state = get_demo_state(conn)
    return {
        "batch": batch,
        "days": days,
        "written": state["demo_records"],
        **state,
    }


def remove_demo(conn) -> dict:
    """把示例数据精确删掉，只删清单上记着的那些。

    删除顺序用模块注册表推导出来的 DELETE_ORDER（子表在前），
    否则外键会挡住，或者留下悬空的子记录。
    """
    from backend.modules import DELETE_ORDER

    rows = conn.execute("SELECT table_name, record_id FROM demo_records").fetchall()
    if not rows:
        raise HTTPException(400, "没有装过示例数据")

    by_table: dict[str, list[str]] = {}
    for row in rows:
        by_table.setdefault(row["table_name"], []).append(str(row["record_id"]))

    removed = 0
    kept_config = []
    unknown = sorted(set(by_table) - set(DELETE_ORDER))
    for table in DELETE_ORDER:
        keys = by_table.get(table)
        if not keys:
            continue
        column = KEY_COLUMNS.get(table, "id")
        if table in CONFIG_TABLES:
            # 配置改过就留着。宁可留下一点残留，也不能抹掉用户自己的设置。
            removable = []
            for key in keys:
                if _config_untouched(conn, table, key):
                    removable.append(key)
                else:
                    kept_config.append(f"{table}:{key}")
            keys = removable
        if not keys:
            continue
        placeholders = ", ".join("?" for _ in keys)
        cursor = conn.execute(
            f"DELETE FROM {table} WHERE CAST({column} AS TEXT) IN ({placeholders})", keys)
        removed += cursor.rowcount
    conn.execute("DELETE FROM demo_records")
    return {
        "removed": removed,
        # 清单里出现了注册表不认识的表，说明有模块改过名字却没同步。
        # 这种情况下那些行删不掉，必须说出来而不是假装干净了。
        "unknown_tables": unknown,
        # 用户后来改过、因此没有被撤销的配置。说出来，不假装全清干净了。
        "kept_config": kept_config,
        **get_demo_state(conn),
    }


SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch TEXT NOT NULL,
  table_name TEXT NOT NULL,
  record_id TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_demo_batch ON demo_records(batch);
CREATE INDEX IF NOT EXISTS idx_demo_lookup ON demo_records(table_name, record_id);
"""

MODULE = LifeModule(
    key="demo",
    label="示例数据",
    schema=SCHEMA,
    tables={
        "demo_records": ["id", "batch", "table_name", "record_id", "created_at"],
    },
    optional_tables=frozenset({"demo_records"}),
)
