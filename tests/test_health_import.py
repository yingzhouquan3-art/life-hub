"""运动 / 健康数据导入。

重复导入是这个功能最容易出的事故：同一份导出文件再传一次，
运动记录就翻倍了。所以对账规则是这里的重点。

注意：列名映射按常见导出格式编写，未对真实导出文件验证。
"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.api import health_import as health_api
from backend.core import db as db_core
from backend.health_import import build_health_preview, parse_health_export
from backend.modules import body, fitness

WORKOUT_CSV = """华为运动健康 · 运动记录
日期,运动类型,运动时长,距离(km),消耗
2026-07-02,户外跑步,00:32:00,5.20,320
2026-07-03,力量训练,45分钟,,260
2026-07-04,瑜伽,1小时10分,,150
2026-07-05,未知项目,,,
"""

BODY_CSV = """华为运动健康 · 身体数据
测量时间,体重(kg),体脂率(%)
2026-07-02,70.5,18.2
2026-07-04,70.1,
2026-07-06,,
"""


class HealthParsingTests(unittest.TestCase):
    def test_workout_rows_are_parsed(self):
        result = parse_health_export(WORKOUT_CSV, "workout")
        self.assertEqual(result["summary"]["parsed"], 3)
        self.assertEqual(result["summary"]["skipped"], 1)

    def test_duration_formats_all_become_minutes(self):
        rows = parse_health_export(WORKOUT_CSV, "workout")["rows"]
        minutes = {row["occurred_on"]: row["duration_minutes"] for row in rows}
        self.assertEqual(minutes["2026-07-02"], 32)   # 00:32:00
        self.assertEqual(minutes["2026-07-03"], 45)   # 45分钟
        self.assertEqual(minutes["2026-07-04"], 70)   # 1小时10分

    def test_activity_kind_is_mapped(self):
        rows = {row["occurred_on"]: row for row in parse_health_export(WORKOUT_CSV, "workout")["rows"]}
        self.assertEqual(rows["2026-07-02"]["activity"], "cardio")
        self.assertEqual(rows["2026-07-03"]["activity"], "strength")
        self.assertEqual(rows["2026-07-04"]["activity"], "mobility")

    def test_row_without_duration_is_skipped_not_guessed(self):
        result = parse_health_export(WORKOUT_CSV, "workout")
        self.assertIn("运动时长", result["skipped"][0]["reason"])

    def test_body_rows_allow_partial_values(self):
        result = parse_health_export(BODY_CSV, "body")
        self.assertEqual(result["summary"]["parsed"], 2)
        rows = {row["occurred_on"]: row for row in result["rows"]}
        self.assertEqual(rows["2026-07-02"]["body_fat_pct"], 18.2)
        self.assertIsNone(rows["2026-07-04"]["body_fat_pct"], "没量体脂就是未知")

    def test_row_with_no_measurement_at_all_is_skipped(self):
        result = parse_health_export(BODY_CSV, "body")
        self.assertEqual(result["summary"]["skipped"], 1)

    def test_missing_header_is_reported(self):
        with self.assertRaises(HTTPException):
            parse_health_export("随便几行\n没有表头\n", "workout")

    def test_unknown_kind_is_rejected(self):
        with self.assertRaises(HTTPException):
            parse_health_export(WORKOUT_CSV, "sleep")

    def test_empty_content_is_rejected(self):
        with self.assertRaises(HTTPException):
            parse_health_export("   ", "workout")


class HealthReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_already_recorded_workout_is_not_offered_again(self):
        with main.db() as conn:
            fitness.record_workout(conn, occurred_on="2026-07-03", activity="strength",
                                   duration_minutes=45, intensity=7)
            preview = build_health_preview(conn, WORKOUT_CSV, "workout")
        summary = preview["reconciliation"]["summary"]
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["new"], 2)

    def test_two_same_length_workouts_on_one_day_both_count(self):
        """一条已有记录只能被认领一次，否则会漏掉真正缺的那条。"""
        csv_text = (
            "日期,运动类型,运动时长\n"
            "2026-07-02,跑步,30分钟\n"
            "2026-07-02,跑步,30分钟\n"
        )
        with main.db() as conn:
            fitness.record_workout(conn, occurred_on="2026-07-02", activity="cardio",
                                   duration_minutes=30, intensity=5)
            preview = build_health_preview(conn, csv_text, "workout")
        summary = preview["reconciliation"]["summary"]
        self.assertEqual((summary["matched"], summary["new"]), (1, 1))

    def test_body_measurement_on_an_existing_day_is_not_overwritten(self):
        with main.db() as conn:
            body.save_body_measurement(conn, occurred_on="2026-07-02", weight_kg=99.0)
            preview = build_health_preview(conn, BODY_CSV, "body")
        summary = preview["reconciliation"]["summary"]
        self.assertEqual(summary["matched"], 1)
        self.assertEqual(summary["new"], 1)
        self.assertIn("不会被覆盖", preview["note"])

    def test_preview_writes_nothing(self):
        with main.db() as conn:
            before = conn.execute("SELECT COUNT(*) FROM fitness_sessions").fetchone()[0]
            build_health_preview(conn, WORKOUT_CSV, "workout")
            build_health_preview(conn, BODY_CSV, "body")
            after = conn.execute("SELECT COUNT(*) FROM fitness_sessions").fetchone()[0]
        self.assertEqual(after, before)

    def test_importing_the_same_file_twice_does_not_duplicate(self):
        """最容易出的事故：再传一次，运动记录翻倍。"""
        with main.db() as conn:
            first = build_health_preview(conn, WORKOUT_CSV, "workout")
        health_api.commit_health_export(health_api.HealthCommitIn(
            kind="workout", rows=first["reconciliation"]["new"]))

        with main.db() as conn:
            second = build_health_preview(conn, WORKOUT_CSV, "workout")
            total = conn.execute("SELECT COUNT(*) FROM fitness_sessions").fetchone()[0]

        self.assertEqual(second["reconciliation"]["summary"]["new"], 0)
        self.assertEqual(total, 3)

    def test_commit_reports_bad_rows_without_losing_the_batch(self):
        result = health_api.commit_health_export(health_api.HealthCommitIn(
            kind="workout",
            rows=[
                {"occurred_on": "2026-07-02", "activity": "cardio", "duration_minutes": 30},
                {"occurred_on": "不是日期", "activity": "cardio", "duration_minutes": 30},
            ],
        ))
        self.assertEqual(result["imported"], 1)
        self.assertEqual(len(result["failed"]), 1)

    def test_imported_workouts_flag_the_default_intensity(self):
        """强度是导出文件里没有的，替用户填的默认值必须说出来。"""
        result = health_api.commit_health_export(health_api.HealthCommitIn(
            kind="workout",
            rows=[{"occurred_on": "2026-07-02", "activity": "cardio", "duration_minutes": 30}],
        ))
        self.assertIn("强度默认按 5", result["note"])


if __name__ == "__main__":
    unittest.main()
