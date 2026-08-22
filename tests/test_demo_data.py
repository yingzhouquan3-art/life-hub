"""示例数据。

它取代的那个脚本第一句是 `DELETE FROM transactions`，而 README 让用户去跑。
所以这组测试里最重要的不是「装得进去」，而是**它绝不碰不属于它的东西**。
"""
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.api import demo as demo_api
from backend.core import db as db_core
from backend.modules.ledger import (create_transaction, get_planning,
                                    get_subscription_overview, get_today_overview,
                                    save_category_budget, save_planning_settings)

REAL_TABLES = ("transactions", "fitness_sessions", "study_sessions", "recovery_checkins",
               "nutrition_entries", "body_measurements", "daily_reflections",
               "habits", "habit_checkins", "personal_tasks")


class DemoDataTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def counts(self):
        with main.db() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in REAL_TABLES}

    def add_real_records(self):
        """放几条「用户自己的」记录，之后要证明它们毫发无损。"""
        with main.db() as conn:
            account = conn.execute("SELECT id FROM accounts LIMIT 1").fetchone()["id"]
            return [
                create_transaction(conn, occurred_on="2026-08-20", type="expense",
                                   category="food", account_id=account,
                                   amount=42.0, note="我自己记的")["id"],
                create_transaction(conn, occurred_on="2026-08-21", type="income",
                                   source="part_time", account_id=account,
                                   amount=300.0, note="我自己记的收入")["id"],
            ]

    def load(self, days=60):
        return demo_api.demo_load(demo_api.DemoLoadIn(days=days))

    # ---------- 安全：绝不碰不属于自己的东西 ----------

    def test_loading_never_deletes_existing_records(self):
        """被取代的那个脚本就是栽在这里：它上来先清空交易。"""
        mine = self.add_real_records()
        before = self.counts()
        self.load()
        with main.db() as conn:
            for tx_id in mine:
                self.assertIsNotNone(
                    conn.execute("SELECT 1 FROM transactions WHERE id = ?", (tx_id,)).fetchone(),
                    "示例数据装入时弄丢了用户自己的记录")
        after = self.counts()
        for table in REAL_TABLES:
            self.assertGreaterEqual(after[table], before[table])

    def test_removing_deletes_only_what_it_wrote(self):
        mine = self.add_real_records()
        self.load()
        demo_api.demo_remove()
        with main.db() as conn:
            remaining = [dict(r) for r in conn.execute("SELECT id, note FROM transactions")]
        self.assertEqual(sorted(r["id"] for r in remaining), sorted(mine))
        for row in remaining:
            self.assertIn("我自己记的", row["note"])

    def test_removing_leaves_the_other_modules_clean(self):
        self.load()
        demo_api.demo_remove()
        counts = self.counts()
        for table in REAL_TABLES:
            if table == "transactions":
                continue
            self.assertEqual(counts[table], 0, f"{table} 还留着示例数据")

    def test_habit_checkins_go_away_with_their_habit(self):
        """打卡没有逐条登记，靠的是外键级联。级联要是没生效就会留下孤儿。"""
        self.load()
        self.assertGreater(self.counts()["habit_checkins"], 0)
        demo_api.demo_remove()
        self.assertEqual(self.counts()["habit_checkins"], 0)

    def test_loading_twice_is_refused(self):
        self.load()
        with self.assertRaises(HTTPException):
            self.load()

    def test_removing_without_loading_is_refused(self):
        with self.assertRaises(HTTPException):
            demo_api.demo_remove()

    def test_state_separates_demo_records_from_real_ones(self):
        self.add_real_records()
        self.load()
        state = demo_api.demo_state()
        self.assertTrue(state["loaded"])
        self.assertEqual(state["real_records"], 2)
        self.assertGreater(state["demo_records"], 100)

    def test_every_table_it_writes_to_is_known_to_the_registry(self):
        """登记了却删不掉的表，会让「已移除」变成一句谎话。"""
        self.load()
        result = demo_api.demo_remove()
        self.assertEqual(result["unknown_tables"], [])

    # ---------- 内容：得让分析页面真的有东西可看 ----------

    def test_it_writes_across_modules_not_just_the_ledger(self):
        """只有账本的示例演示不了一个 14 模块的平台。"""
        self.load()
        counts = self.counts()
        for table in ("fitness_sessions", "study_sessions", "recovery_checkins",
                      "nutrition_entries", "body_measurements", "habits"):
            self.assertGreater(counts[table], 0, f"{table} 没有示例数据")

    def test_expenses_are_categorised_not_all_other(self):
        """全归到「其他」的话，分类统计还是一根柱子，等于没演示。"""
        self.load()
        with main.db() as conn:
            categories = {
                row["category"] for row in
                conn.execute("SELECT DISTINCT category FROM transactions WHERE type = 'expense'")
            }
        self.assertGreater(len(categories), 4)

    def test_the_record_keeping_is_deliberately_incomplete(self):
        """每天都记满的示例会让「数据健康度」和「趋势」看起来毫无用处，
        而那两个功能存在的意义恰恰是应付不完整的记录。"""
        self.load(days=60)
        with main.db() as conn:
            recorded_days = conn.execute(
                "SELECT COUNT(DISTINCT occurred_on) FROM recovery_checkins").fetchone()[0]
        self.assertLess(recorded_days, 60, "示例数据记得太满了，不像真人")
        self.assertGreater(recorded_days, 20, "示例数据记得太少，分析页面还是空的")

    def test_the_same_seed_gives_the_same_demo(self):
        self.load()
        first = self.counts()
        demo_api.demo_remove()
        self.load()
        self.assertEqual(self.counts(), first)

    def test_day_range_is_bounded(self):
        for bad in (3, 400):
            with self.subTest(days=bad):
                with self.assertRaises(Exception):
                    self.load(days=bad)


