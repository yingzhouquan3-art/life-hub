import tempfile
import unittest
from datetime import date
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core


class LifePlatformPhase2Tests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_recovery_checkin_updates_same_day_instead_of_duplicating(self):
        today = date.today().isoformat()
        with main.db() as conn:
            first = main.save_recovery_checkin(
                conn, occurred_on=today, sleep_hours=7.5, sleep_quality=4, energy=3
            )
            updated = main.save_recovery_checkin(
                conn, occurred_on=today, sleep_hours=8, sleep_quality=5, energy=4, mood=4
            )
            state = main.get_recovery_state(conn)
            count = conn.execute("SELECT COUNT(*) FROM recovery_checkins").fetchone()[0]

        self.assertEqual(first["id"], updated["id"])
        self.assertEqual(count, 1)
        self.assertEqual(state["today"]["sleep_hours"], 8)
        self.assertEqual(state["week"]["sleep_hours"], 8)

    def test_empty_recovery_checkin_is_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                main.save_recovery_checkin(conn, occurred_on=date.today().isoformat())
            count = conn.execute("SELECT COUNT(*) FROM recovery_checkins").fetchone()[0]
        self.assertEqual(count, 0)

    def test_study_session_is_summarized_for_today_and_week(self):
        with main.db() as conn:
            session = main.record_study_session(
                conn,
                occurred_on=date.today().isoformat(),
                subject="高等数学",
                duration_minutes=45,
                focus=4,
                note="复习积分",
            )
            state = main.get_study_state(conn)
            overview = main.get_life_overview(conn)

        self.assertEqual(session["subject"], "高等数学")
        self.assertEqual(state["today"]["minutes"], 45)
        self.assertEqual(state["week"]["avg_focus"], 4)
        self.assertEqual(overview["study"]["today"]["count"], 1)
        self.assertNotIn("study", [item["module"] for item in overview["actions"]])

    def test_legacy_snapshot_without_phase2_tables_restores(self):
        with main.db() as conn:
            snapshot = main.build_snapshot(conn)
        snapshot["tables"].pop("recovery_checkins")
        snapshot["tables"].pop("study_sessions")

        result = main.restore_backup(main.RestoreSnapshotIn(snapshot=snapshot, confirmation="RESTORE"))

        self.assertTrue(result["restored"])
        with main.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM recovery_checkins").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
