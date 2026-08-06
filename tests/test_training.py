"""训练记录：动作库、组数与个人纪录。

纪录是从已有记录里挑出来的最好一次，不是能力评价，
所以这里重点守住「怎么挑」和「挑不出来时说什么」。
"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core
from backend.modules import fitness


class TrainingTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def a_session(self, conn, offset=0):
        day = (date.today() + timedelta(days=offset)).isoformat()
        return fitness.record_workout(
            conn, occurred_on=day, activity="strength", duration_minutes=60, intensity=7,
        )

    def an_exercise(self, conn, name="卧推"):
        row = conn.execute("SELECT * FROM exercises WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else fitness.create_exercise(conn, name=name)

    # ---------- 动作库 ----------

    def test_default_exercises_are_seeded(self):
        """空动作库会让这个功能一上来就没法用。"""
        with main.db() as conn:
            exercises = fitness.list_exercises(conn)
        self.assertTrue(exercises)
        self.assertIn("深蹲", [item["name"] for item in exercises])

    def test_seeding_does_not_duplicate_on_second_init(self):
        with main.db() as conn:
            before = len(fitness.list_exercises(conn))
        main.init_db()
        main.init_db()
        with main.db() as conn:
            self.assertEqual(len(fitness.list_exercises(conn)), before)

    def test_duplicate_name_is_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                fitness.create_exercise(conn, name="深蹲")

    def test_recreating_an_archived_exercise_reactivates_it(self):
        """否则纪录会被拆成同名的两个动作。"""
        with main.db() as conn:
            created = fitness.create_exercise(conn, name="保加利亚分腿蹲")
            fitness.archive_exercise(conn, created["id"])
            again = fitness.create_exercise(conn, name="保加利亚分腿蹲")
        self.assertEqual(again["id"], created["id"])
        self.assertEqual(again["is_active"], 1)

    def test_archiving_keeps_existing_sets(self):
        with main.db() as conn:
            session = self.a_session(conn)
            exercise = self.an_exercise(conn)
            fitness.record_set(conn, session_id=session["id"], exercise_id=exercise["id"],
                               reps=5, weight_kg=60)
            fitness.archive_exercise(conn, exercise["id"])
            records = fitness.get_exercise_records(conn, exercise["id"])
        self.assertEqual(records["set_count"], 1)

    # ---------- 组数 ----------

    def test_set_numbers_increment_within_a_session(self):
        with main.db() as conn:
            session = self.a_session(conn)
            exercise = self.an_exercise(conn)
            for _ in range(3):
                fitness.record_set(conn, session_id=session["id"],
                                   exercise_id=exercise["id"], reps=5, weight_kg=60)
            sets = fitness.get_session_sets(conn, session["id"])
        self.assertEqual([item["set_number"] for item in sets], [1, 2, 3])

    def test_set_numbers_restart_for_a_new_session(self):
        with main.db() as conn:
            exercise = self.an_exercise(conn)
            first = self.a_session(conn, -1)
            fitness.record_set(conn, session_id=first["id"], exercise_id=exercise["id"], reps=5, weight_kg=60)
            second = self.a_session(conn, 0)
            created = fitness.record_set(conn, session_id=second["id"],
                                         exercise_id=exercise["id"], reps=5, weight_kg=60)
        self.assertEqual(created["set_number"], 1)

    def test_empty_set_is_rejected(self):
        with main.db() as conn:
            session = self.a_session(conn)
            exercise = self.an_exercise(conn)
            with self.assertRaises(HTTPException):
                fitness.record_set(conn, session_id=session["id"], exercise_id=exercise["id"])

    def test_set_requires_an_existing_session_and_exercise(self):
        with main.db() as conn:
            session = self.a_session(conn)
            exercise = self.an_exercise(conn)
            with self.assertRaises(HTTPException):
                fitness.record_set(conn, session_id=999, exercise_id=exercise["id"], reps=5)
            with self.assertRaises(HTTPException):
                fitness.record_set(conn, session_id=session["id"], exercise_id=999, reps=5)

    def test_deleting_a_session_takes_its_sets_with_it(self):
        with main.db() as conn:
            session = self.a_session(conn)
            exercise = self.an_exercise(conn)
            fitness.record_set(conn, session_id=session["id"], exercise_id=exercise["id"],
                               reps=5, weight_kg=60)
            conn.execute("DELETE FROM fitness_sessions WHERE id = ?", (session["id"],))
            remaining = conn.execute("SELECT COUNT(*) FROM workout_sets").fetchone()[0]
        self.assertEqual(remaining, 0)

    # ---------- 容量 ----------

    def test_volume_only_counts_sets_with_both_reps_and_weight(self):
        with main.db() as conn:
            session = self.a_session(conn)
            exercise = self.an_exercise(conn)
            fitness.record_set(conn, session_id=session["id"], exercise_id=exercise["id"], reps=5, weight_kg=60)
            fitness.record_set(conn, session_id=session["id"], exercise_id=exercise["id"], reps=5, weight_kg=60)
            fitness.record_set(conn, session_id=session["id"], exercise_id=exercise["id"], reps=10)
            volume = fitness.session_volume(conn, session["id"])
        self.assertEqual(volume, 600.0, "只填了次数的那组没有重量，不能算进容量")

    # ---------- 个人纪录 ----------

    def test_heaviest_prefers_more_reps_when_weight_ties(self):
        with main.db() as conn:
            session = self.a_session(conn)
            exercise = self.an_exercise(conn)
            fitness.record_set(conn, session_id=session["id"], exercise_id=exercise["id"], reps=3, weight_kg=80)
            fitness.record_set(conn, session_id=session["id"], exercise_id=exercise["id"], reps=5, weight_kg=80)
            records = fitness.get_exercise_records(conn, exercise["id"])
        self.assertEqual(records["heaviest"]["weight_kg"], 80)
        self.assertEqual(records["heaviest"]["reps"], 5)

    def test_estimated_one_rep_max_can_beat_the_heaviest_set(self):
        """5×80 的估算 1RM 高于 1×90，这正是这个指标存在的意义。"""
        with main.db() as conn:
            session = self.a_session(conn)
            exercise = self.an_exercise(conn)
            fitness.record_set(conn, session_id=session["id"], exercise_id=exercise["id"], reps=1, weight_kg=90)
            fitness.record_set(conn, session_id=session["id"], exercise_id=exercise["id"], reps=5, weight_kg=80)
            records = fitness.get_exercise_records(conn, exercise["id"])
        self.assertEqual(records["heaviest"]["weight_kg"], 90)
        self.assertEqual(records["estimated_one_rep_max"]["reps"], 5)
        self.assertGreater(records["estimated_one_rep_max"]["value"], 90)

    def test_records_are_none_when_nothing_was_logged(self):
        with main.db() as conn:
            exercise = self.an_exercise(conn)
            records = fitness.get_exercise_records(conn, exercise["id"])
        self.assertIsNone(records["heaviest"])
        self.assertIsNone(records["estimated_one_rep_max"])
        self.assertEqual(records["set_count"], 0)

    def test_records_state_the_limit_of_what_they_mean(self):
        with main.db() as conn:
            exercise = self.an_exercise(conn)
            records = fitness.get_exercise_records(conn, exercise["id"])
        self.assertIn("不代表能力上限", records["note"])

    def test_cardio_records_track_distance(self):
        with main.db() as conn:
            session = self.a_session(conn)
            running = self.an_exercise(conn, "跑步")
            fitness.record_set(conn, session_id=session["id"], exercise_id=running["id"],
                               distance_km=5.0, duration_seconds=1800)
            fitness.record_set(conn, session_id=session["id"], exercise_id=running["id"],
                               distance_km=8.0, duration_seconds=3000)
            records = fitness.get_exercise_records(conn, running["id"])
        self.assertEqual(records["farthest"]["distance_km"], 8.0)
        self.assertIsNone(records["heaviest"])

    def test_missing_exercise_is_an_error(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                fitness.get_exercise_records(conn, 999)

    # ---------- 汇总 ----------

    def test_state_only_reports_records_for_exercises_actually_used(self):
        with main.db() as conn:
            session = self.a_session(conn)
            exercise = self.an_exercise(conn)
            fitness.record_set(conn, session_id=session["id"], exercise_id=exercise["id"], reps=5, weight_kg=60)
            state = fitness.get_training_state(conn)
        self.assertEqual(len(state["records"]), 1)
        self.assertEqual(state["records"][0]["exercise"]["name"], "卧推")
        self.assertEqual(state["week"]["volume"], 300.0)
        self.assertEqual(state["recent_sessions"][0]["volume"], 300.0)


if __name__ == "__main__":
    unittest.main()
