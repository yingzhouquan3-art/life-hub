import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core


class LifePlatformPhase7Tests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def populate_project_records(self):
        today = date.today().isoformat()
        with main.db() as conn:
            main.record_study_session(
                conn, occurred_on=today, subject="课程项目", duration_minutes=45, focus=4,
            )
            main.create_personal_task(conn, title="提交课程项目", due_on=today, category="study")
            main.save_daily_reflection(conn, occurred_on=today, highlight="课程项目完成了原型")
            goal = main.create_life_goal(
                conn, title="完成课程项目", category="study", target_date=today,
            )
            main.create_goal_milestone(
                conn, goal_id=goal["id"], title="课程项目答辩", target_date=today,
            )
        return today

    def test_search_returns_normalized_results_across_modules(self):
        self.populate_project_records()
        with main.db() as conn:
            result = main.search_life(conn, query="课程项目")

        self.assertEqual(result["summary"]["total"], 5)
        self.assertEqual(
            {item["module"] for item in result["results"]},
            {"study", "rhythm", "reflection", "goals"},
        )
        for item in result["results"]:
            self.assertIn(item["kind"], {"fact", "arrangement", "reference"})
            self.assertTrue(item["title"])
            self.assertTrue(item["module"])

    def test_module_filter_keeps_only_requested_source(self):
        self.populate_project_records()
        with main.db() as conn:
            result = main.search_life(conn, query="课程项目", module="study")

        self.assertEqual(result["summary"]["total"], 1)
        self.assertEqual(result["results"][0]["module"], "study")

    def test_date_filter_excludes_records_outside_range(self):
        today = self.populate_project_records()
        tomorrow = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
        with main.db() as conn:
            result = main.search_life(conn, query="课程项目", date_from=tomorrow)

        self.assertEqual(result["summary"]["total"], 0)

    def test_search_matches_display_labels_not_only_raw_codes(self):
        today = date.today().isoformat()
        main.add_transaction(main.TransactionIn(
            occurred_on=today, type="expense", category="food", amount=18,
        ))
        with main.db() as conn:
            result = main.search_life(conn, query="餐饮")

        self.assertEqual(result["summary"]["total"], 1)
        self.assertEqual(result["results"][0]["module"], "finance")
        self.assertIn("餐饮", result["results"][0]["detail"])

    def test_search_limit_reports_truncation(self):
        today = date.today().isoformat()
        with main.db() as conn:
            for index in range(3):
                main.record_study_session(
                    conn, occurred_on=today, subject=f"英语阅读 {index}", duration_minutes=20, focus=3,
                )
            result = main.search_life(conn, query="英语阅读", limit=2)

        self.assertEqual(result["summary"]["total"], 3)
        self.assertEqual(len(result["results"]), 2)
        self.assertTrue(result["truncated"])

    def test_empty_or_invalid_search_is_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                main.search_life(conn, query="   ")
            with self.assertRaises(HTTPException):
                main.search_life(conn, query="项目", module="calendar")
            with self.assertRaises(HTTPException):
                main.search_life(conn, query="项目", date_from="2026-09-02", date_to="2026-09-01")

    def test_search_is_read_only(self):
        self.populate_project_records()
        with main.db() as conn:
            before = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("study_sessions", "personal_tasks", "daily_reflections", "life_goals", "goal_milestones")
            }
            main.search_life(conn, query="课程项目")
            after = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in before
            }

        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
