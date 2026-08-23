"""事后批量改分类。

导入几百条之后总有一批落进「其他」——商户名没被规则认出来。写入那一刻能改，
但写完就只能一笔一笔翻出来改，而主交易列表只显示最近 50 条，更早的根本够不到。

不做这件事的后果是分类统计里永远杵着一根巨大的「其他」柱子，
之后所有关于「钱花在哪」的分析都是废的。
"""
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.api import ledger as ledger_api
from backend.core import db as db_core
from backend.modules.ledger import create_transaction, recategorise_transactions


class RecategoriseTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()
        with main.db() as conn:
            self.account_id = conn.execute(
                "SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()["id"]
            self.others = [
                create_transaction(conn, occurred_on=f"2026-08-{10 + i:02d}", type="expense",
                                   category="other", account_id=self.account_id,
                                   amount=12.0 + i, note="楼下张记")["id"]
                for i in range(4)
            ]
            self.income = create_transaction(
                conn, occurred_on="2026-08-20", type="income", source="part_time",
                account_id=self.account_id, amount=300.0, note="家教")["id"]

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def categories(self):
        with main.db() as conn:
            return [row["category"] for row in conn.execute(
                "SELECT category FROM transactions WHERE type = 'expense' ORDER BY id")]

    def learned(self):
        with main.db() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM merchant_rules WHERE source = 'learned'").fetchone()[0]

    # ---------- 改 ----------

    def test_a_batch_moves_together(self):
        result = ledger_api.recategorise(
            ledger_api.RecategoriseIn(ids=self.others, category="food"))
        self.assertEqual(len(result["changed"]), 4)
        self.assertEqual(self.categories(), ["food"] * 4)

    def test_income_is_skipped_and_said_so(self):
        """收入没有支出分类。静默忽略的话，用户以为改成功了。"""
        result = ledger_api.recategorise(ledger_api.RecategoriseIn(
            ids=self.others + [self.income], category="food"))
        self.assertEqual(len(result["changed"]), 4)
        reasons = [item["reason"] for item in result["skipped"]]
        self.assertTrue(any("收入" in reason for reason in reasons))

    def test_a_missing_transaction_is_skipped_and_said_so(self):
        result = ledger_api.recategorise(
            ledger_api.RecategoriseIn(ids=[999999], category="food"))
        self.assertEqual(result["changed"], [])
        self.assertIn("已经不在了", result["skipped"][0]["reason"])

    def test_rows_already_in_that_category_are_not_recorded_as_changes(self):
        """撤销清单里混进「本来就是这个分类」的行，撤销时会把它们改成别的。"""
        ledger_api.recategorise(ledger_api.RecategoriseIn(ids=self.others, category="food"))
        again = ledger_api.recategorise(ledger_api.RecategoriseIn(ids=self.others, category="food"))
        self.assertEqual(again["changed"], [])

    def test_an_unknown_category_is_refused(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                recategorise_transactions(conn, self.others, "乱写的")

    def test_an_empty_selection_is_refused(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                recategorise_transactions(conn, [], "food")

    # ---------- 撤销 ----------

    def test_undo_puts_every_row_back_to_its_own_previous_category(self):
        """整批改完发现选错了分类，得能一次退回来，而不是手工改几百笔。

        而且每一笔要回到**它自己原来的**分类，不是统一回到某一个。
        """
        with main.db() as conn:
            mixed = create_transaction(
                conn, occurred_on="2026-08-15", type="expense", category="transport",
                account_id=self.account_id, amount=9.0, note="地铁")["id"]
        result = ledger_api.recategorise(
            ledger_api.RecategoriseIn(ids=self.others + [mixed], category="food"))
        self.assertEqual(self.categories(), ["food"] * 5)

        ledger_api.restore_transaction_categories(
            ledger_api.RestoreCategoriesIn(entries=result["changed"]))
        self.assertEqual(self.categories(), ["other"] * 4 + ["transport"])

    # ---------- 顺手记规则 ----------

    def test_it_can_remember_the_merchant_so_the_next_import_is_cleaner(self):
        """整理完这一批还得防着下一批再落进「其他」，
        否则每次导入都要重来一遍。"""
        result = ledger_api.recategorise(ledger_api.RecategoriseIn(
            ids=self.others, category="food", remember_keyword="楼下张记"))
        self.assertEqual(result["learned_rule"]["keyword"], "楼下张记")
        with main.db() as conn:
            from backend.modules.categorize import suggest_category
            self.assertEqual(suggest_category(conn, "楼下张记 外带")["category"], "food")

    def test_it_does_not_remember_anything_unless_asked(self):
        """不填关键字就只改这一批，不写规则。"""
        ledger_api.recategorise(ledger_api.RecategoriseIn(ids=self.others, category="food"))
        self.assertEqual(self.learned(), 0)

    # ---------- 和账单支付的关系 ----------

    def test_a_bill_payment_can_still_be_recategorised(self):
        """只有改日期、金额、方向才会让账单日历对不上——那三样被账单按月引用着。
        改分类不影响任何引用关系，不该被一并挡在门外。"""
        bill = ledger_api.add_recurring_bill(ledger_api.RecurringBillIn(
            name="房租", amount=800.0, day_of_month=5, category="housing",
            account_id=self.account_id))
        ledger_api.pay_recurring_bill(
            bill["bill_id"], ledger_api.PayRecurringBillIn(month="2026-08", paid_on="2026-08-05"))
        with main.db() as conn:
            tx_id = conn.execute(
                "SELECT transaction_id FROM recurring_bill_payments WHERE bill_id = ?",
                (bill["bill_id"],)).fetchone()["transaction_id"]

        result = ledger_api.recategorise(
            ledger_api.RecategoriseIn(ids=[tx_id], category="other"))
        self.assertEqual(len(result["changed"]), 1)

    def test_changing_a_bill_payment_amount_is_still_refused(self):
        """放宽的是分类，不是金额。"""
        from backend.modules.ledger import update_transaction
        bill = ledger_api.add_recurring_bill(ledger_api.RecurringBillIn(
            name="房租", amount=800.0, day_of_month=5, category="housing",
            account_id=self.account_id))
        ledger_api.pay_recurring_bill(
            bill["bill_id"], ledger_api.PayRecurringBillIn(month="2026-08", paid_on="2026-08-05"))
        with main.db() as conn:
            tx_id = conn.execute(
                "SELECT transaction_id FROM recurring_bill_payments WHERE bill_id = ?",
                (bill["bill_id"],)).fetchone()["transaction_id"]
            with self.assertRaises(HTTPException):
                update_transaction(conn, tx_id, amount=999.0)


if __name__ == "__main__":
    unittest.main()
