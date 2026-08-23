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
from backend.api import categorize as categorize_api
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


class MerchantAtConfirmTests(unittest.TestCase):
    """通知原文里认不出商户时，学习链是断的。

    learn_category 只在有关键字时才写规则，而解析规则是按常见文案写的、
    各家文案还会变。也就是说解析失败的那些商户，用户每次都得重新挑分类，
    而且平台永远学不会。让用户在确认那一下顺手补两个字就能接上。
    """

    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def unparsed_capture(self, amount=42.0):
        """一条认不出商户的通知——这正是真实文案最常见的情况。"""
        result = capture_api.capture_notification(capture_api.NotificationIn(
            channel="wechat_notification", text=f"微信支付 支付成功 ¥{amount:.2f}"))
        return result["capture"]["id"]

    def learned(self):
        with main.db() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM merchant_rules WHERE source = 'learned'").fetchone()[0]

    def test_without_a_merchant_nothing_is_ever_learned(self):
        """先把问题本身钉住：不补商户就学不到东西，这不是我臆想的。"""
        capture_id = self.unparsed_capture()
        capture_api.confirm_capture(capture_id, capture_api.CaptureConfirmIn(category="food"))
        self.assertEqual(self.learned(), 0)

    def test_a_merchant_typed_at_confirm_closes_the_loop(self):
        capture_id = self.unparsed_capture()
        result = capture_api.confirm_capture(
            capture_id, capture_api.CaptureConfirmIn(category="food", merchant="楼下张记"))
        self.assertEqual(self.learned(), 1)
        self.assertEqual(result["learned_rule"]["keyword"], "楼下张记")

    def test_the_next_notification_from_that_merchant_is_pre_selected(self):
        """学到规则的意义就在这一步：下次不用再挑一遍。"""
        first = self.unparsed_capture()
        capture_api.confirm_capture(
            first, capture_api.CaptureConfirmIn(category="food", merchant="楼下张记"))

        capture_api.capture_notification(capture_api.NotificationIn(
            channel="wechat_notification", text="微信支付 支付成功 ¥18.00 楼下张记"))
        pending = capture_api.capture_state()["pending"]
        suggested = [item["suggested"] for item in pending if item["suggested"]]
        self.assertTrue(suggested)
        self.assertEqual(suggested[0]["category"], "food")
        self.assertEqual(suggested[0]["keyword"], "楼下张记")

    def test_the_transaction_note_becomes_the_merchant_not_the_raw_text(self):
        """备注写成整条通知原文，账本翻起来全是「微信支付 支付成功 ¥42.00」。"""
        capture_id = self.unparsed_capture()
        result = capture_api.confirm_capture(
            capture_id, capture_api.CaptureConfirmIn(category="food", merchant="楼下张记"))
        self.assertEqual(result["transaction"]["note"], "楼下张记")

    def test_a_typed_merchant_wins_over_a_parsed_one(self):
        """解析出来的商户可能是「星巴克咖啡(西单店)」这种，用户想改成「星巴克」。"""
        with main.db() as conn:
            created = capture.record_capture(
                conn, channel="wechat_notification", raw_text="向 星巴克咖啡(西单店) 付款",
                amount=32.0, merchant="星巴克咖啡(西单店)")["capture"]
        result = capture_api.confirm_capture(
            created["id"], capture_api.CaptureConfirmIn(category="food", merchant="星巴克"))
        self.assertEqual(result["learned_rule"]["keyword"], "星巴克")
        self.assertEqual(result["transaction"]["note"], "星巴克")

    def test_income_captures_still_do_not_learn_expense_rules(self):
        """收入没有支出分类，补了商户也不该写进分类规则。"""
        with main.db() as conn:
            created = capture.record_capture(
                conn, channel="wechat_notification", raw_text="已收款 200 元",
                amount=200.0, direction="income")["capture"]
        capture_api.confirm_capture(
            created["id"], capture_api.CaptureConfirmIn(source="part_time", merchant="某公司"))
        self.assertEqual(self.learned(), 0)


class RuleManagementApiTests(unittest.TestCase):
    """规则管理界面靠这几个响应工作。

    模块注释里写着「规则可以查看和删除，否则一条学错的规则会一直错下去」，
    这组测试守的就是那条承诺在接口这一层是真的。
    """

    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_state_separates_seed_rules_from_learned_ones(self):
        """界面要能告诉用户「这条是我自己教的」还是「它自带的」。"""
        state = categorize_api.categorize_state()
        self.assertEqual(state["summary"]["learned"], 0)
        self.assertEqual(state["summary"]["seed"], state["summary"]["total"])
        self.assertTrue(state["summary"]["total"])

    def test_adding_an_existing_keyword_rejudges_instead_of_duplicating(self):
        """用户改判一条内置规则时，不能变成两条互相打架的规则。"""
        before = categorize_api.categorize_state()["summary"]["total"]
        result = categorize_api.add_rule(
            categorize_api.RuleIn(keyword="星巴克", category="social"))
        summary = result["categorize"]["summary"]
        self.assertEqual(summary["total"], before)
        self.assertEqual(summary["learned"], 1)
        with main.db() as conn:
            self.assertEqual(categorize.suggest_category(conn, "星巴克 拿铁")["category"], "social")

    def test_add_and_delete_both_return_the_refreshed_list(self):
        """界面就地刷新靠的是这两个响应，少一个就得整页重载。"""
        added = categorize_api.add_rule(
            categorize_api.RuleIn(keyword="楼下张记", category="food"))
        self.assertIn("categorize", added)
        rule_id = added["rule"]["id"]

        removed = categorize_api.remove_rule(rule_id)
        self.assertEqual(removed["deleted"], rule_id)
        keywords = [r["keyword"] for r in removed["categorize"]["rules"]]
        self.assertNotIn("楼下张记", keywords)

    def test_deleting_one_seed_rule_does_not_bring_it_back_on_restart(self):
        """播种只在规则表全空时发生，删掉一条不该被下次启动悄悄补回来。"""
        state = categorize_api.categorize_state()
        target = next(r for r in state["rules"] if r["keyword"] == "星巴克")
        categorize_api.remove_rule(target["id"])

        main.init_db()  # 相当于重启一次

        keywords = [r["keyword"] for r in categorize_api.categorize_state()["rules"]]
        self.assertNotIn("星巴克", keywords)


if __name__ == "__main__":
    unittest.main()
