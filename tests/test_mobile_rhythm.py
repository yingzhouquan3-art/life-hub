"""手机端的打卡与待办。

手机端离线时会把操作排进队列，联网后才补发。这中间可能过了几分钟，
也可能过了半天——期间用户完全可能在电脑上做了同一件事。

所以这组测试守的是一条：**补发一条迟到的操作，不能把已经做好的事撤销掉。**
做法是让手机端发「设成这样」而不是「切换一下」。
"""
import re
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

    def test_the_service_worker_can_deliver_updates(self):
        """纯 cache-first 加一个永不变的缓存名，等于**手机缓存过一次外壳就
        永远运行那个版本**：缓存名不变所以 activate 里的清理不触发，
        命中缓存就不查网络，之后所有修复都到不了用户手上。

        改成 stale-while-revalidate：先给缓存让页面立刻能开，同时后台取新的。
        """
        sw = (self.root / "sw.js").read_text(encoding="utf-8")
        self.assertNotIn("hit || fetch(event.request)", sw, "这是纯 cache-first，更新永远送不到")
        self.assertIn("cache.put", sw, "必须在后台把新的存回缓存")
        self.assertIn("caches.open", sw)

    def test_the_mobile_script_is_cache_busted(self):
        """走 http 访问时没有 Service Worker，全靠浏览器缓存。
        脚本地址不带版本号的话，更新一样可能永远到不了手机上。"""
        self.assertRegex(self.html, r'app\.js\?v=[0-9a-z-]+', "手机端脚本缺少版本号")

    def test_a_success_banner_is_not_wiped_by_the_next_refresh(self):
        """doCommit 是「showBanner('已记下') → refresh() → renderConnection()」，
        而 renderConnection 以前在联网时无条件隐藏横幅——那句确认刚显示就被
        自己人抹掉了，手机上从来没人看见过。"""
        self.assertIn("dataset.purpose", self.js)
        # 去掉注释再判：`} else {` 和 add('hidden') 之间可能隔着好几行说明，
        # 只按原文匹配的话，把 bug 放回去测试也照样绿——我实测过。
        bare = re.sub(r"//.*", "", self.js)
        self.assertNotRegex(
            bare, r"\}\s*else\s*\{\s*\$\('banner'\)\.classList\.add\('hidden'\)",
            "联网时无条件隐藏横幅，会把刚写完的「已记下」一起抹掉")

    def test_a_mobile_write_can_be_undone(self):
        """手机端改不了已有记录，猜错模块之后没有撤销就得回到电脑前。"""
        self.assertIn("banner__action", self.js)
        self.assertIn("undo.path", self.js)

    def test_offline_queue_never_sends_a_bare_toggle(self):
        """队列里排的必须是「设成这样」。这条是这次改动的全部理由。"""
        self.assertIn("desired", self.js)
        start = self.js.index("async function flipTick")
        body = self.js[start:start + 900]
        self.assertIn("desired", body)


if __name__ == "__main__":
    unittest.main()
