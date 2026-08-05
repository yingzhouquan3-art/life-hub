import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core


class DailyLoopTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()
        now = datetime.now().isoformat()
        with main.db() as conn:
            conn.execute(
                """INSERT INTO settings
                   (id, birth_date, target_age, currency, show_past, created_at,
                    initial_assets, use_initial_assets, tracking_days_override, avg_daily_expense_override)
                   VALUES (1, '2005-01-01', 80, 'CNY', 0, ?, 0, 0, 0, 0)""",
                (now,),
            )
            conn.execute(
                "INSERT INTO accounts (name, type, opening_balance, is_active, created_at) VALUES ('支付宝', 'alipay', 500, 1, ?)",
                (now,),
            )
            conn.execute(
                "INSERT INTO accounts (name, type, opening_balance, is_active, created_at) VALUES ('银行卡', 'bank', 1000, 1, ?)",
                (now,),
            )

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def test_quick_entry_parses_without_writing(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with main.db() as conn:
            expense = main.parse_quick_entry(conn, "昨天午饭 16.5 支付宝")
            income = main.parse_quick_entry(conn, "奖学金 2000 银行卡")
            count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]

        self.assertEqual(expense["transaction"]["type"], "expense")
        self.assertEqual(expense["transaction"]["category"], "food")
        self.assertEqual(expense["transaction"]["account_name"], "支付宝")
        self.assertEqual(expense["transaction"]["occurred_on"], yesterday)
        self.assertEqual(income["transaction"]["type"], "income")
        self.assertEqual(income["transaction"]["source"], "scholarship")
        self.assertEqual(income["transaction"]["account_name"], "银行卡")
        self.assertEqual(count, 0)

    def test_quick_entry_rejects_missing_amount(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                main.parse_quick_entry(conn, "今天午饭 支付宝")
            count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        self.assertEqual(count, 0)

    def test_semester_budget_drives_today_without_creating_income(self):
        today = date.today()
        response = main.set_semester_settings(main.SemesterSettingsIn(
            start_date=(today - timedelta(days=30)).isoformat(),
            end_date=(today + timedelta(days=60)).isoformat(),
            total_budget=9000,
            mode="in_school",
        ))
        with main.db() as conn:
            account_id = conn.execute("SELECT id FROM accounts WHERE name = '支付宝'").fetchone()[0]
            conn.execute(
                """INSERT INTO transactions
                   (occurred_on, type, source, category, account_id, amount, note, created_at)
                   VALUES (?, 'expense', 'expense', 'food', ?, 100, '测试隔离支出', ?)""",
                (today.isoformat(), account_id, datetime.now().isoformat()),
            )
            semester = main.get_semester(conn)
            overview = main.get_today_overview(conn)
            income_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE type = 'income'").fetchone()[0]

        self.assertTrue(response["planning"]["semester"]["configured"])
        self.assertEqual(semester["actual_expense"], 100)
        self.assertEqual(semester["remaining_budget"], 8900)
        self.assertEqual(overview["today_expense"], 100)
        self.assertIsNotNone(overview["available_today"])
        self.assertEqual(income_count, 0)

    def test_legacy_snapshot_without_semester_table_still_restores(self):
        with main.db() as conn:
            snapshot = main.build_snapshot(conn)
        snapshot["tables"].pop("semester_settings")
        result = main.restore_backup(main.RestoreSnapshotIn(snapshot=snapshot, confirmation="RESTORE"))
        self.assertTrue(result["restored"])
        with main.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM semester_settings").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
