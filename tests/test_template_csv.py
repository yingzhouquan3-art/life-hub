"""本平台账目模板的解析。

这份格式原本只在浏览器里解析，于是「导入」分成了两套：微信、支付宝、
运动数据走后端，自己的表格走前端。搬到后端之后入口才真的只剩一个，
而且模板也能用 .xlsx 导了。
"""
import tempfile
import unittest
from pathlib import Path

from backend import main
from backend.api import ingest as ingest_api
from backend.core import db as db_core
from backend.template_csv import looks_like_template, parse_template

TEMPLATE = """date,type,amount,category,source,note,account
2026-08-01,支出,32.00,餐饮,,星巴克,
2026-08-02,expense,18.50,交通,,滴滴,
2026-08-04,收入,2000,,家庭生活费,生活费,
"""


class TemplateParsingTests(unittest.TestCase):
    def test_it_recognises_its_own_template(self):
        self.assertTrue(looks_like_template(TEMPLATE))

    def test_a_file_without_date_or_amount_is_not_a_template(self):
        self.assertFalse(looks_like_template("名字,备注" + chr(10) + "甲,乙" + chr(10)))

    def test_chinese_and_english_type_words_both_work(self):
        rows = parse_template(TEMPLATE)["rows"]
        self.assertEqual([r["type"] for r in rows], ["expense", "expense", "income"])

    def test_a_negative_amount_means_expense(self):
        """表格里用负数表示支出是最常见的写法。"""
        rows = parse_template("date,amount,note" + chr(10) + "2026-08-01,-25,买菜" + chr(10))["rows"]
        self.assertEqual(rows[0]["type"], "expense")
        self.assertEqual(rows[0]["amount"], 25.0)

    def test_accounting_parentheses_mean_negative(self):
        rows = parse_template("date,amount,note" + chr(10) + "2026-08-01,(12.00),会计写法" + chr(10))["rows"]
        self.assertEqual(rows[0]["amount"], 12.0)
        self.assertEqual(rows[0]["type"], "expense")

    def test_unreadable_rows_say_which_line_and_why(self):
        """「导入完少了几笔却不知道少了哪几笔」是对账最难受的状态。"""
        text = ("date,type,amount,note" + chr(10)
                + "坏日期,支出,10,x" + chr(10)
                + "2026-08-01,支出,0,金额为零" + chr(10))
        result = parse_template(text)
        self.assertEqual(result["rows"], [])
        self.assertEqual(len(result["skipped"]), 2)
        self.assertEqual(result["skipped"][0]["line"], 2)
        self.assertIn("日期", result["skipped"][0]["reason"])
        self.assertIn("金额", result["skipped"][1]["reason"])

    def test_an_unknown_category_falls_back_and_says_so(self):
        """悄悄归到「其他」的话，用户以为自己填对了。"""
        rows = parse_template(
            "date,type,amount,category,note" + chr(10)
            + "2026-08-01,支出,10,乱写的,x" + chr(10))["rows"]
        self.assertEqual(rows[0]["category"], "other")
        self.assertIn("认不出分类", rows[0]["note_hint"])

    def test_an_unknown_account_falls_back_and_says_so(self):
        rows = parse_template(
            "date,type,amount,account,note" + chr(10)
            + "2026-08-01,支出,10,不存在的账户,x" + chr(10),
            default_account_id=7, accounts={"日常资金": 7})["rows"]
        self.assertEqual(rows[0]["account_id"], 7)
        self.assertIn("没有叫", rows[0]["note_hint"])

    def test_a_header_only_file_is_refused_clearly(self):
        result = parse_template("date,type,amount" + chr(10))
        self.assertEqual(result["rows"], [])
        self.assertIn("只有表头", result["skipped"][0]["reason"])


class TemplateThroughTheUnifiedImporterTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_the_unified_importer_recognises_it(self):
        result = ingest_api.ingest_identify(
            ingest_api.IdentifyIn(filename="我的账目.csv", content=TEMPLATE))
        self.assertEqual(result["best"], "ledger_template")

    def test_an_empty_category_gets_guessed_from_the_note(self):
        """和账单那条路一致：猜得出就填，猜不出老实落进「其他」。"""
        text = "date,type,amount,category,note" + chr(10) + "2026-08-01,支出,20,,美团外卖" + chr(10)
        preview = ingest_api.ingest_preview(ingest_api.IngestPreviewIn(
            kind="ledger_template", filename="x.csv", content=text))
        self.assertEqual(preview["rows"][0]["category"], "food")
        self.assertEqual(preview["rows"][0]["category_by"], "美团")

    def test_bulk_template_import_does_not_learn_rules(self):
        """批量导入不是逐条确认，不该回写分类规则。"""
        text = "date,type,amount,category,note" + chr(10) + "2026-08-01,支出,20,,美团外卖" + chr(10)
        preview = ingest_api.ingest_preview(ingest_api.IngestPreviewIn(
            kind="ledger_template", filename="x.csv", content=text))
        ingest_api.ingest_commit(ingest_api.IngestCommitIn(
            kind="ledger_template", filename="x.csv", rows=preview["rows"]))
        with main.db() as conn:
            learned = conn.execute(
                "SELECT COUNT(*) FROM merchant_rules WHERE source = 'learned'").fetchone()[0]
        self.assertEqual(learned, 0)

    def test_it_writes_and_dedupes_like_the_other_formats(self):
        preview = ingest_api.ingest_preview(ingest_api.IngestPreviewIn(
            kind="ledger_template", filename="x.csv", content=TEMPLATE))
        result = ingest_api.ingest_commit(ingest_api.IngestCommitIn(
            kind="ledger_template", filename="x.csv", rows=preview["rows"]))
        self.assertEqual(result["imported"], 3)
        again = ingest_api.ingest_preview(ingest_api.IngestPreviewIn(
            kind="ledger_template", filename="x.csv", content=TEMPLATE))
        self.assertEqual(again["summary"]["will_write"], 0)


if __name__ == "__main__":
    unittest.main()
