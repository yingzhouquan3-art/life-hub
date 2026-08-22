"""手机端的打卡与待办。

手机端离线时会把操作排进队列，联网后才补发。这中间可能过了几分钟，
也可能过了半天——期间用户完全可能在电脑上做了同一件事。

所以这组测试守的是一条：**补发一条迟到的操作，不能把已经做好的事撤销掉。**
做法是让手机端发「设成这样」而不是「切换一下」。
"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.api import rhythm as rhythm_api
from backend.core import db as db_core
from backend.modules.rhythm import toggle_habit_checkin, toggle_personal_task


class MobileRhythmTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()
        self.today = date.today().isoformat()
        with main.db() as conn:
            self.habit = rhythm_api.add_habit(
                rhythm_api.HabitIn(name="每天读半小时"))["habit"]
            self.task = rhythm_api.add_personal_task(
                rhythm_api.PersonalTaskIn(title="交课程项目"))["task"]

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def checked(self):
        with main.db() as conn:
            return bool(conn.execute(
                "SELECT 1 FROM habit_checkins WHERE habit_id = ? AND occurred_on = ?",
                (self.habit["id"], self.today)).fetchone())

    def status(self):
        with main.db() as conn:
            return conn.execute(
                "SELECT status FROM personal_tasks WHERE id = ?",
                (self.task["id"],)).fetchone()["status"]

    # ---------- 迟到的补发不能撤销已经做好的事 ----------

    def test_replaying_a_queued_checkin_keeps_it_checked(self):
        """离线打了卡，回家又在电脑上打了一次，补发不能把它取消。"""
        with main.db() as conn:
            toggle_habit_checkin(conn, self.habit["id"], self.today)  # 电脑上先打了
        self.assertTrue(self.checked())

        with main.db() as conn:  # 手机排队的那条这时才补发
            toggle_habit_checkin(conn, self.habit["id"], self.today, desired=True)
        self.assertTrue(self.checked())

    def test_replaying_a_queued_checkin_is_safe_any_number_of_times(self):
        for _ in range(3):
            with main.db() as conn:
                toggle_habit_checkin(conn, self.habit["id"], self.today, desired=True)
        self.assertTrue(self.checked())
        with main.db() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM habit_checkins WHERE habit_id = ?",
                (self.habit["id"],)).fetchone()[0]
        self.assertEqual(count, 1)

    def test_replaying_a_queued_task_completion_keeps_it_done(self):
        with main.db() as conn:
            toggle_personal_task(conn, self.task["id"])  # 电脑上先勾了
        self.assertEqual(self.status(), "done")
        with main.db() as conn:
            toggle_personal_task(conn, self.task["id"], desired="done")
        self.assertEqual(self.status(), "done")

    def test_a_plain_toggle_would_have_undone_it(self):
        """把上面那条反过来跑一次，确认这个风险是真的，不是我臆想出来的。"""
        with main.db() as conn:
            toggle_habit_checkin(conn, self.habit["id"], self.today)
            toggle_habit_checkin(conn, self.habit["id"], self.today)  # 迟到的「切换」
        self.assertFalse(self.checked())

    # ---------- 桌面端的「切换」照旧 ----------

    def test_toggle_without_a_desired_state_still_flips(self):
        with main.db() as conn:
            self.assertTrue(toggle_habit_checkin(conn, self.habit["id"], self.today)["checked"])
            self.assertFalse(toggle_habit_checkin(conn, self.habit["id"], self.today)["checked"])

    def test_desired_false_can_undo_a_mistap(self):
        with main.db() as conn:
            toggle_habit_checkin(conn, self.habit["id"], self.today, desired=True)
            toggle_habit_checkin(conn, self.habit["id"], self.today, desired=False)
        self.assertFalse(self.checked())

    def test_unknown_task_status_is_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                toggle_personal_task(conn, self.task["id"], desired="完成了吧")

    def test_checkin_for_another_day_does_not_touch_today(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with main.db() as conn:
            toggle_habit_checkin(conn, self.habit["id"], yesterday, desired=True)
        self.assertFalse(self.checked())

    # ---------- 手机端拿得到它需要的东西 ----------

    def test_rhythm_state_carries_what_the_phone_shows(self):
        """手机上那张卡片只显示名字、今天打没打、连续多少天。"""
        state = rhythm_api.rhythm_state()
        habit = state["habits"][0]
        for field in ("id", "name", "checked_today", "streak"):
            self.assertIn(field, habit)
        task = state["tasks"][0]
        for field in ("id", "title", "status", "due_on", "priority"):
            self.assertIn(field, task)


class MobileShellTests(unittest.TestCase):
    """手机端是独立的一套页面，桌面端的守卫测试覆盖不到它。"""

    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / "frontend" / "m"
        self.html = (self.root / "index.html").read_text(encoding="utf-8")
        self.js = (self.root / "app.js").read_text(encoding="utf-8")

    def test_the_card_has_both_markup_and_a_renderer(self):
        self.assertIn('id="rhythmList"', self.html)
        self.assertIn("loadRhythm()", self.js)

    def test_offline_queue_never_sends_a_bare_toggle(self):
        """队列里排的必须是「设成这样」。这条是这次改动的全部理由。"""
        self.assertIn("desired", self.js)
        start = self.js.index("async function flipTick")
        body = self.js[start:start + 900]
        self.assertIn("desired", body)


if __name__ == "__main__":
    unittest.main()
