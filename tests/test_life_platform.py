import tempfile
import unittest
from datetime import date
from pathlib import Path

from backend import main
from backend.core import db as db_core


class LifePlatformTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_workout_is_recorded_and_summarized(self):
        with main.db() as conn:
            session = main.record_workout(
                conn,
                occurred_on=date.today().isoformat(),
                activity="cardio",
                duration_minutes=35,
                intensity=6,
                note="操场慢跑",
            )
            state = main.get_fitness_state(conn)

        self.assertEqual(session["activity"], "cardio")
        self.assertEqual(state["today"]["count"], 1)
        self.assertEqual(state["today"]["minutes"], 35)
        self.assertEqual(state["week"]["minutes"], 35)

    def test_unknown_nutrition_values_remain_distinguishable(self):
        with main.db() as conn:
            main.record_meal(
                conn,
                occurred_on=date.today().isoformat(),
                meal_type="lunch",
                name="食堂午餐",
            )
            state = main.get_nutrition_state(conn)

        self.assertEqual(state["today"]["count"], 1)
        self.assertEqual(state["today"]["calories"], 0)
        self.assertEqual(state["today"]["calories_known"], 0)

    def test_life_overview_reads_module_summaries(self):
        with main.db() as conn:
            main.record_workout(
                conn,
                occurred_on=date.today().isoformat(),
                activity="mobility",
                duration_minutes=10,
                intensity=3,
            )
            main.record_meal(
                conn,
                occurred_on=date.today().isoformat(),
                meal_type="breakfast",
                name="早餐",
                protein_g=18,
                water_ml=300,
            )
            overview = main.get_life_overview(conn)

        self.assertEqual(overview["fitness"]["today"]["minutes"], 10)
        self.assertEqual(overview["nutrition"]["today"]["count"], 1)
        self.assertEqual(overview["nutrition"]["today"]["protein_g"], 18)
        self.assertEqual(overview["completed_signals"], 2)

    def test_finance_only_legacy_snapshot_restores_with_empty_life_tables(self):
        with main.db() as conn:
            snapshot = main.build_snapshot(conn)
        snapshot["tables"].pop("fitness_sessions")
        snapshot["tables"].pop("nutrition_entries")

        result = main.restore_backup(main.RestoreSnapshotIn(snapshot=snapshot, confirmation="RESTORE"))

        self.assertTrue(result["restored"])
        with main.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM fitness_sessions").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM nutrition_entries").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
