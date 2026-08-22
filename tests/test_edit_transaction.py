"""改一笔已经记好的账。

在这之前，把 16.5 记成 165 的唯一出路是删掉重记——一个纠错动作要走一遍
删除。这组测试守两件事：改得对，以及**不该改的地方它会拦住**。
"""
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.api import ledger as ledger_api
from backend.core import db as db_core
from backend.modules.ledger import create_transaction, update_transaction


class EditTransactionTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()
        with main.db() as conn:
            self.account_id = conn.execute(
                "SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()["id"]
            self.tx = create_transaction(
                conn, occurred_on="2026-08-20", type="expense", category="food",
                account_id=self.account_id, amount=165.0, note="午饭")

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def read(self):
        with main.db() as conn:
            return dict(conn.execute(
                "SELECT * FROM transactions WHERE id = ?", (self.tx["id"],)).fetchone())

    def patch(self, **fields):
        return ledger_api.patch_transaction(
            self.tx["id"], ledger_api.TransactionPatchIn(**fields))

    # ---------- 改得对 ----------

    def test_fixing_a_typo_leaves_everything_else_alone(self):
        self.patch(amount=16.5)
        row = self.read()
        self.assertEqual(row["amount"], 16.5)
        self.assertEqual(row["note"], "午饭")
        self.assertEqual(row["occurred_on"], "2026-08-20")
        self.assertEqual(row["category"], "food")

    def test_each_field_can_be_changed_on_its_own(self):
        self.patch(occurred_on="2026-08-18")
        self.assertEqual(self.read()["occurred_on"], "2026-08-18")
        self.patch(category="transport")
        self.assertEqual(self.read()["category"], "transport")
        self.patch(note="改成打车")
        self.assertEqual(self.read()["note"], "改成打车")
        # 前面改过的不该被后面的单字段修改冲掉
        self.assertEqual(self.read()["occurred_on"], "2026-08-18")

    def test_the_ledger_totals_follow_the_edit(self):
        """改了金额但统计不动，比不能改更糟——用户会以为改成功了。"""
        before = ledger_api.patch_transaction(
            self.tx["id"], ledger_api.TransactionPatchIn(amount=16.5))
        self.assertEqual(before["stats"]["total_expense"], 16.5)

    def test_switching_direction_renormalises_source_and_category(self):
        """收入没有支出分类。沿用旧值会留下 type=income 而 category=food 的矛盾行。"""
        self.patch(type="income", source="part_time")
        row = self.read()
        self.assertEqual(row["type"], "income")
        self.assertEqual(row["category"], "income")
        self.assertEqual(row["source"], "part_time")

    def test_switching_back_to_expense_gets_a_usable_category(self):
        self.patch(type="income")
        self.patch(type="expense")
        row = self.read()
        self.assertEqual(row["source"], "expense")
        self.assertEqual(row["category"], "other")

    # ---------- 拦得住 ----------

    def test_a_bill_payment_transaction_is_refused(self):
        """这笔同时被账单按月引用着。改了日期，账单日历仍认为你付的是原来那个月，
        两边对不上而且没人看得出来。"""
        with main.db() as conn:
            bill = ledger_api.add_recurring_bill(ledger_api.RecurringBillIn(
                name="房租", amount=800.0, day_of_month=5, category="housing",
                account_id=self.account_id))
        paid = ledger_api.pay_recurring_bill(
            bill["bill_id"], ledger_api.PayRecurringBillIn(month="2026-08", paid_on="2026-08-05"))
        with main.db() as conn:
            tx_id = conn.execute(
                "SELECT transaction_id FROM recurring_bill_payments WHERE bill_id = ?",
                (bill["bill_id"],)).fetchone()["transaction_id"]
            with self.assertRaises(HTTPException) as caught:
                update_transaction(conn, tx_id, amount=999.0)
        self.assertIn("撤销这次支付", caught.exception.detail)

    def test_unknown_transaction_is_a_404(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException) as caught:
                update_transaction(conn, 999999, amount=1.0)
        self.assertEqual(caught.exception.status_code, 404)

    def test_a_bad_amount_is_refused(self):
        with main.db() as conn:
            for bad in (0, -5):
                with self.subTest(amount=bad):
                    with self.assertRaises(HTTPException):
                        update_transaction(conn, self.tx["id"], amount=bad)

    def test_a_bad_date_is_refused(self):
        with main.db() as conn:
            with self.assertRaises(ValueError):
                update_transaction(conn, self.tx["id"], occurred_on="八月二十号")

    def test_an_inactive_account_is_refused(self):
        with main.db() as conn:
            conn.execute(
                """INSERT INTO accounts (name, type, opening_balance, is_active, created_at)
                   VALUES ('已停用', 'other', 0, 0, '2026-01-01')""")
            dead = conn.execute(
                "SELECT id FROM accounts WHERE is_active = 0").fetchone()["id"]
            with self.assertRaises(HTTPException):
                update_transaction(conn, self.tx["id"], account_id=dead)

    def test_an_empty_patch_is_refused(self):
        with self.assertRaises(HTTPException):
            self.patch()

    def test_editing_does_not_teach_a_category_rule(self):
        """一次改判不该悄悄改变以后所有同名商户的预选。
        规则只在用户逐条确认捕获时学。"""
        self.patch(category="entertainment")
        with main.db() as conn:
            learned = conn.execute(
                "SELECT COUNT(*) FROM merchant_rules WHERE source = 'learned'").fetchone()[0]
        self.assertEqual(learned, 0)


if __name__ == "__main__":
    unittest.main()
