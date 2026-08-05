import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core


class LifePlatformPhase6Tests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_goal_and_milestone_state_reports_factual_progress(self):
        target = (date.today() + timedelta(days=7)).isoformat()
        with main.db() as conn:
            goal = main.create_life_goal(
                conn, title="完成课程项目", category="study", target_date=target,
                motivation="做出可以展示的作品",
            )
            milestone = main.create_goal_milestone(
                conn, goal_id=goal["id"], title="完成原型", target_date=target,
            )
            main.toggle_goal_milestone(conn, milestone["id"])
            state = main.get_life_goals_state(conn)

        self.assertEqual(state["summary"]["active"], 1)
        self.assertEqual(state["summary"]["milestones_done"], 1)
        self.assertEqual(state["goals"][0]["progress"], {"completed": 1, "total": 1})
        self.assertEqual(state["goals"][0]["status"], "active")

    def test_finishing_all_milestones_does_not_auto_complete_goal(self):
        with main.db() as conn:
            goal = main.create_life_goal(conn, title="跑完第一次 5 公里", category="health")
            milestone = main.create_goal_milestone(conn, goal_id=goal["id"], title="跑完 3 公里")
            main.toggle_goal_milestone(conn, milestone["id"])
            before = main.get_life_goals_state(conn)["goals"][0]
            completed = main.set_life_goal_status(conn, goal["id"], "completed")

        self.assertEqual(before["status"], "active")
        self.assertEqual(before["progress"], {"completed": 1, "total": 1})
        self.assertEqual(completed["status"], "completed")
        self.assertIsNotNone(completed["completed_at"])

    def test_pausing_and_reactivating_goal_is_manual(self):
        with main.db() as conn:
            goal = main.create_life_goal(conn, title="学习摄影")
            paused = main.set_life_goal_status(conn, goal["id"], "paused")
            active = main.set_life_goal_status(conn, goal["id"], "active")

        self.assertEqual(paused["status"], "paused")
        self.assertEqual(active["status"], "active")
        self.assertIsNone(active["completed_at"])

    def test_goal_dates_appear_as_calendar_arrangements(self):
        target = date.today().isoformat()
        with main.db() as conn:
            goal = main.create_life_goal(
                conn, title="完成作品集", category="study", target_date=target,
            )
            main.create_goal_milestone(
                conn, goal_id=goal["id"], title="整理三个项目", target_date=target,
            )
            calendar = main.get_life_calendar(conn, selected_date=target)

        goal_items = [
            item for item in calendar["selected"]["arrangements"] if item["module"] == "goals"
        ]
        self.assertEqual(calendar["summary"]["arrangement_count"], 2)
        self.assertEqual(len(goal_items), 2)
        self.assertTrue(all(item["kind"] == "arrangement" for item in goal_items))

    def test_deleting_goal_cascades_its_milestones(self):
        with main.db() as conn:
            goal = main.create_life_goal(conn, title="整理个人档案")
            main.create_goal_milestone(conn, goal_id=goal["id"], title="整理照片")

        result = main.delete_life_goal(goal["id"])

        self.assertEqual(result["goals"]["goals"], [])
        with main.db() as conn:
            milestone_count = conn.execute("SELECT COUNT(*) FROM goal_milestones").fetchone()[0]
        self.assertEqual(milestone_count, 0)

    def test_legacy_snapshot_without_goal_tables_restores(self):
        with main.db() as conn:
            snapshot = main.build_snapshot(conn)
        snapshot["tables"].pop("life_goals")
        snapshot["tables"].pop("goal_milestones")

        result = main.restore_backup(
            main.RestoreSnapshotIn(snapshot=snapshot, confirmation="RESTORE")
        )

        self.assertTrue(result["restored"])
        with main.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM life_goals").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM goal_milestones").fetchone()[0], 0)

    def test_empty_goal_title_is_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                main.create_life_goal(conn, title="   ")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM life_goals").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
