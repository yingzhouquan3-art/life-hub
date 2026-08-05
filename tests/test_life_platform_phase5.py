import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core


class LifePlatformPhase5Tests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_empty_calendar_uses_current_month_without_inventing_activity(self):
        with main.db() as conn:
            calendar = main.get_life_calendar(conn)

        self.assertEqual(calendar["month"], date.today().strftime("%Y-%m"))
        self.assertEqual(calendar["selected_date"], date.today().isoformat())
        self.assertEqual(calendar["summary"], {
            "active_days": 0, "fact_count": 0, "arrangement_count": 0,
        })
        self.assertEqual(calendar["selected"]["facts"], [])
        self.assertEqual(calendar["selected"]["arrangements"], [])

    def test_calendar_aggregates_facts_and_arrangements_without_mixing_them(self):
        today = date.today()
        day = today.isoformat()
        main.add_transaction(main.TransactionIn(
            occurred_on=day, type="expense", category="food", amount=18, note="午饭"
        ))
        now = datetime.now().isoformat()
        with main.db() as conn:
            main.record_workout(
                conn, occurred_on=day, activity="cardio", duration_minutes=30, intensity=5
            )
            main.record_meal(conn, occurred_on=day, meal_type="lunch", name="食堂午餐")
            main.save_recovery_checkin(conn, occurred_on=day, sleep_hours=7.5, energy=4)
            main.record_study_session(
                conn, occurred_on=day, subject="英语", duration_minutes=40, focus=4
            )
            task = main.create_personal_task(conn, title="交作业", due_on=day)
            habit = main.create_habit(conn, name="阅读", category="study")
            main.toggle_habit_checkin(conn, habit["id"], day)
            main.save_daily_reflection(conn, occurred_on=day, highlight="完成任务")
            conn.execute(
                """INSERT INTO recurring_bills
                   (name, amount, day_of_month, category, account_id, note, is_active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                ("校园网", 20, today.day, "digital", 1, "", now),
            )
            calendar = main.get_life_calendar(conn, today.strftime("%Y-%m"), day)

        selected_day = next(item for item in calendar["days"] if item["date"] == day)
        fact_modules = {item["module"] for item in calendar["selected"]["facts"]}
        arrangement_modules = {item["module"] for item in calendar["selected"]["arrangements"]}
        self.assertEqual(selected_day["fact_count"], 7)
        self.assertEqual(selected_day["arrangement_count"], 2)
        self.assertEqual(fact_modules, {
            "finance", "fitness", "nutrition", "recovery", "study", "rhythm", "reflection",
        })
        self.assertEqual(arrangement_modules, {"finance", "rhythm"})
        self.assertEqual(calendar["summary"]["active_days"], 1)

    def test_completed_task_remains_an_arrangement_with_completed_status(self):
        today = date.today().isoformat()
        with main.db() as conn:
            task = main.create_personal_task(conn, title="提交报告", due_on=today)
            main.toggle_personal_task(conn, task["id"])
            calendar = main.get_life_calendar(conn, selected_date=today)

        self.assertEqual(calendar["summary"]["fact_count"], 0)
        self.assertEqual(calendar["summary"]["arrangement_count"], 1)
        self.assertEqual(calendar["selected"]["arrangements"][0]["status"], "done")

    def test_calendar_rejects_invalid_or_mismatched_dates(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                main.get_life_calendar(conn, "2026-13")
            with self.assertRaises(HTTPException):
                main.get_life_calendar(conn, "2026-08", "2026-09-01")

    def test_calendar_projection_does_not_write_source_tables(self):
        with main.db() as conn:
            before = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "transactions", "fitness_sessions", "nutrition_entries", "recovery_checkins",
                    "study_sessions", "personal_tasks", "habit_checkins", "daily_reflections",
                )
            }
            main.get_life_calendar(conn)
            after = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in before
            }

        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
