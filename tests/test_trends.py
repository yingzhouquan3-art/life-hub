"""按周 / 按月的走势。

这个视图最容易骗人的地方是「记得勤」被读成「变化大」：
上周只记了两天、这周记满七天，总和自然翻几倍，但什么都没发生。
下面大半的测试守的都是这一条。
"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core
from backend.views.trends import MIN_DAYS_PER_PERIOD, get_trends


class TrendTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()
        today = date.today()
        self.monday = today - timedelta(days=today.weekday())
        self.last_monday = self.monday - timedelta(days=7)
        with main.db() as conn:
            self.account_id = conn.execute(
                "SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()["id"]

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def spend(self, day, amount):
        with main.db() as conn:
            conn.execute(
                """INSERT INTO transactions
                   (occurred_on, type, source, category, account_id, amount, note, created_at)
                   VALUES (?, 'expense', 'expense', 'food', ?, ?, '', '2026-01-01')""",
                (day.isoformat(), self.account_id, amount))

    def sleep(self, day, hours):
        with main.db() as conn:
            conn.execute(
                """INSERT INTO recovery_checkins (occurred_on, sleep_hours, note, updated_at)
                   VALUES (?, ?, '', '2026-01-01')""",
                (day.isoformat(), hours))

    def metric(self, key, period="week", count=4):
        with main.db() as conn:
            trends = get_trends(conn, period, count)
        for entry in trends["metrics"]:
            if entry["key"] == key:
                return entry
        return None

    # ---------- 「记得勤」不等于「变化大」 ----------

    def test_recording_more_days_is_not_reported_as_spending_more(self):
        """上周记 2 天共 200、本周记 6 天共 600，日均都是 100。

        总和翻了三倍，但什么都没发生。这里必须拒绝给变化数字。
        """
        for offset in range(2):
            self.spend(self.last_monday + timedelta(days=offset), 100)
        for offset in range(6):
            self.spend(self.monday + timedelta(days=offset), 100)

        change = self.metric("expense")["change"]
        self.assertFalse(change["comparable"])
        self.assertIn("差太远", change["reason"])

    def test_change_is_computed_on_the_daily_average_not_the_total(self):
        """两期都记得够多时，总和不同但日均相同 → 变化应当是 0。"""
        for offset in range(4):
            self.spend(self.last_monday + timedelta(days=offset), 100)   # 共 400
        for offset in range(7):
            self.spend(self.monday + timedelta(days=offset), 100)        # 共 700

        entry = self.metric("expense")
        self.assertEqual(entry["buckets"][-2]["total"], 400)
        self.assertEqual(entry["buckets"][-1]["total"], 700)
        change = entry["change"]
        self.assertTrue(change["comparable"])
        self.assertEqual(change["delta"], 0)
        self.assertEqual(change["direction"], "flat")

    def test_a_real_change_still_shows_up(self):
        """守了假阳性，也得确认真的变化没被一起挡掉。"""
        for offset in range(5):
            self.sleep(self.last_monday + timedelta(days=offset), 8.0)
        for offset in range(5):
            self.sleep(self.monday + timedelta(days=offset), 6.0)

        change = self.metric("sleep_hours")["change"]
        self.assertTrue(change["comparable"])
        self.assertEqual(change["delta"], -2.0)
        self.assertEqual(change["direction"], "down")

    def test_days_without_records_are_skipped_not_counted_as_zero(self):
        """没记那天的睡眠不是 0 小时，补零会把日均拉垮。"""
        self.sleep(self.monday, 8.0)
        self.sleep(self.monday + timedelta(days=1), 8.0)

        bucket = self.metric("sleep_hours")["buckets"][-1]
        self.assertEqual(bucket["days"], 2)
        self.assertEqual(bucket["average"], 8.0)

    def test_a_single_day_cannot_represent_a_period(self):
        """一个点算不出平均值。"""
        self.sleep(self.last_monday, 8.0)
        self.sleep(self.monday, 6.0)

        change = self.metric("sleep_hours")["change"]
        self.assertFalse(change["comparable"])
        self.assertIn(f"{MIN_DAYS_PER_PERIOD} 天", change["reason"])

    def test_sparse_but_balanced_records_are_still_comparable(self):
        """一周只练两次力量、一周只量两次体重，都是正常的记录方式。

        以前的写法要求每期满 3 天，等于把这类人整个排除在趋势之外——
        他们记得再规律也永远看不到走势。挡的应该是悬殊，不是稀疏。
        """
        for offset in (0, 3):
            self.sleep(self.last_monday + timedelta(days=offset), 8.0)
            self.sleep(self.monday + timedelta(days=offset), 7.0)

        change = self.metric("sleep_hours")["change"]
        self.assertTrue(change["comparable"], change.get("reason"))
        self.assertEqual(change["delta"], -1.0)

    # ---------- 形状与边界 ----------

    def test_state_metrics_do_not_report_a_total(self):
        """把一周的心情加起来是没有意义的数。"""
        for offset in range(4):
            self.sleep(self.monday + timedelta(days=offset), 7.0)
        bucket = self.metric("sleep_hours")["buckets"][-1]
        self.assertIsNone(bucket["total"])
        self.assertIsNotNone(bucket["average"])

    def test_metrics_without_records_are_listed_separately_not_as_zero(self):
        """一个从没记过的指标不该显示成一条贴着 0 的平线。"""
        self.spend(self.monday, 50)
        with main.db() as conn:
            trends = get_trends(conn, "week", 4)
        tracked = {m["key"] for m in trends["metrics"]}
        untracked = {m["key"] for m in trends["untracked"]}
        self.assertIn("expense", tracked)
        self.assertIn("study_minutes", untracked)
        self.assertFalse(tracked & untracked)

    def test_empty_database_does_not_blow_up(self):
        with main.db() as conn:
            trends = get_trends(conn, "week", 4)
        self.assertEqual(trends["metrics"], [])
        self.assertTrue(trends["untracked"])

    def test_monthly_buckets_cover_whole_calendar_months(self):
        with main.db() as conn:
            trends = get_trends(conn, "month", 3)
        last = trends["metrics"] or trends["untracked"]
        self.assertTrue(last)
        with main.db() as conn:
            self.spend(date.today().replace(day=1), 10)
            trends = get_trends(conn, "month", 3)
        bucket = next(m for m in trends["metrics"] if m["key"] == "expense")["buckets"][-1]
        self.assertTrue(bucket["start"].endswith("-01"))
        self.assertEqual(bucket["label"], "本月")

    def test_unknown_period_is_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                get_trends(conn, "季度", 4)

    def test_count_out_of_range_is_rejected(self):
        with main.db() as conn:
            for bad in (1, 25):
                with self.assertRaises(HTTPException):
                    get_trends(conn, "week", bad)

    def test_every_metric_declares_how_it_aggregates(self):
        """漏一个就会在界面上显示成 None，而不是报错——那种漏很难发现。"""
        from backend.views.insights import METRICS
        from backend.views.trends import AGGREGATIONS
        self.assertEqual(set(METRICS), set(AGGREGATIONS))


if __name__ == "__main__":
    unittest.main()
