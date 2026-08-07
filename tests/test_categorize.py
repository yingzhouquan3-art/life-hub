"""商户分类记忆。

确认一次之后，同一个商户下次要能直接预选好分类。
但规则只能影响预选——猜错的代价必须停留在「多点一下」。
"""
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.api import capture as capture_api
from backend.core import db as db_core
from backend.modules import capture, categorize


class SuggestionTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def suggest(self, text):
        with main.db() as conn:
            return categorize.suggest_category(conn, text)

    def test_seed_rules_are_available_from_the_start(self):
        """空规则库会让这个功能一上来毫无用处。"""
        self.assertEqual(self.suggest("星巴克 拿铁")["category"], "food")
        self.assertEqual(self.suggest("滴滴出行 快车")["category"], "transport")

    def test_unknown_merchant_gets_no_suggestion(self):
        """猜不出来就不给，不能硬塞一个默认分类冒充建议。"""
        self.assertIsNone(self.suggest("某个没见过的店"))
        self.assertIsNone(self.suggest(""))

    def test_longer_keyword_wins(self):
        """「星巴克」应当压过「咖啡」——关键字越长越具体。"""
        with main.db() as conn:
            categorize.learn_category(conn, "星巴克", "social")
        self.assertEqual(self.suggest("星巴克 咖啡")["category"], "social")

    def test_learning_overrides_a_seed_rule(self):
        """用户最近一次的选择最可信。"""
        self.assertEqual(self.suggest("美团")["category"], "food")
        with main.db() as conn:
            categorize.learn_category(conn, "美团", "transport")
        suggestion = self.suggest("美团 打车")
        self.assertEqual(suggestion["category"], "transport")
        self.assertEqual(suggestion["source"], "learned", "改过的种子规则要标成学来的")

    def test_unknown_category_is_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                categorize.learn_category(conn, "某店", "不存在的分类")

    def test_overlong_key_is_not_learned(self):
        """拿整条通知原文当关键字永远不会再命中，只是噪声。"""
        with main.db() as conn:
            result = categorize.learn_category(conn, "微信支付 " * 20, "food")
        self.assertIsNone(result)

    def test_deleting_a_rule_stops_the_suggestion(self):
        """学错了必须能撤销，否则会一直错下去而用户不知道为什么。"""
        with main.db() as conn:
            rule = categorize.learn_category(conn, "某新店", "medical")
            self.assertEqual(categorize.suggest_category(conn, "某新店")["category"], "medical")
            categorize.delete_rule(conn, rule["id"])
            self.assertIsNone(categorize.suggest_category(conn, "某新店"))


class ConfirmFlowTests(unittest.TestCase):
    """确认捕获时的预选与学习。"""

    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def add_capture(self, merchant, amount=20.0):
        with main.db() as conn:
            return capture.record_capture(
                conn, channel="wechat_notification",
                raw_text=f"微信支付 向 {merchant} 付款", amount=amount, merchant=merchant,
            )["capture"]

    def test_pending_captures_carry_a_suggestion(self):
        self.add_capture("星巴克")
        state = capture_api.capture_state()
        self.assertEqual(state["pending"][0]["suggested"]["category"], "food")

    def test_confirming_teaches_the_rule(self):
        created = self.add_capture("楼下小面馆")
        capture_api.confirm_capture(
            created["id"], capture_api.CaptureConfirmIn(category="food"))

        second = self.add_capture("楼下小面馆", amount=21.0)
        state = capture_api.capture_state()
        item = next(row for row in state["pending"] if row["id"] == second["id"])
        self.assertEqual(item["suggested"]["category"], "food")
        self.assertEqual(item["suggested"]["keyword"], "楼下小面馆")

    def test_nothing_is_learned_without_a_merchant(self):
        """没有商户名时不学：整条原文当关键字只会变成噪声。"""
        with main.db() as conn:
            created = capture.record_capture(
                conn, channel="bank_sms", raw_text="您尾号1234的卡消费20元",
                amount=20.0, merchant="",
            )["capture"]
        result = capture_api.confirm_capture(
            created["id"], capture_api.CaptureConfirmIn(category="food"))
        self.assertIsNone(result["learned_rule"])

    def test_income_captures_do_not_teach_expense_rules(self):
        with main.db() as conn:
            created = capture.record_capture(
                conn, channel="wechat_notification", raw_text="微信支付 已收款",
                amount=50.0, merchant="同学", direction="income",
            )["capture"]
        result = capture_api.confirm_capture(
            created["id"], capture_api.CaptureConfirmIn(source="other"))
        self.assertIsNone(result["learned_rule"])

    def test_suggestion_never_writes_anything_by_itself(self):
        """预选只是预选：没有确认就不能有交易。"""
        self.add_capture("星巴克")
        capture_api.capture_state()
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
