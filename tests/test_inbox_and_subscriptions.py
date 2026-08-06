"""收集箱与订阅总览。

收集箱守的是「归档只是标记去向，不复制内容」；
订阅守的是「季付年付不会月月提醒一笔并不会扣的钱」。
"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.api import ledger as ledger_api
from backend.core import db as db_core
from backend.modules import inbox, ledger


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def add(self, content="买跑鞋", **kwargs):
        with main.db() as conn:
            return inbox.add_inbox_item(conn, content=content, **kwargs)

    def state(self, **kwargs):
        with main.db() as conn:
            return inbox.get_inbox_state(conn, **kwargs)

    def test_item_lands_open_and_counts(self):
        self.add()
        summary = self.state()["summary"]
        self.assertEqual(summary["open"], 1)
        self.assertEqual(summary["filed"], 0)

    def test_empty_content_is_rejected(self):
        with self.assertRaises(HTTPException):
            self.add("   ")

    def test_unknown_source_is_rejected(self):
        with self.assertRaises(HTTPException):
            self.add("x", source="telepathy")

    def test_filing_only_marks_where_it_went(self):
        """归档不复制内容——否则收集箱会变成第二份事实来源。"""
        item = self.add("买跑鞋")
        with main.db() as conn:
            filed = inbox.file_inbox_item(conn, item["id"], "finance")
            transactions = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        self.assertEqual(filed["status"], "filed")
        self.assertEqual(filed["filed_module"], "finance")
        self.assertEqual(transactions, 0, "归档不能在目标模块里凭空造出记录")

    def test_unknown_target_is_rejected(self):
        item = self.add()
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                inbox.file_inbox_item(conn, item["id"], "astrology")

    def test_an_item_can_only_be_resolved_once(self):
        item = self.add()
        with main.db() as conn:
            inbox.drop_inbox_item(conn, item["id"])
            with self.assertRaises(HTTPException):
                inbox.file_inbox_item(conn, item["id"], "finance")

    def test_reopening_clears_the_destination(self):
        item = self.add()
        with main.db() as conn:
            inbox.file_inbox_item(conn, item["id"], "finance")
            reopened = inbox.reopen_inbox_item(conn, item["id"])
        self.assertEqual(reopened["status"], "open")
        self.assertIsNone(reopened["filed_module"])

    def test_oldest_open_days_surfaces_a_stagnant_inbox(self):
        item = self.add()
        with main.db() as conn:
            conn.execute(
                "UPDATE inbox_items SET created_at = ? WHERE id = ?",
                ("2026-07-01T09:00:00", item["id"]),
            )
        self.assertGreater(self.state()["summary"]["oldest_open_days"], 0)

    def test_resolved_items_do_not_clutter_the_open_list(self):
        first = self.add("买跑鞋")
        self.add("查一下考试时间")
        with main.db() as conn:
            inbox.file_inbox_item(conn, first["id"], "finance")
        self.assertEqual(len(self.state()["items"]), 1)
        self.assertEqual(len(self.state(status="filed")["items"]), 1)

    def test_unknown_status_filter_is_rejected(self):
        with self.assertRaises(HTTPException):
            self.state(status="pending")


class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()
        with main.db() as conn:
            self.account_id = conn.execute(
                "SELECT id FROM accounts ORDER BY id LIMIT 1"
            ).fetchone()["id"]

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def add_bill(self, name, amount, cycle="monthly", anchor_month=None, day=10):
        return ledger_api.add_recurring_bill(ledger_api.RecurringBillIn(
            name=name, amount=amount, day_of_month=day, cycle=cycle,
            anchor_month=anchor_month, category="digital", account_id=self.account_id,
        ))

    def test_yearly_cost_is_normalised_to_a_monthly_figure(self):
        self.add_bill("视频会员", 30.0, "monthly")
        self.add_bill("云盘", 120.0, "yearly", anchor_month=3)
        with main.db() as conn:
            overview = ledger.get_subscription_overview(conn)

        by_name = {item["name"]: item for item in overview["items"]}
        self.assertEqual(by_name["云盘"]["monthly_cost"], 10.0)
        self.assertEqual(by_name["云盘"]["yearly_cost"], 120.0)
        self.assertEqual(overview["summary"]["monthly_total"], 40.0)
        self.assertEqual(overview["summary"]["yearly_total"], 480.0)

    def test_monthly_cost_is_labelled_as_a_conversion(self):
        with main.db() as conn:
            overview = ledger.get_subscription_overview(conn)
        self.assertIn("换算值", overview["note"])

    def test_yearly_bill_only_shows_in_its_anchor_month(self):
        """否则日历会月月提醒一笔并不会扣的钱。"""
        bill = {"cycle": "yearly", "anchor_month": 3, "day_of_month": 10}
        self.assertTrue(ledger.bill_due_in_month(bill, 2026, 3))
        self.assertFalse(ledger.bill_due_in_month(bill, 2026, 4))
        self.assertTrue(ledger.bill_due_in_month(bill, 2027, 3))

    def test_quarterly_bill_repeats_every_three_months(self):
        bill = {"cycle": "quarterly", "anchor_month": 2, "day_of_month": 10}
        for month, expected in ((2, True), (3, False), (5, True), (8, True), (11, True)):
            with self.subTest(month=month):
                self.assertEqual(ledger.bill_due_in_month(bill, 2026, month), expected)

    def test_missing_anchor_falls_back_to_every_month(self):
        """宁可多提醒，不要漏提醒。"""
        bill = {"cycle": "yearly", "anchor_month": None, "day_of_month": 10}
        self.assertTrue(ledger.bill_due_in_month(bill, 2026, 4))

    def test_existing_monthly_bills_keep_their_meaning(self):
        self.add_bill("房租", 1500.0)
        with main.db() as conn:
            calendar = ledger.get_financial_calendar(conn)
        self.assertEqual([item["name"] for item in calendar["bills"]], ["房租"])

    def test_creating_a_non_monthly_bill_defaults_the_anchor_to_this_month(self):
        self.add_bill("年费", 240.0, "yearly")
        with main.db() as conn:
            row = conn.execute("SELECT cycle, anchor_month FROM recurring_bills").fetchone()
        self.assertEqual(row["cycle"], "yearly")
        self.assertEqual(row["anchor_month"], date.today().month)

    def test_overview_sorts_by_how_soon_it_is_due(self):
        self.add_bill("先扣的", 10.0, day=1)
        self.add_bill("后扣的", 10.0, day=28)
        with main.db() as conn:
            overview = ledger.get_subscription_overview(conn)
        days = [item["days_until_due"] for item in overview["items"]]
        self.assertEqual(days, sorted(days))

    def test_empty_overview_reports_zero_not_none(self):
        with main.db() as conn:
            overview = ledger.get_subscription_overview(conn)
        self.assertEqual(overview["summary"]["count"], 0)
        self.assertEqual(overview["summary"]["monthly_total"], 0)


if __name__ == "__main__":
    unittest.main()
