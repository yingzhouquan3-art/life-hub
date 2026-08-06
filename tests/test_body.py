"""身体指标模块。

体重是健身与饮食唯一的共同锚点，所以这里守两件事：
未填写的指标不能被当成零，变化量只描述差值、不解释原因。
"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core
from backend.modules import body


class BodyMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()
        self.today = date.today()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def day(self, offset):
        return (self.today + timedelta(days=offset)).isoformat()

    def save(self, offset=0, **fields):
        with main.db() as conn:
            return body.save_body_measurement(conn, occurred_on=self.day(offset), **fields)

    def state(self):
        with main.db() as conn:
            return body.get_body_state(conn)

    # ---------- 保存与更新 ----------

    def test_one_record_per_day_and_resaving_updates(self):
        self.save(0, weight_kg=70.0)
        self.save(0, weight_kg=70.5, waist_cm=80.0)
        with main.db() as conn:
            rows = conn.execute("SELECT * FROM body_measurements").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["weight_kg"], 70.5)
        self.assertEqual(rows[0]["waist_cm"], 80.0)

    def test_empty_record_is_rejected(self):
        with self.assertRaises(HTTPException):
            self.save(0)

    def test_non_positive_values_are_rejected(self):
        with self.assertRaises(HTTPException):
            self.save(0, weight_kg=0)
        with self.assertRaises(HTTPException):
            self.save(0, body_fat_pct=120)

    def test_unknown_girth_field_is_rejected(self):
        with self.assertRaises(HTTPException):
            self.save(0, ankle_cm=22.0)

    def test_note_alone_is_enough(self):
        record = self.save(0, note="今天没带体脂秤")
        self.assertIsNone(record["weight_kg"])
        self.assertEqual(record["note"], "今天没带体脂秤")

    # ---------- 未填写代表未知 ----------

    def test_missing_metric_is_unknown_not_zero(self):
        self.save(0, weight_kg=70.0)
        state = self.state()
        self.assertIsNone(state["latest"]["waist_cm"], "没量腰围就是未知，不是 0")
        self.assertNotIn("waist_cm", state["changes"], "从没量过的指标不该出现变化量")

    def test_change_skips_days_without_that_metric(self):
        """只称了体重的那天，不该打断围度的前后对比。"""
        self.save(-14, weight_kg=72.0, waist_cm=84.0)
        self.save(-7, weight_kg=71.0)
        self.save(0, weight_kg=70.0, waist_cm=82.0)

        changes = self.state()["changes"]
        self.assertEqual(changes["weight_kg"]["delta"], -1.0)
        self.assertEqual(changes["weight_kg"]["days_between"], 7)
        self.assertEqual(changes["waist_cm"]["delta"], -2.0)
        self.assertEqual(changes["waist_cm"]["days_between"], 14)

    def test_first_record_has_no_delta(self):
        self.save(0, weight_kg=70.0)
        change = self.state()["changes"]["weight_kg"]
        self.assertIsNone(change["delta"])
        self.assertIsNone(change["previous"])

    # ---------- 趋势 ----------

    def test_seven_day_average_smooths_the_curve(self):
        for offset, weight in enumerate([70.0, 71.0, 69.0], start=-2):
            self.save(offset, weight_kg=weight)
        with main.db() as conn:
            trend = body.get_weight_trend(conn, 30)
        self.assertEqual(trend["count"], 3)
        self.assertEqual(trend["points"][0]["average_7"], 70.0)
        self.assertEqual(trend["points"][2]["average_7"], 70.0)

    def test_trend_is_empty_without_weight_records(self):
        self.save(0, waist_cm=80.0)
        with main.db() as conn:
            trend = body.get_weight_trend(conn)
        self.assertEqual(trend["count"], 0)
        self.assertIn("不能推导体重没有变化", trend["note"])

    def test_trend_rejects_absurd_ranges(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                body.get_weight_trend(conn, 0)

    def test_days_since_last_measurement(self):
        self.save(-3, weight_kg=70.0)
        self.assertEqual(self.state()["days_since_last"], 3)

    def test_empty_module_reports_nothing_rather_than_zero(self):
        state = self.state()
        self.assertIsNone(state["latest"])
        self.assertIsNone(state["days_since_last"])
        self.assertEqual(state["changes"], {})

    # ---------- 删除 ----------

    def test_delete_removes_only_that_day(self):
        self.save(-1, weight_kg=71.0)
        record = self.save(0, weight_kg=70.0)
        with main.db() as conn:
            body.delete_body_measurement(conn, record["id"])
            remaining = conn.execute("SELECT occurred_on FROM body_measurements").fetchall()
        self.assertEqual([row["occurred_on"] for row in remaining], [self.day(-1)])

    def test_deleting_a_missing_record_is_an_error(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                body.delete_body_measurement(conn, 999)


if __name__ == "__main__":
    unittest.main()