class DemoConfigSafetyTests(unittest.TestCase):
    """规划参数和分类预算是**配置**，不是记录。

    删掉一条记录只是少了一条记录；删掉一项配置，是把用户的设置清零。
    所以这两张表要单独对待：只在空着时写，只在值没被改过时撤。
    """

    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_planning_is_seeded_so_the_headline_numbers_work(self):
        """没有生活费周期，「今日可用」永远是一条横杠，账本的招牌功能演示不出来。"""
        demo_api.demo_load(demo_api.DemoLoadIn(days=60))
        with main.db() as conn:
            planning = get_planning(conn)
            self.assertGreater(planning["settings"]["monthly_allowance_amount"], 0)
            self.assertTrue(planning["goals"])
            self.assertIsNotNone(get_today_overview(conn)["available_today"])
            self.assertGreater(get_subscription_overview(conn)["summary"]["count"], 0)

    def test_existing_planning_settings_are_not_overwritten(self):
        with main.db() as conn:
            save_planning_settings(conn, monthly_allowance_amount=888.0,
                                   allowance_day=12, monthly_spending_budget=777.0)
        demo_api.demo_load(demo_api.DemoLoadIn(days=30))
        with main.db() as conn:
            settings = get_planning(conn)["settings"]
        self.assertEqual(settings["monthly_allowance_amount"], 888.0)
        self.assertEqual(settings["allowance_day"], 12)

    def test_config_the_user_changed_is_kept_and_reported(self):
        """用户改过之后再撤示例，不能顺手把他的设置也清了。"""
        demo_api.demo_load(demo_api.DemoLoadIn(days=30))
        with main.db() as conn:
            save_category_budget(conn, category="food", amount=1234.0)

        result = demo_api.demo_remove()
        self.assertIn("category_budgets:food", result["kept_config"])
        with main.db() as conn:
            row = conn.execute(
                "SELECT amount FROM category_budgets WHERE category = 'food'").fetchone()
        self.assertEqual(row["amount"], 1234.0)

    def test_untouched_config_is_removed_cleanly(self):
        demo_api.demo_load(demo_api.DemoLoadIn(days=30))
        result = demo_api.demo_remove()
        self.assertEqual(result["kept_config"], [])
        with main.db() as conn:
            self.assertIsNone(
                conn.execute("SELECT 1 FROM planning_settings WHERE id = 1").fetchone())
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM category_budgets").fetchone()[0], 0)

    def test_a_text_keyed_table_round_trips_through_the_ledger(self):
        """category_budgets 的主键是文本，不是自增 id。
        登记册要是只认整数，这类表就会悄悄漏掉。"""
        demo_api.demo_load(demo_api.DemoLoadIn(days=30))
        with main.db() as conn:
            keys = [r["record_id"] for r in conn.execute(
                "SELECT record_id FROM demo_records WHERE table_name = 'category_budgets'")]
        self.assertTrue(keys)
        self.assertIn("food", keys)


class RetiredScriptTests(unittest.TestCase):
    def test_the_destructive_seed_script_is_gone(self):
        """backend/seed_demo.py 会 `DELETE FROM transactions`，
        而 README 把它写成了体验步骤。它不该再回来。"""
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "backend" / "seed_demo.py").exists())
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("seed_demo.py", readme)


if __name__ == "__main__":
    unittest.main()
