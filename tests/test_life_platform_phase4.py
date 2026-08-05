import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core


class LifePlatformPhase4Tests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_reflection_updates_same_day_instead_of_duplicating(self):
        today = date.today().isoformat()
        with main.db() as conn:
            first = main.save_daily_reflection(conn, occurred_on=today, highlight="完成作业")
            updated = main.save_daily_reflection(
                conn, occurred_on=today, highlight="完成作业", gratitude="谢谢室友"
            )
            count = conn.execute("SELECT COUNT(*) FROM daily_reflections").fetchone()[0]
            state = main.get_reflection_state(conn, today)

        self.assertEqual(first["id"], updated["id"])
        self.assertEqual(count, 1)
        self.assertEqual(state["selected"]["gratitude"], "谢谢室友")

    def test_empty_reflection_is_rejected_without_writing(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                main.save_daily_reflection(conn, occurred_on=date.today().isoformat())
            count = conn.execute("SELECT COUNT(*) FROM daily_reflections").fetchone()[0]

        self.assertEqual(count, 0)

    def test_weekly_snapshot_aggregates_cross_module_facts(self):
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        day = monday.isoformat()
        main.add_transaction(main.TransactionIn(
            occurred_on=day, type="income", source="family_support", amount=500
        ))
        main.add_transaction(main.TransactionIn(
            occurred_on=day, type="expense", category="food", amount=80
        ))
        with main.db() as conn:
            main.record_workout(
                conn, occurred_on=day, activity="cardio", duration_minutes=35, intensity=5
            )
            main.record_meal(
                conn, occurred_on=day, meal_type="lunch", name="食堂午餐",
                calories=600, water_ml=500
            )
            main.save_recovery_checkin(
                conn, occurred_on=day, sleep_hours=7.5, energy=4, mood=3
            )
            main.record_study_session(
                conn, occurred_on=day, subject="高等数学", duration_minutes=45, focus=4
            )
            task = main.create_personal_task(conn, title="交作业", due_on=day)
            main.toggle_personal_task(conn, task["id"])
            habit = main.create_habit(conn, name="阅读", category="study")
            main.toggle_habit_checkin(conn, habit["id"], day)
            main.save_daily_reflection(conn, occurred_on=day, highlight="按时完成")
            snapshot = main.get_weekly_snapshot(conn, monday)

        self.assertEqual(snapshot["finance"]["income"], 500)
        self.assertEqual(snapshot["finance"]["expense"], 80)
        self.assertEqual(snapshot["fitness"], {"count": 1, "minutes": 35})
        self.assertEqual(snapshot["nutrition"]["calories_known"], 1)
        self.assertEqual(snapshot["nutrition"]["water_ml"], 500)
        self.assertEqual(snapshot["recovery"]["sleep_hours"], 7.5)
        self.assertEqual(snapshot["study"]["minutes"], 45)
        self.assertEqual(snapshot["rhythm"]["tasks_done"], 1)
        self.assertEqual(snapshot["rhythm"]["habit_checkins"], 1)
        self.assertEqual(snapshot["reflection_count"], 1)

    def test_life_overview_prioritizes_missing_reflection_action(self):
        with main.db() as conn:
            before = main.get_life_overview(conn)
            main.save_daily_reflection(
                conn, occurred_on=date.today().isoformat(), note="今天平稳"
            )
            after = main.get_life_overview(conn)

        before_modules = [item["module"] for item in before["actions"]]
        after_modules = [item["module"] for item in after["actions"]]
        self.assertIn("reflection", before_modules)
        self.assertNotIn("reflection", after_modules)
        self.assertEqual(after["reflection"]["selected"]["note"], "今天平稳")

    def test_empty_week_preserves_unknown_averages(self):
        with main.db() as conn:
            snapshot = main.get_weekly_snapshot(conn, date.today())

        self.assertIsNone(snapshot["recovery"]["sleep_hours"])
        self.assertIsNone(snapshot["recovery"]["energy"])
        self.assertIsNone(snapshot["study"]["avg_focus"])

    def test_legacy_snapshot_without_reflections_restores(self):
        with main.db() as conn:
            snapshot = main.build_snapshot(conn)
        snapshot["tables"].pop("daily_reflections")

        result = main.restore_backup(
            main.RestoreSnapshotIn(snapshot=snapshot, confirmation="RESTORE")
        )

        self.assertTrue(result["restored"])
        with main.db() as conn:
            count = conn.execute("SELECT COUNT(*) FROM daily_reflections").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
