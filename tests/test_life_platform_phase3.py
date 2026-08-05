import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from backend import main
from backend.core import db as db_core


class LifePlatformPhase3Tests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_task_toggle_updates_today_summary(self):
        today = date.today().isoformat()
        with main.db() as conn:
            task = main.create_personal_task(
                conn, title="交课程作业", due_on=today, priority="high", category="study"
            )
            before = main.get_rhythm_state(conn)
            toggled = main.toggle_personal_task(conn, task["id"])
            after = main.get_rhythm_state(conn)

        self.assertEqual(before["task_summary"]["today_pending"], 1)
        self.assertEqual(toggled["status"], "done")
        self.assertEqual(after["task_summary"]["today_done"], 1)
        self.assertEqual(after["task_summary"]["today_pending"], 0)

    def test_overdue_task_appears_first_in_life_actions(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with main.db() as conn:
            main.create_personal_task(conn, title="整理材料", due_on=yesterday)
            overview = main.get_life_overview(conn)

        self.assertEqual(overview["rhythm"]["task_summary"]["overdue"], 1)
        self.assertEqual(overview["actions"][0]["module"], "rhythm")
        self.assertIn("逾期", overview["actions"][0]["title"])

    def test_habit_toggle_and_streak_end_today_or_yesterday(self):
        today = date.today()
        yesterday = today - timedelta(days=1)
        with main.db() as conn:
            habit = main.create_habit(conn, name="阅读", category="study")
            main.toggle_habit_checkin(conn, habit["id"], yesterday.isoformat())
            main.toggle_habit_checkin(conn, habit["id"], today.isoformat())
            checked = main.get_rhythm_state(conn)
            main.toggle_habit_checkin(conn, habit["id"], today.isoformat())
            unchecked = main.get_rhythm_state(conn)

        self.assertTrue(checked["habits"][0]["checked_today"])
        self.assertEqual(checked["habits"][0]["streak"], 2)
        self.assertFalse(unchecked["habits"][0]["checked_today"])
        self.assertEqual(unchecked["habits"][0]["streak"], 1)

    def test_archiving_habit_preserves_checkin_history(self):
        with main.db() as conn:
            habit = main.create_habit(conn, name="拉伸", category="health")
            main.toggle_habit_checkin(conn, habit["id"], date.today().isoformat())

        response = main.archive_habit(habit["id"])

        self.assertEqual(response["rhythm"]["habit_summary"]["total"], 0)
        with main.db() as conn:
            archived = conn.execute("SELECT is_active FROM habits WHERE id = ?", (habit["id"],)).fetchone()[0]
            checkins = conn.execute("SELECT COUNT(*) FROM habit_checkins WHERE habit_id = ?", (habit["id"],)).fetchone()[0]
        self.assertEqual(archived, 0)
        self.assertEqual(checkins, 1)

    def test_legacy_snapshot_without_phase3_tables_restores(self):
        with main.db() as conn:
            snapshot = main.build_snapshot(conn)
        for table in ("personal_tasks", "habits", "habit_checkins"):
            snapshot["tables"].pop(table)

        result = main.restore_backup(main.RestoreSnapshotIn(snapshot=snapshot, confirmation="RESTORE"))

        self.assertTrue(result["restored"])
        with main.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM personal_tasks").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM habits").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM habit_checkins").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
