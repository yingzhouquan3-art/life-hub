"""跨模块同期变化。

这是整个平台最容易被误读的地方，所以测的重点不是算得准不准，
而是「什么时候闭嘴」：样本不够不给数字，缺一边的天不补零，
任何结论都不能说成因果。
"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core
from backend.modules import body, recovery, study
from backend.views import insights


class InsightTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def day(self, offset):
        return (date.today() - timedelta(days=offset)).isoformat()

    def seed_pairs(self, count, *, sleep_start=6.0, minutes_start=30, step=1.0):
        """造 count 天两项都有记录的数据，且严格同向。"""
        with main.db() as conn:
            for index in range(count):
                recovery.save_recovery_checkin(
                    conn, occurred_on=self.day(index),
                    sleep_hours=sleep_start + index * step,
                )
                study.record_study_session(
                    conn, occurred_on=self.day(index), subject="复习",
                    duration_minutes=minutes_start + index * 10, focus=3,
                )

    def compare(self, a="sleep_hours", b="study_minutes", days=90):
        with main.db() as conn:
            return insights.compare_metrics(conn, a, b, days)

    # ---------- 样本不够就闭嘴 ----------

    def test_too_few_paired_days_gives_no_number(self):
        self.seed_pairs(insights.MIN_PAIRED_DAYS - 1)
        result = self.compare()
        self.assertIsNone(result["correlation"])
        self.assertIn("少于", result["reason"])

    def test_enough_paired_days_gives_a_number(self):
        self.seed_pairs(insights.MIN_PAIRED_DAYS)
        result = self.compare()
        self.assertIsNotNone(result["correlation"])
        self.assertEqual(result["paired_days"], insights.MIN_PAIRED_DAYS)

    def test_perfectly_aligned_series_correlate_at_one(self):
        self.seed_pairs(10)
        result = self.compare()
        self.assertAlmostEqual(result["correlation"], 1.0, places=3)
        self.assertEqual(result["direction"], "同向")

    def test_flat_series_has_no_computable_relation(self):
        """一边全程没变，相关系数没有意义，不能报 0 了事。"""
        with main.db() as conn:
            for index in range(10):
                recovery.save_recovery_checkin(
                    conn, occurred_on=self.day(index), sleep_hours=7.0,
                )
                study.record_study_session(
                    conn, occurred_on=self.day(index), subject="复习",
                    duration_minutes=30 + index * 5, focus=3,
                )
        result = self.compare()
        self.assertIsNone(result["correlation"])
        self.assertIn("完全没有变化", result["reason"])

    # ---------- 缺一边的天不补零 ----------

    def test_days_missing_one_side_are_skipped_not_zeroed(self):
        self.seed_pairs(8)
        with main.db() as conn:
            for index in range(8, 20):
                study.record_study_session(
                    conn, occurred_on=self.day(index), subject="只学习没睡眠记录",
                    duration_minutes=60, focus=3,
                )
        result = self.compare()
        self.assertEqual(result["paired_days"], 8, "只有一边有记录的天不能配对")
        self.assertEqual(result["metric_b"]["days_with_data"], 20)

    def test_no_overlap_at_all_is_reported_honestly(self):
        with main.db() as conn:
            recovery.save_recovery_checkin(conn, occurred_on=self.day(1), sleep_hours=7.0)
            study.record_study_session(
                conn, occurred_on=self.day(40), subject="很久以前",
                duration_minutes=60, focus=3,
            )
        result = self.compare()
        self.assertEqual(result["paired_days"], 0)
        self.assertIsNone(result["correlation"])

    # ---------- 措辞 ----------

    def test_every_comparison_carries_the_causation_caveat(self):
        self.seed_pairs(10)
        result = self.compare()
        self.assertIn("不能推导因果", result["note"])

    def test_overview_says_missing_numbers_do_not_mean_unrelated(self):
        with main.db() as conn:
            overview = insights.get_insights(conn)
        self.assertIn("不代表两者无关", overview["note"])
        self.assertEqual(len(overview["comparisons"]), len(insights.DEFAULT_PAIRS))

    # ---------- 输入校验 ----------

    def test_unknown_metric_is_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                insights.compare_metrics(conn, "sleep_hours", "星座运势")

    def test_absurd_window_is_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                insights.compare_metrics(conn, "sleep_hours", "study_minutes", days=1)

    def test_every_declared_metric_actually_queries(self):
        """指标表里写错一条 SQL，只会在有人正好看那一组时才炸。"""
        with main.db() as conn:
            for key in insights.METRICS:
                with self.subTest(metric=key):
                    insights.compare_metrics(conn, key, "study_minutes", days=30)

    # ---------- 数据健康度 ----------

    def test_health_reports_days_since_last_record(self):
        with main.db() as conn:
            body.save_body_measurement(conn, occurred_on=self.day(5), weight_kg=70.0)
            health = insights.get_data_health(conn)
        weight = next(item for item in health["metrics"] if item["key"] == "weight_kg")
        self.assertEqual(weight["days_since"], 5)
        self.assertEqual(weight["days_recorded"], 1)

    def test_health_leaves_never_recorded_metrics_as_unknown(self):
        with main.db() as conn:
            health = insights.get_data_health(conn)
        for item in health["metrics"]:
            self.assertIsNone(item["days_since"])
            self.assertEqual(item["days_recorded"], 0)
        self.assertIn("不代表没有发生", health["note"])


if __name__ == "__main__":
    unittest.main()
