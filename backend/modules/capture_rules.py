"""把支付通知与银行短信的原文解析成金额、方向和商户。

设计取舍：解析放在后端，手机端只负责把通知原文整条转发过来。
这样改规则不用重新配置手机，也能对着真实原文回归测试。

**这里的默认规则是按常见文案写的，没有对着真机验证过。**
微信、各家银行的文案会随版本变化，接入时应当先用真实通知跑一遍
`POST /api/capture/parse` 看解析结果，再决定是否要补规则。
解析不出来不是错误——返回 matched=false，让用户手动补录，
绝不猜一个金额写进账本。
"""
from __future__ import annotations

import re
from typing import Optional

# 数字本身。两侧的断言很关键：没有它们，"尾号1234" 里的 123 会被当成金额，
# 于是一笔 1234.56 元的扣款被读成 123 元——用户会去确认一个错的数字。
_NUMBER = r"(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?!\d)"

# 金额：允许 ¥ / 元 / RMB / 人民币 前后缀。命名组固定叫 amount。
_AMOUNT = rf"(?:¥|￥|RMB|人民币)?\s*(?P<amount>{_NUMBER})\s*元?"

# 兜底场景下必须带货币标记，否则任何一串数字都会被当成钱。
_AMOUNT_PREFIXED = rf"(?:¥|￥|RMB|人民币)\s*(?P<amount>{_NUMBER})"
_AMOUNT_SUFFIXED = rf"(?P<amount>{_NUMBER})\s*元"

# 支出与收入的方向词。命中收入词优先，因为「收款」里也含「款」。
_INCOME_HINTS = ("收款", "已收款", "入账", "转入", "退款", "收到", "到账")
_EXPENSE_HINTS = ("付款", "支付", "消费", "扣款", "支出", "转出", "已付")


class CaptureRule:
    """一条解析规则。

    pattern 里必须有名为 amount 的捕获组；merchant 可有可无。
    """

    def __init__(self, key: str, channel: str, pattern: str, direction: Optional[str] = None,
                 description: str = ""):
        self.key = key
        self.channel = channel
        self.regex = re.compile(pattern)
        self.direction = direction
        self.description = description

    def match(self, text: str) -> Optional[dict]:
        found = self.regex.search(text)
        if not found:
            return None
        groups = found.groupdict()
        raw_amount = groups.get("amount")
        if not raw_amount:
            return None
        return {
            "rule": self.key,
            "amount": float(raw_amount.replace(",", "")),
            "merchant": (groups.get("merchant") or "").strip(),
            "direction": self.direction,
        }


# 顺序即优先级：越靠前越具体，兜底规则必须放最后。
RULES: tuple[CaptureRule, ...] = (
    CaptureRule(
        "wechat_receive", "wechat_notification",
        rf"(?:已收款|收款|已到账)[^0-9]{{0,12}}{_AMOUNT}",
        direction="income",
        description="微信收款通知",
    ),
    CaptureRule(
        "wechat_pay_success", "wechat_notification",
        rf"(?:已成功付款|支付成功|已付款|微信支付)[^0-9]{{0,12}}{_AMOUNT}",
        direction="expense",
        description="微信支付成功通知",
    ),
    # 卡号与动词之间常夹着日期（"尾号1234的储蓄卡于08月05日消费"），
    # 所以这里用非贪婪的任意字符，不能禁止数字。
    CaptureRule(
        "bank_card_income", "bank_sms",
        rf"(?:尾号|卡号)\s*(?P<card>\d{{3,4}}).{{0,30}}?(?:收入|转入|入账|退款).{{0,10}}?{_AMOUNT}",
        direction="income",
        description="银行卡入账短信",
    ),
    CaptureRule(
        "bank_card_spend", "bank_sms",
        rf"(?:尾号|卡号)\s*(?P<card>\d{{3,4}}).{{0,30}}?(?:消费|支出|支付|扣款).{{0,10}}?{_AMOUNT}",
        direction="expense",
        description="银行卡消费短信",
    ),
    CaptureRule(
        "amount_with_currency_mark", "other",
        _AMOUNT_PREFIXED,
        direction=None,
        description="兜底：带 ¥ / 人民币 前缀的金额",
    ),
    CaptureRule(
        "amount_with_yuan_suffix", "other",
        _AMOUNT_SUFFIXED,
        direction=None,
        description="兜底：带「元」后缀的金额",
    ),
)

# 商户名常见写法：「商户名称：星巴克」「向 星巴克 付款」「在星巴克消费」
_MERCHANT_PATTERNS = (
    r"商户(?:名称)?[：:]\s*(?P<merchant>[^\s，,。;；]{1,20})",
    r"向\s*(?P<merchant>[^\s，,。;；]{1,20})\s*(?:付款|转账|支付)",
    r"(?:在|于)\s*(?P<merchant>[^\s，,。;；]{1,20})\s*(?:消费|支付|付款)",
)


def guess_direction(text: str, fallback: Optional[str]) -> str:
    """先看收入词再看支出词；都没有就用规则自带的方向，最后默认支出。"""
    if any(hint in text for hint in _INCOME_HINTS):
        return "income"
    if any(hint in text for hint in _EXPENSE_HINTS):
        return "expense"
    return fallback or "expense"


# 日期、金额、卡号都可能落进商户位；它们不是商户名，宁可留空。
_NOT_A_MERCHANT = re.compile(r"^[\d\s.,:：年月日号元¥￥-]+$")


def guess_merchant(text: str) -> str:
    for pattern in _MERCHANT_PATTERNS:
        found = re.search(pattern, text)
        if not found:
            continue
        candidate = found.group("merchant").strip()
        if candidate and not _NOT_A_MERCHANT.match(candidate):
            return candidate
    return ""


def parse_notification(text: str, channel: Optional[str] = None) -> dict:
    """解析一条通知原文。

    解析不出金额时返回 matched=False，不猜测、不填默认值。
    """
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return {"matched": False, "reason": "通知内容为空", "raw_text": ""}

    candidates = [rule for rule in RULES if channel is None or rule.channel in (channel, "other")]
    for rule in candidates:
        hit = rule.match(cleaned)
        if not hit:
            continue
        if hit["amount"] <= 0:
            continue
        merchant = hit["merchant"] or guess_merchant(cleaned)
        return {
            "matched": True,
            "raw_text": cleaned,
            "rule": rule.key,
            "rule_description": rule.description,
            "channel": channel or rule.channel,
            "amount": round(hit["amount"], 2),
            "direction": guess_direction(cleaned, hit["direction"]),
            "merchant": merchant,
        }

    return {
        "matched": False,
        "reason": "没有从通知里认出金额，请手动补录",
        "raw_text": cleaned,
    }


def describe_rules() -> list[dict]:
    """给前端和调试用：当前生效的规则清单。"""
    return [
        {"key": rule.key, "channel": rule.channel, "direction": rule.direction,
         "description": rule.description, "pattern": rule.regex.pattern}
        for rule in RULES
    ]
