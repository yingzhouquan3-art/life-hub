"""演示数据注入器
- 60 天 · 平均日花销 / 日收入可配置
- 不删库 · 不重建 schema（复用 main.py 的 init_db）
- 不覆盖已有 birth_date · 重置覆盖字段
"""
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "ledger.db"

# ---- 可配置 ----
DAYS = 60
TARGET_AVG_EXPENSE_PER_DAY = 70.0
TARGET_AVG_INCOME_PER_DAY = 500.0
DEFAULT_TARGET_AGE_OFFSET = 26  # 仅当库中无 settings 时使用

EXPENSE_NOTES = [
    "早餐", "午餐", "晚餐", "咖啡", "打车", "地铁", "买菜", "水电", "外卖",
    "夜宵", "理发", "书", "电影", "看牙医", "话费", "健身", "保险",
    "下午茶", "买花", "蛋糕", "茶饮", "超市", "停车", "网费",
]
INCOME_NOTES_REGULAR = ["写作收入", "课程分成", "广告", "咨询", "稿费", "推广"]
INCOME_NOTES_BIG = ["项目尾款", "课程发布", "联名合作", "客户预付", "结算"]


def main():
    random.seed(42)

    # 强制走 main.py 的 init_db,保证 schema 同步
    sys.path.insert(0, str(ROOT))
    from backend import main as backend_main  # noqa: F401  side-effect: init_db()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    # 1) 清空交易
    conn.execute("DELETE FROM transactions")

    # 2) 重置覆盖字段(避免与新派生数据矛盾)
    existing = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    today = date.today()
    if existing:
        conn.execute("""
            UPDATE settings SET
              tracking_days_override = 0,
              avg_daily_expense_override = 0
            WHERE id = 1
        """)
        print(f"[settings] 保留现有 birth_date={existing['birth_date']} · 重置 override")
    else:
        # 接收方首跑时给一个默认生日(避免 NOT NULL 报错)
        birth = today.replace(year=today.year - DEFAULT_TARGET_AGE_OFFSET)
        conn.execute(
            """INSERT INTO settings (id, birth_date, target_age, currency, show_past,
                use_initial_assets, initial_assets, tracking_days_override,
                avg_daily_expense_override, created_at)
               VALUES (1, ?, 80, 'CNY', 0, 0, 0, 0, 0, ?)""",
            (birth.isoformat(), datetime.now().isoformat()),
        )
        print(f"[settings] 写入默认 birth_date={birth.isoformat()}(请在 UI 改成你的真实生日)")

    # 3) 生成支出
    start = today - timedelta(days=DAYS - 1)
    expenses, incomes = [], []
    target_total_expense = TARGET_AVG_EXPENSE_PER_DAY * DAYS
    target_total_income = TARGET_AVG_INCOME_PER_DAY * DAYS

    for d in range(DAYS):
        when = (start + timedelta(days=d)).isoformat()
        n = random.choices([1, 2, 3], weights=[2, 5, 3])[0]
        for _ in range(n):
            amt = round(random.gauss(20, 8), 2)
            if random.random() < 0.05:
                amt = round(random.uniform(150, 380), 2)
            amt = max(round(amt, 2), 3.0)
            expenses.append((when, "expense", amt, random.choice(EXPENSE_NOTES)))

    scale = target_total_expense / sum(e[2] for e in expenses)
    expenses = [(d, t, round(a * scale, 2), n) for d, t, a, n in expenses]

    # 4) 生成收入
    for d in range(DAYS):
        when = (start + timedelta(days=d)).isoformat()
        if random.random() < 0.55:
            incomes.append((when, "income", round(random.uniform(80, 350), 2),
                            random.choice(INCOME_NOTES_REGULAR)))
        if d > 0 and d % random.choice([7, 8, 9, 10]) == 0:
            incomes.append((when, "income", round(random.uniform(800, 2200), 2),
                            random.choice(INCOME_NOTES_REGULAR)))
        if random.random() < 0.08:
            incomes.append((when, "income", round(random.uniform(2500, 6000), 2),
                            random.choice(INCOME_NOTES_BIG)))

    iscale = target_total_income / sum(i[2] for i in incomes)
    incomes = [(d, t, round(a * iscale, 2), n) for d, t, a, n in incomes]

    # 5) 保证跨度精确 = DAYS
    all_dates = {r[0] for r in expenses + incomes}
    if start.isoformat() not in all_dates:
        expenses.append((start.isoformat(), "expense", 5.0, "锚点"))
    if today.isoformat() not in all_dates:
        expenses.append((today.isoformat(), "expense", 5.0, "锚点"))

    account = conn.execute("SELECT id FROM accounts WHERE is_active = 1 ORDER BY id LIMIT 1").fetchone()
    if not account:
        raise RuntimeError("请先启动一次应用，让系统创建默认账户")
    account_id = account[0]
    rows = [(r[0], r[1], "expense", "other", account_id, r[2], r[3]) for r in expenses]
    rows += [(r[0], r[1], "part_time", "income", account_id, r[2], r[3]) for r in incomes]
    rows.sort(key=lambda r: (r[0], r[1]))
    now = datetime.now().isoformat()
    conn.executemany(
        """INSERT INTO transactions
           (occurred_on, type, source, category, account_id, amount, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [(*r, now) for r in rows],
    )
    conn.commit()
    conn.close()

    total_e = sum(e[2] for e in expenses)
    total_i = sum(i[2] for i in incomes)
    print(f"✓ seeded {len(rows)} transactions across {DAYS} days")
    print(f"  total income  ≈ ¥{total_i:.2f}  (avg/day ≈ {total_i/DAYS:.2f})")
    print(f"  total expense ≈ ¥{total_e:.2f}  (avg/day ≈ {total_e/DAYS:.2f})")
    print(f"  db: {DB}")
    print(f"\n提示:server 若正在跑,刷新浏览器即可看到效果")


if __name__ == "__main__":
    main()
