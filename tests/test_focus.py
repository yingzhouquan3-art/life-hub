"""番茄钟。

两条最要紧的：

- 倒计时的真相在数据库里的结束时刻，不在浏览器的计数器里——
  刷新页面、换设备、电脑睡一觉，剩余时间都得是对的。
- **一个没跑完的番茄不是一整段学习记录。** 提前停下时按实际时长记，
  否则学习时长会凭空变多。
"""
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core
from backend.modules import study


class FocusSessionTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def start(self, **kwargs):
        with main.db() as conn:
            return study.start_focus_session(conn, **kwargs)

    def backdate(self, session_id, minutes_ago, planned=25):
        """把开始时间往前推，模拟已经跑了一段时间。"""
        started = datetime.now() - timedelta(minutes=minutes_ago)
        with main.db() as conn:
            conn.execute(
                "UPDATE focus_sessions SET started_at = ?, ends_at = ? WHERE id = ?",
                (started.isoformat(),
                 (started + timedelta(minutes=planned)).isoformat(), session_id),
            )

    # ---------- 倒计时的真相在后端 ----------

    def test_remaining_time_is_computed_from_the_end_moment(self):
        session = self.start(minutes=25)
        self.assertGreater(session["remaining_seconds"], 24 * 60)
        self.assertLessEqual(session["remaining_seconds"], 25 * 60)
        self.assertFalse(session["finished"])

    def test_remaining_time_survives_a_reload(self):
        """重新读一次仍然对——因为它是算出来的，不是存的计数器。"""
        session = self.start(minutes=30)
        self.backdate(session["id"], minutes_ago=10, planned=30)
        with main.db() as conn:
            again = study.get_focus_session(conn, session["id"])
        self.assertAlmostEqual(again["remaining_seconds"] / 60, 20, delta=1)

    def test_expired_session_reports_finished(self):
        session = self.start(minutes=25)
        self.backdate(session["id"], minutes_ago=30)
        with main.db() as conn:
            expired = study.get_focus_session(conn, session["id"])
        self.assertTrue(expired["finished"])
        self.assertEqual(expired["remaining_seconds"], 0)

    # ---------- 一次只能有一个 ----------

    def test_only_one_can_run_at_a_time(self):
        self.start()
        with self.assertRaises(HTTPException):
            self.start()

    def test_a_new_one_can_start_after_finishing(self):
        first = self.start()
        with main.db() as conn:
            study.finish_focus_session(conn, first["id"])
        self.assertIsNotNone(self.start())

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(HTTPException):
            self.start(kind="nap")
        with self.assertRaises(HTTPException):
            self.start(minutes=0)
        with self.assertRaises(HTTPException):
            self.start(minutes=999)

    # ---------- 没跑完不算一整段 ----------

    def test_stopping_early_records_actual_minutes_not_planned(self):
        """跑了 10 分钟就停，不能记成 25 分钟。"""
        session = self.start(minutes=25, subject="高等数学")
        self.backdate(session["id"], minutes_ago=10)
        with main.db() as conn:
            result = study.finish_focus_session(conn, session["id"], focus=4)
            recorded = conn.execute(
                "SELECT * FROM study_sessions WHERE id = ?",
                (result["recorded_study_session"],),
            ).fetchone()
        self.assertEqual(result["status"], "stopped")
        self.assertAlmostEqual(result["actual_minutes"], 10, delta=1)
        self.assertAlmostEqual(recorded["duration_minutes"], 10, delta=1)
        self.assertEqual(recorded["subject"], "高等数学")

    def test_completed_session_records_the_planned_length(self):
        """到点之后才来点结束，不该把发呆那几分钟也算成学习。"""
        session = self.start(minutes=25)
        self.backdate(session["id"], minutes_ago=40)
        with main.db() as conn:
            result = study.finish_focus_session(conn, session["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["actual_minutes"], 25)

    def test_sub_minute_session_records_nothing(self):
        """刚开就停不构成一段学习事实。"""
        session = self.start()
        with main.db() as conn:
            result = study.finish_focus_session(conn, session["id"])
            count = conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0]
        self.assertIsNone(result["recorded_study_session"])
        self.assertEqual(count, 0)

    def test_breaks_never_become_study_records(self):
        session = self.start(kind="short_break", minutes=5)
        self.backdate(session["id"], minutes_ago=5, planned=5)
        with main.db() as conn:
            result = study.finish_focus_session(conn, session["id"])
            count = conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0]
        self.assertIsNone(result["recorded_study_session"])
        self.assertEqual(count, 0)

    def test_user_can_decline_to_record(self):
        session = self.start(minutes=25)
        self.backdate(session["id"], minutes_ago=20)
        with main.db() as conn:
            result = study.finish_focus_session(conn, session["id"], record=False)
            count = conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0]
        self.assertIsNone(result["recorded_study_session"])
        self.assertEqual(count, 0)
        self.assertAlmostEqual(result["actual_minutes"], 20, delta=1)

    def test_finishing_twice_is_rejected(self):
        session = self.start()
        with main.db() as conn:
            study.finish_focus_session(conn, session["id"])
            with self.assertRaises(HTTPException):
                study.finish_focus_session(conn, session["id"])

    # ---------- 汇总 ----------

    def test_state_counts_only_finished_focus_sessions(self):
        done = self.start(minutes=25)
        self.backdate(done["id"], minutes_ago=30)
        with main.db() as conn:
            study.finish_focus_session(conn, done["id"])
        running = self.start(minutes=25)

        with main.db() as conn:
            state = study.get_focus_state(conn)
        self.assertEqual(state["today"]["count"], 1, "在跑的那个还没结束，不该算进去")
        self.assertEqual(state["today"]["minutes"], 25)
        self.assertEqual(state["running"]["id"], running["id"])

    def test_state_says_what_the_count_does_not_mean(self):
        with main.db() as conn:
            state = study.get_focus_state(conn)
        self.assertIn("不代表学到了多少", state["note"])

    def test_pomodoro_records_show_up_in_study_summary(self):
        session = self.start(minutes=25, subject="英语")
        self.backdate(session["id"], minutes_ago=30)
        with main.db() as conn:
            study.finish_focus_session(conn, session["id"])
            summary = study.get_study_state(conn)
        self.assertEqual(summary["today"]["minutes"], 25)
        self.assertEqual(summary["recent"][0]["subject"], "英语")
        self.assertEqual(summary["recent"][0]["note"], "番茄钟")


if __name__ == "__main__":
    unittest.main()
