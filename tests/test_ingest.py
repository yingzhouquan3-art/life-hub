"""统一导入口。

守两件事：认得出这是什么文件、并且认错的时候说得出来；
以及自动分类只是**猜**——它可以填错，但不能悄悄变成规则。
"""
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.api import ingest as ingest_api
from backend.core import db as db_core
from backend.ingest import identify

WECHAT = """微信支付账单明细
微信昵称：某某
交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态
2026-08-01 09:12:00,商户消费,星巴克,拿铁,支出,¥32.00,零钱,支付成功
2026-08-02 12:30:00,商户消费,滴滴出行,快车,支出,¥18.50,零钱,支付成功
2026-08-03 19:00:00,商户消费,某不知名小店,东西,支出,¥7.00,零钱,支付成功
"""

WORKOUT = """日期,运动类型,运动时长,距离(km),卡路里
2026-08-01,跑步,32,5.1,320
2026-08-03,骑行,45,15.0,410
"""

BODY = """测量时间,体重(kg),体脂率(%)
2026-08-01,70.2,18.5
2026-08-05,69.8,18.2
"""


class IdentifyTests(unittest.TestCase):
    """识别只看文件的样子，不碰数据库。"""

    def test_each_kind_lands_on_its_own_module(self):
        for text, kind, module in ((WECHAT, "wechat_statement", "ledger"),
                                   (WORKOUT, "health_workout", "fitness"),
                                   (BODY, "health_body", "body")):
            with self.subTest(kind=kind):
                result = identify("导出.csv", text)
                self.assertEqual(result["best"], kind)
                best = result["candidates"][0]
                self.assertEqual(best["module"], module)

    def test_every_candidate_can_say_why(self):
        """没有依据的判断没法被用户复核，等于让人闭眼点确认。"""
        result = identify("账单.csv", WECHAT)
        self.assertTrue(result["candidates"])
        for candidate in result["candidates"]:
            self.assertTrue(candidate["evidence"], candidate["kind"])

    def test_unknown_file_is_refused_instead_of_guessed(self):
        """把体重数据当账单写进账本，比认不出来糟得多。"""
        result = identify("随便.txt", "hello world\nnothing to see here")
        self.assertIsNone(result["best"])
        self.assertEqual(result["candidates"], [])

    def test_spreadsheet_is_flagged_so_the_message_can_be_specific(self):
        result = identify("账单.xlsx", "PK\x03\x04 二进制内容")
        self.assertTrue(result["looks_like_spreadsheet"])

    def test_statement_parser_outranks_the_generic_signals(self):
        """微信账单也含有支付宝的通用列名，不能因此排到前面去。"""
        result = identify("账单.csv", WECHAT)
        kinds = [c["kind"] for c in result["candidates"]]
        self.assertEqual(kinds[0], "wechat_statement")
        self.assertIn("alipay_statement", kinds)


class IngestFlowTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def preview(self, kind, text, filename="导出.csv"):
        return ingest_api.ingest_preview(
            ingest_api.IngestPreviewIn(kind=kind, filename=filename, content=text))

    def commit(self, kind, rows, filename="导出.csv"):
        return ingest_api.ingest_commit(
            ingest_api.IngestCommitIn(kind=kind, filename=filename, rows=rows))

    def test_preview_writes_nothing(self):
        self.preview("wechat_statement", WECHAT)
        with main.db() as conn:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 0)

    def test_statement_rows_arrive_categorised_instead_of_all_other(self):
        """全部落进「其他」的话，导进来几百笔之后分类统计毫无意义。"""
        preview = self.preview("wechat_statement", WECHAT)
        self.commit("wechat_statement", preview["rows"])
        with main.db() as conn:
            categories = {
                row["note"]: row["category"]
                for row in conn.execute("SELECT note, category FROM transactions")
            }
        self.assertEqual(categories["星巴克 拿铁"], "food")
        self.assertEqual(categories["滴滴出行 快车"], "transport")
        # 猜不出来的老实落进「其他」，不硬套一个像样的分类
        self.assertEqual(categories["某不知名小店 东西"], "other")

    def test_bulk_import_never_turns_its_guesses_into_rules(self):
        """一次误判在几百行上自我强化，正是分类记忆最该避免的事。

        学习只发生在用户逐条确认时，批量导入不是逐条确认。
        """
        preview = self.preview("wechat_statement", WECHAT)
        self.commit("wechat_statement", preview["rows"])
        with main.db() as conn:
            learned = conn.execute(
                "SELECT COUNT(*) FROM merchant_rules WHERE source = 'learned'").fetchone()[0]
        self.assertEqual(learned, 0)

    def test_importing_the_same_file_twice_writes_nothing_new(self):
        for kind, text in (("wechat_statement", WECHAT),
                           ("health_workout", WORKOUT),
                           ("health_body", BODY)):
            with self.subTest(kind=kind):
                first = self.preview(kind, text)
                self.commit(kind, first["rows"])
                again = self.preview(kind, text)
                self.assertEqual(again["summary"]["will_write"], 0)
                self.assertEqual(again["summary"]["already_have"],
                                 first["summary"]["will_write"])

    def test_each_kind_reaches_its_own_module(self):
        for kind, text, module in (("wechat_statement", WECHAT, "ledger"),
                                   ("health_workout", WORKOUT, "fitness"),
                                   ("health_body", BODY, "body")):
            with self.subTest(kind=kind):
                preview = self.preview(kind, text)
                result = self.commit(kind, preview["rows"])
                self.assertEqual(result["module"], module)
                self.assertEqual(result["imported"], preview["summary"]["will_write"])

    def test_unknown_kind_is_rejected(self):
        from backend.ingest import build_ingest_preview
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                build_ingest_preview(conn, "不存在的类型", "x.csv", WECHAT)


if __name__ == "__main__":
    unittest.main()
