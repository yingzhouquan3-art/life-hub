"""待确认捕获模块。

最重要的一条：捕获在用户确认之前不得影响任何数字。
其次是双通道去重——同一笔付款可能同时触发微信通知和银行短信。
"""
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.api import capture as capture_api
from backend.core import db as db_core
from backend.modules import capture, ledger


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()
        self.moment = datetime.now().replace(microsecond=0)

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def record(self, conn, *, channel="wechat_notification", amount=16.5, offset_seconds=0,
               raw_text="微信支付 你已成功付款16.50元", **kwargs):
        return capture.record_capture(
            conn, channel=channel, raw_text=raw_text, amount=amount,
            occurred_at=(self.moment + timedelta(seconds=offset_seconds)).isoformat(),
            **kwargs,
        )

    # ---------- 核心不变量 ----------

    def test_pending_capture_does_not_touch_any_statistic(self):
        with main.db() as conn:
            before = ledger.compute_stats(conn)
            before_month = ledger.compute_monthly(conn)
            before_today = ledger.get_today_overview(conn)

            self.record(conn, amount=88.0)

            self.assertEqual(ledger.compute_stats(conn), before)
            self.assertEqual(ledger.compute_monthly(conn), before_month)
            self.assertEqual(ledger.get_today_overview(conn), before_today)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0], 0,
                "捕获不能自己创建交易",
            )

    def test_confirming_creates_the_transaction_and_only_then_counts(self):
        with main.db() as conn:
            created = self.record(conn, amount=16.5)["capture"]
            self.assertEqual(created["status"], "pending")

        # 路由自己开连接，所以要先让上面的写入提交
        result = capture_api.confirm_capture(
            created["id"], capture_api.CaptureConfirmIn(category="food"),
        )

        self.assertEqual(result["capture"]["status"], "confirmed")
        self.assertEqual(result["transaction"]["amount"], 16.5)
        self.assertEqual(result["transaction"]["category"], "food")
        self.assertEqual(result["capture"]["transaction_id"], result["transaction"]["id"])
        self.assertEqual(result["today"]["today_expense"], 16.5)

    def test_confirmed_capture_cannot_be_confirmed_twice(self):
        with main.db() as conn:
            created = self.record(conn)["capture"]
            transaction = ledger.create_transaction(conn, type="expense", amount=16.5)
            capture.mark_capture_confirmed(conn, created["id"], transaction["id"])
            with self.assertRaises(HTTPException):
                capture.mark_capture_confirmed(conn, created["id"], transaction["id"])

    # ---------- 双通道去重 ----------

    def test_same_amount_within_window_merges_and_keeps_both_sources(self):
        with main.db() as conn:
            first = self.record(conn, channel="wechat_notification", amount=16.5)
            second = self.record(
                conn, channel="bank_sms", amount=16.5, offset_seconds=30,
                raw_text="您尾号1234的卡消费16.50元",
            )

            self.assertFalse(first["merged"])
            self.assertTrue(second["merged"], "60 秒内的同额扣款应当合并")
            self.assertEqual(first["capture"]["id"], second["capture"]["id"])
            self.assertEqual(
                {hit["channel"] for hit in second["capture"]["channels"]},
                {"wechat_notification", "bank_sms"},
                "合并后必须保留两个来源，便于事后判断哪条通道还活着",
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM pending_captures").fetchone()[0], 1,
            )

    def test_outside_the_window_stays_separate(self):
        with main.db() as conn:
            self.record(conn, amount=16.5)
            second = self.record(conn, channel="bank_sms", amount=16.5, offset_seconds=61)
            self.assertFalse(second["merged"])
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM pending_captures").fetchone()[0], 2,
            )

    def test_different_amount_stays_separate(self):
        with main.db() as conn:
            self.record(conn, amount=16.5)
            second = self.record(conn, channel="bank_sms", amount=16.6, offset_seconds=5)
            self.assertFalse(second["merged"])

    def test_dismissed_capture_does_not_absorb_new_ones(self):
        with main.db() as conn:
            created = self.record(conn, amount=16.5)["capture"]
            capture.dismiss_capture(conn, created["id"])
            second = self.record(conn, channel="bank_sms", amount=16.5, offset_seconds=10)
            self.assertFalse(second["merged"], "刚划掉的捕获不该把新事件重新吸回去")

    def test_merge_fills_in_missing_merchant_without_overwriting(self):
        with main.db() as conn:
            first = self.record(conn, amount=16.5, merchant="")
            self.record(conn, channel="bank_sms", amount=16.5, offset_seconds=5, merchant="星巴克")
            filled = capture.get_capture(conn, first["capture"]["id"])
            self.assertEqual(filled["merchant"], "星巴克")

            second = self.record(conn, amount=30.0, offset_seconds=600, merchant="食堂")
            self.record(conn, channel="bank_sms", amount=30.0, offset_seconds=605, merchant="别的")
            kept = capture.get_capture(conn, second["capture"]["id"])
            self.assertEqual(kept["merchant"], "食堂", "已有商户名不该被后到的覆盖")

    # ---------- 输入校验 ----------

    def test_invalid_input_is_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                capture.record_capture(conn, channel="telepathy", raw_text="x", amount=1)
            with self.assertRaises(HTTPException):
                capture.record_capture(conn, channel="manual", raw_text="x", amount=0)
            with self.assertRaises(HTTPException):
                capture.record_capture(conn, channel="manual", raw_text="   ", amount=1)
            with self.assertRaises(HTTPException):
                capture.record_capture(
                    conn, channel="manual", raw_text="x", amount=1, occurred_at="昨天下午",
                )

    # ---------- 覆盖率 ----------

    def test_coverage_counts_only_confirmed_captures(self):
        month = date.today().strftime("%Y-%m")
        with main.db() as conn:
            ledger.create_transaction(conn, type="expense", amount=20, note="手动记的")
            created = self.record(conn, amount=16.5)["capture"]
            transaction = ledger.create_transaction(conn, type="expense", amount=16.5)
            capture.mark_capture_confirmed(conn, created["id"], transaction["id"])
            self.record(conn, amount=99.0, offset_seconds=900)  # 仍待确认

            coverage = capture.get_capture_coverage(conn, month)

        self.assertEqual(coverage["expense_transactions"], 2)
        self.assertEqual(coverage["from_capture"], 1)
        self.assertEqual(coverage["coverage"], 0.5)
        self.assertEqual(coverage["still_pending"], 1)

    def test_coverage_is_none_when_there_is_nothing_to_measure(self):
        with main.db() as conn:
            coverage = capture.get_capture_coverage(conn)
        self.assertIsNone(
            coverage["coverage"],
            "没有支出时覆盖率应当是未知，而不是 0——0 会被读成通道全挂了",
        )

    def test_coverage_rejects_bad_month(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                capture.get_capture_coverage(conn, "2026/08")

    # ---------- 汇总 ----------

    def test_state_summary_reports_channel_health(self):
        with main.db() as conn:
            self.record(conn, amount=16.5)
            self.record(conn, channel="bank_sms", amount=16.5, offset_seconds=20)
            self.record(conn, channel="manual", amount=42.0, offset_seconds=300)
            state = capture.get_capture_state(conn)

        self.assertEqual(state["summary"]["pending_count"], 2)
        self.assertEqual(state["summary"]["by_channel"]["wechat_notification"], 1)
        self.assertEqual(state["summary"]["by_channel"]["bank_sms"], 1)
        self.assertIsNotNone(state["summary"]["last_capture_at"])


if __name__ == "__main__":
    unittest.main()
