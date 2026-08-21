"""生活轨迹跨模块只读视图。"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core


class LifeTimelineTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def populate(self):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        main.add_transaction(main.TransactionIn(
            occurred_on=today, type="expense", category="food", amount=18, note="早餐",
        ))
        with main.db() as conn:
            main.record_workout(conn, occurred_on=yesterday, activity="cardio", duration_minutes=30, intensity=5)
            main.record_study_session(conn, occurred_on=today, subject="高等数学", duration_minutes=45, focus=4)
            main.create_personal_task(conn, title="交课程作业", due_on=today, category="study")
            main.save_daily_reflection(conn, occurred_on=today, highlight="完成课程作业")
            main.create_life_goal(conn, title="完成本学期课程", category="study", target_date=today)
        return today, yesterday

    def test_timeline_normalizes_and_orders_cross_module_items(self):
        today, yesterday = self.populate()
        with main.db() as conn:
            result = main.get_life_timeline(conn)

        self.assertEqual(result["summary"]["total"], 6)
        self.assertEqual(result["results"][0]["date"], today)
        self.assertEqual(result["results"][-1]["date"], yesterday)
        self.assertEqual(
            {item["module"] for item in result["results"]},
            {"finance", "fitness", "study", "rhythm", "reflection", "goals"},
        )
        required = {"module", "kind", "id", "date", "title", "detail"}
        self.assertTrue(all(required <= set(item) for item in result["results"]))

    def test_filters_and_pagination_are_factual(self):
        self.populate()
        with main.db() as conn:
            facts = main.get_life_timeline(conn, kind="fact")
            study = main.get_life_timeline(conn, module="study")
            first = main.get_life_timeline(conn, limit=2)
            second = main.get_life_timeline(conn, offset=first["next_offset"], limit=2)

        self.assertEqual(facts["summary"]["total"], 4)
        self.assertEqual(study["summary"]["total"], 1)
        self.assertTrue(first["has_more"])
        first_ids = {(item["module"], item["id"]) for item in first["results"]}
        second_ids = {(item["module"], item["id"]) for item in second["results"]}
        self.assertFalse(first_ids & second_ids)

    def test_date_filter_keeps_only_selected_day(self):
        today, _ = self.populate()
        with main.db() as conn:
            result = main.get_life_timeline(conn, date_from=today, date_to=today)
        self.assertEqual(result["summary"]["total"], 5)
        self.assertTrue(all(item["date"] == today for item in result["results"]))

    def test_recurring_bill_keeps_its_arrangement_meaning(self):
        self.populate()
        with main.db() as conn:
            account_id = conn.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()[0]
            conn.execute(
                """INSERT INTO recurring_bills
                   (name, amount, day_of_month, category, account_id, note, is_active, created_at, cycle, anchor_month)
                   VALUES (?, ?, ?, ?, ?, '', 1, ?, ?, ?)""",
                ("云盘", 120, 15, "digital", account_id, "2026-08-21T10:00:00", "yearly", 8),
            )
            result = main.get_life_timeline(conn, module="finance")

        bill = next(item for item in result["results"] if item["title"] == "云盘")
        self.assertEqual(bill["kind"], "arrangement")
        self.assertIn("每年 8 月 15 日", bill["detail"])

    def test_invalid_filters_are_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                main.get_life_timeline(conn, module="calendar")
            with self.assertRaises(HTTPException):
                main.get_life_timeline(conn, kind="score")
            with self.assertRaises(HTTPException):
                main.get_life_timeline(conn, date_from="2026-09-02", date_to="2026-09-01")

    def test_timeline_is_read_only(self):
        self.populate()
        with main.db() as conn:
            tables = ("transactions", "fitness_sessions", "study_sessions", "personal_tasks", "daily_reflections", "life_goals")
            before = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
            main.get_life_timeline(conn, module="study", kind="fact")
            after = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
