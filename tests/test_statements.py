"""月度账单解析与对账。

账单是权威事实，所以这里最要紧的两件事：
不能把同一笔重复入账，也不能把退款当成一笔支出。

注意：这些样例按公开的导出格式写，没有对着真实账单验证过。
拿到真账单后应当先跑预览，确认条数与金额对得上。
"""
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core
from backend.modules import ledger
from backend.statements import build_preview, detect_source, parse_statement, reconcile

WECHAT_CSV = """微信支付账单明细
微信昵称：某某
起始时间：[2026-07-01 00:00:00] 终止时间：[2026-07-31 23:59:59]
共 4 笔记录
----------------------微信支付账单明细列表--------------------
交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注
2026-07-02 12:30:00,商户消费,星巴克,拿铁,支出,¥32.00,零钱,支付成功,4200001,S001,
2026-07-03 08:15:00,商户消费,食堂三楼,早餐,支出,¥6.50,零钱,支付成功,4200002,S002,
2026-07-05 19:00:00,转账,同学,还钱,收入,¥100.00,零钱,已收钱,4200003,S003,
2026-07-06 10:00:00,商户消费,某网店,退货,支出,¥58.00,零钱,已全额退款,4200004,S004,
"""

ALIPAY_CSV = """支付宝交易记录明细查询
账号：someone@example.com
起始日期：[2026-07-01 00:00:00]    终止日期：[2026-07-31 23:59:59]
---------------------------------交易记录---------------------------------
交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注
2026-07-02 09:00:00,交通出行,滴滴出行,didi@a.com,快车,支出,18.80,余额宝,交易成功,20260702001,D001,
2026-07-04 21:10:00,日用百货,某超市,shop@a.com,牙膏,支出,25.90,花呗,交易成功,20260704001,D002,
2026-07-09 14:00:00,退款,某超市,shop@a.com,牙膏,收入,25.90,余额宝,退款成功,20260709001,D003,
"""


class StatementParsingTests(unittest.TestCase):
    def test_source_is_detected(self):
        self.assertEqual(detect_source(WECHAT_CSV), "wechat")
        self.assertEqual(detect_source(ALIPAY_CSV), "alipay")
        self.assertIsNone(detect_source("随便一段文字"))

    def test_wechat_rows_are_parsed(self):
        result = parse_statement(WECHAT_CSV)
        self.assertEqual(result["source"], "wechat")
        self.assertEqual(result["summary"]["parsed"], 3)
        amounts = sorted(row["amount"] for row in result["rows"])
        self.assertEqual(amounts, [6.5, 32.0, 100.0])

    def test_refunded_row_is_skipped_not_imported(self):
        """已全额退款不是一笔实际支出，直接入账会凭空多出 58 元。"""
        result = parse_statement(WECHAT_CSV)
        self.assertEqual(result["summary"]["skipped"], 1)
        self.assertNotIn(58.0, [row["amount"] for row in result["rows"]])
        self.assertIn("已全额退款", result["skipped"][0]["reason"])

    def test_alipay_rows_and_refund_status(self):
        result = parse_statement(ALIPAY_CSV)
        self.assertEqual(result["source"], "alipay")
        self.assertEqual(result["summary"]["parsed"], 2)
        self.assertEqual(result["summary"]["expense"], 44.7)

    def test_preamble_and_blank_lines_do_not_break_parsing(self):
        result = parse_statement(WECHAT_CSV + "\n\n\n")
        self.assertEqual(result["summary"]["parsed"], 3)

    def test_direction_column_is_required(self):
        broken = (
            "交易时间,交易对方,商品,收/支,金额(元)\n"
            "2026-07-02 12:30:00,某商户,东西,,¥10.00\n"
        )
        result = parse_statement("微信支付账单\n" + broken)
        self.assertEqual(result["summary"]["parsed"], 0)
        self.assertIn("收支方向不明", result["skipped"][0]["reason"])

    def test_missing_header_is_reported(self):
        with self.assertRaises(HTTPException):
            parse_statement("微信支付账单\n随便几行\n没有表头\n")

    def test_empty_content_is_rejected(self):
        with self.assertRaises(HTTPException):
            parse_statement("   ")

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(HTTPException):
            parse_statement("交易时间,金额\n2026-07-01,10\n")


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_already_recorded_rows_are_not_offered_again(self):
        with main.db() as conn:
            ledger.create_transaction(
                conn, occurred_on="2026-07-02", type="expense", amount=32.0, note="星巴克",
            )
            preview = build_preview(conn, WECHAT_CSV)

        result = preview["reconciliation"]
        self.assertEqual(result["summary"]["matched"], 1)
        self.assertEqual(result["summary"]["new"], 2)
        self.assertNotIn(32.0, [row["amount"] for row in result["new"]])

    def test_one_existing_transaction_is_claimed_only_once(self):
        """同一天两笔 12 元，账本里只有一笔时，必须还有一笔算作缺失。"""
        rows = [
            {"occurred_on": "2026-07-02", "type": "expense", "amount": 12.0, "note": "a"},
            {"occurred_on": "2026-07-02", "type": "expense", "amount": 12.0, "note": "b"},
        ]
        with main.db() as conn:
            ledger.create_transaction(
                conn, occurred_on="2026-07-02", type="expense", amount=12.0, note="已经记过",
            )
            result = reconcile(conn, rows)

        self.assertEqual(result["summary"]["matched"], 1)
        self.assertEqual(result["summary"]["new"], 1)

    def test_direction_must_match_too(self):
        with main.db() as conn:
            ledger.create_transaction(
                conn, occurred_on="2026-07-05", type="expense", amount=100.0, note="巧合同额",
            )
            result = reconcile(conn, [
                {"occurred_on": "2026-07-05", "type": "income", "amount": 100.0, "note": "收款"},
            ])
        self.assertEqual(result["summary"]["matched"], 0)

    def test_nothing_is_written_during_preview(self):
        with main.db() as conn:
            before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            build_preview(conn, WECHAT_CSV)
            build_preview(conn, ALIPAY_CSV)
            after = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        self.assertEqual(after, before, "预览必须完全只读")

    def test_import_payload_only_contains_new_rows(self):
        from backend.api.statements import StatementIn, preview_statement

        with main.db() as conn:
            ledger.create_transaction(
                conn, occurred_on="2026-07-02", type="expense", amount=32.0, note="星巴克",
            )
        preview = preview_statement(StatementIn(content=WECHAT_CSV, filename="wechat-07.csv"))
        payload = preview["import_payload"]
        self.assertEqual(payload["filename"], "wechat-07.csv")
        self.assertEqual(len(payload["rows"]), preview["reconciliation"]["summary"]["new"])
        self.assertNotIn(32.0, [row["amount"] for row in payload["rows"]])

    def test_empty_statement_reconciles_to_nothing(self):
        with main.db() as conn:
            result = reconcile(conn, [])
        self.assertEqual(result["summary"]["new"], 0)


if __name__ == "__main__":
    unittest.main()
