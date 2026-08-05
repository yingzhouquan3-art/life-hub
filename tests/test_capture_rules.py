"""通知与短信的解析规则。

解析错一个金额，用户就会去确认一个不存在的数字，比解析不出来危险得多。
所以这里的重点不是覆盖多少种文案，而是「宁可不认，也不能认错」。

注意：这些是按常见文案写的规则，没有对着真机验证过。
接入通知监听前应当先用真实原文跑 POST /api/capture/parse。
"""
import unittest

from backend.modules.capture_rules import describe_rules, parse_notification


class CaptureRuleTests(unittest.TestCase):
    def parse(self, text, channel="wechat_notification"):
        return parse_notification(text, channel)

    # ---------- 微信 ----------

    def test_wechat_payment(self):
        result = self.parse("微信支付 你已成功付款16.50元")
        self.assertTrue(result["matched"])
        self.assertEqual(result["amount"], 16.5)
        self.assertEqual(result["direction"], "expense")

    def test_wechat_receipt_is_income(self):
        result = self.parse("微信支付 已收款 ¥25.00")
        self.assertEqual(result["amount"], 25.0)
        self.assertEqual(result["direction"], "income")

    def test_merchant_is_extracted_when_present(self):
        result = self.parse("微信支付 向 星巴克 付款 ¥38.00")
        self.assertEqual(result["merchant"], "星巴克")

    # ---------- 银行短信 ----------

    def test_bank_sms_with_thousands_separator(self):
        """回归：卡号里的 1234 曾经被当成金额，1,234.56 元被读成 123 元。"""
        result = self.parse(
            "您尾号1234的储蓄卡于08月05日消费人民币1,234.56元", "bank_sms",
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["amount"], 1234.56)
        self.assertEqual(result["direction"], "expense")

    def test_bank_sms_income(self):
        result = self.parse("您尾号1234的储蓄卡08月05日收入人民币500.00元", "bank_sms")
        self.assertEqual(result["amount"], 500.0)
        self.assertEqual(result["direction"], "income")

    def test_card_number_alone_is_never_an_amount(self):
        result = self.parse("您尾号1234的储蓄卡状态已更新", "bank_sms")
        self.assertFalse(result["matched"], "只有卡号没有金额时必须放弃解析")

    # ---------- 宁可不认 ----------

    def test_plain_message_without_amount_is_not_matched(self):
        for text in ("你收到了一条新的消息", "你有3条未读消息", "微信运动 今天走了8000步"):
            with self.subTest(text=text):
                self.assertFalse(
                    self.parse(text)["matched"],
                    f"没有货币标记的数字不能当成金额：{text}",
                )

    def test_empty_text_is_not_matched(self):
        result = self.parse("   ")
        self.assertFalse(result["matched"])
        self.assertEqual(result["raw_text"], "")

    def test_date_is_never_taken_as_merchant(self):
        result = self.parse("于08月05日消费人民币12元", "bank_sms")
        self.assertTrue(result["matched"])
        self.assertEqual(result["merchant"], "", "日期不是商户名，宁可留空")

    def test_unmatched_result_carries_no_amount(self):
        result = self.parse("你收到了一条新的消息")
        self.assertNotIn("amount", result)
        self.assertIn("reason", result)

    # ---------- 规则清单 ----------

    def test_rules_are_described_for_debugging(self):
        rules = describe_rules()
        self.assertTrue(rules)
        for rule in rules:
            self.assertIn("key", rule)
            self.assertIn("pattern", rule)

    def test_fallback_rules_come_last(self):
        keys = [rule["key"] for rule in describe_rules()]
        fallbacks = {"amount_with_currency_mark", "amount_with_yuan_suffix"}
        specific = [i for i, key in enumerate(keys) if key not in fallbacks]
        generic = [i for i, key in enumerate(keys) if key in fallbacks]
        self.assertTrue(
            max(specific) < min(generic),
            "兜底规则必须排在具体规则之后，否则银行短信会被兜底规则先抢走",
        )


if __name__ == "__main__":
    unittest.main()
