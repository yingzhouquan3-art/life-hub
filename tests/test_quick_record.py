"""全局一句话记录。

手机上只有一个输入框，所以「这句话属于哪个模块」必须判得住。
判错比判不出来更糟，因此含糊时要同时给出候选，认不出时要老实说认不出。
"""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.api import quick as quick_api
from backend.core import db as db_core
from backend.quick import parse_quick_record


class QuickRecordTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def parse(self, text):
        with main.db() as conn:
            return parse_quick_record(conn, text)

    def parse_as(self, text, module):
        with main.db() as conn:
            return parse_quick_record(conn, text, module)

    # ---------- 分流 ----------

    def test_routes_to_the_right_module(self):
        cases = [
            ("跑步 30 分钟 强度 6", "fitness"),
            ("午饭 鸡胸肉 450千卡 蛋白质 40", "nutrition"),
            ("喝水 2000毫升", "nutrition"),
            ("睡了 7 小时 精力 4", "recovery"),
            ("学习 高等数学 45 分钟 专注 4", "study"),
            ("记得 周五前交课程项目", "rhythm"),
            ("午饭 16.5 支付宝", "finance"),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text)["module"], expected)

    def test_money_signal_wins_over_food_words(self):
        """「午饭 16.5 支付宝」是一笔支出，不是一餐热量。"""
        result = self.parse("午饭 16.5 支付宝")
        self.assertEqual(result["module"], "finance")
        self.assertEqual(result["preview"]["amount"], 16.5)

    def test_ambiguous_sentence_lists_the_other_candidate(self):
        result = self.parse("午饭 16.5 支付宝")
        self.assertIn("nutrition", result["alternatives"])
        self.assertTrue(
            any("个人饮食" in warning for warning in result["warnings"]),
            "含糊时必须明说还可能属于哪个模块",
        )

    def test_unrecognised_sentence_is_honest_about_it(self):
        result = self.parse("今天天气不错")
        self.assertFalse(result["matched"])
        self.assertNotIn("preview", result)
        self.assertTrue(result["alternatives"], "认不出时要给出模块清单让用户自己选")

    def test_empty_input_is_rejected(self):
        with self.assertRaises(HTTPException):
            self.parse("   ")

    # ---------- 字段解析 ----------

    def test_relative_date_is_resolved(self):
        result = self.parse("昨天睡了 7 小时")
        self.assertEqual(
            result["preview"]["occurred_on"],
            (date.today() - timedelta(days=1)).isoformat(),
        )
        self.assertEqual(result["preview"]["sleep_hours"], 7.0)

    def test_hours_and_minutes_both_become_minutes(self):
        self.assertEqual(self.parse("跑步 30 分钟")["preview"]["duration_minutes"], 30)
        self.assertEqual(self.parse("健身 1.5 小时")["preview"]["duration_minutes"], 90)

    def test_activity_kind_is_guessed(self):
        self.assertEqual(self.parse("跑步 30 分钟")["preview"]["activity"], "cardio")
        self.assertEqual(self.parse("深蹲 40 分钟")["preview"]["activity"], "strength")
        self.assertEqual(self.parse("拉伸 15分钟")["preview"]["activity"], "mobility")

    def test_meal_type_is_guessed(self):
        self.assertEqual(self.parse("早餐 包子")["preview"]["meal_type"], "breakfast")
        self.assertEqual(self.parse("晚饭 面条 600千卡")["preview"]["meal_type"], "dinner")

    # ---------- 猜测必须说出来 ----------

    def test_guessed_duration_is_flagged(self):
        result = self.parse("跑步了一会")
        self.assertEqual(result["module"], "fitness")
        self.assertEqual(result["preview"]["duration_minutes"], 30)
        self.assertTrue(
            any("30 分钟" in warning for warning in result["warnings"]),
            "替用户填的默认值必须提示出来",
        )

    def test_task_without_explicit_date_is_flagged(self):
        result = self.parse("记得 周五前交课程项目")
        self.assertEqual(result["preview"]["due_on"], date.today().isoformat())
        self.assertTrue(
            any("截止日期" in warning for warning in result["warnings"]),
            "没认出「周五」就必须说清楚日期是默认填的",
        )

    # ---------- 用户改判后按指定模块重新解析 ----------

    def test_forcing_a_module_reparses_the_same_sentence(self):
        """改判到饮食后，「午饭」仍要认成午餐，而不是退化成加餐。

        字段推断留在后端，前端不需要复制一份关键词逻辑。
        """
        result = self.parse_as("午饭 16.5 支付宝", "nutrition")
        self.assertEqual(result["module"], "nutrition")
        self.assertEqual(result["preview"]["meal_type"], "lunch")

    def test_forced_module_still_lists_the_original_candidate(self):
        result = self.parse_as("午饭 16.5 支付宝", "nutrition")
        self.assertIn("finance", result["alternatives"])

    def test_forcing_a_module_works_even_without_keywords(self):
        """认不出归属的句子，用户仍然可以指定一个模块手动填。

        标题里的「今天」被日期解析吃掉了，这是刻意的：日期词进 due_on，
        不该再留在待办标题里。
        """
        result = self.parse_as("今天天气不错", "rhythm")
        self.assertTrue(result["matched"])
        self.assertEqual(result["module"], "rhythm")
        self.assertEqual(result["preview"]["title"], "天气不错")
        self.assertEqual(result["preview"]["due_on"], date.today().isoformat())

    def test_unknown_forced_module_is_rejected(self):
        with self.assertRaises(HTTPException):
            self.parse_as("跑步 30 分钟", "telepathy")

    def test_forcing_finance_still_returns_a_transaction_preview(self):
        result = self.parse_as("跑步 30 分钟", "finance")
        self.assertEqual(result["module"], "finance")
        self.assertIn("amount", result["preview"])

    # ---------- 解析不写入 ----------

    def test_parsing_never_writes_anything(self):
        with main.db() as conn:
            tables = ["transactions", "fitness_sessions", "nutrition_entries",
                      "recovery_checkins", "study_sessions", "personal_tasks"]
            before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
            for text in ("跑步 30 分钟", "午饭 16.5 支付宝", "睡了 7 小时", "记得 交作业"):
                parse_quick_record(conn, text)
            after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
        self.assertEqual(after, before)

    # ---------- 确认后落库 ----------

    def test_commit_writes_to_the_chosen_module(self):
        parsed = quick_api.parse_quick(quick_api.QuickTextIn(text="跑步 30 分钟 强度 6"))
        committed = quick_api.commit_quick(
            quick_api.QuickCommitIn(module=parsed["module"], payload=parsed["preview"])
        )
        self.assertEqual(committed["session"]["duration_minutes"], 30)
        self.assertEqual(committed["session"]["intensity"], 6)
        self.assertEqual(committed["life"]["fitness"]["today"]["minutes"], 30)

    def test_commit_can_be_redirected_to_another_module(self):
        """用户把「午饭 16.5 支付宝」改判成饮食，也应当写得进去。"""
        parsed = quick_api.parse_quick(quick_api.QuickTextIn(text="午饭 16.5 支付宝"))
        self.assertEqual(parsed["module"], "finance")
        committed = quick_api.commit_quick(quick_api.QuickCommitIn(
            module="nutrition",
            payload={"occurred_on": date.today().isoformat(), "meal_type": "lunch",
                     "name": "午饭", "calories": None, "protein_g": None, "water_ml": None},
        ))
        self.assertEqual(committed["entry"]["meal_type"], "lunch")

    def test_commit_reports_missing_fields_instead_of_crashing(self):
        with self.assertRaises(HTTPException) as caught:
            quick_api.commit_quick(quick_api.QuickCommitIn(
                module="fitness", payload={"occurred_on": date.today().isoformat()},
            ))
        self.assertEqual(caught.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
