"""解析本平台自己的账目模板（date,type,amount,category,source,note,account）。

这份格式原本只在浏览器里解析，于是「导入」这件事分成了两套：微信、支付宝、
运动数据走后端，自己的表格走前端。带来的实际后果是同一个动作有两个入口，
而且前端那条路吃不到后端已经做好的东西——读 Excel、猜分类、逐行列出
没写进去的行。

搬到后端之后三件事一起解决：入口合成一个、能导 .xlsx、和别的格式共用
同一套预览与对账。

**列名不写死顺序**，按表头认；日期和金额是必需的，其余可缺。
认不出的行不猜，放进 skipped 并写明第几行、为什么——
「导入完少了几笔却不知道少了哪几笔」是对账最难受的状态。
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Optional

from backend.core.config import EXPENSE_CATEGORIES

# 一列可能出现的多种叫法。和前端原来那份保持一致，加一种写法只要往这里补。
_ALIASES = {
    "date": ("date", "日期", "交易日期", "occurred_on"),
    "type": ("type", "类型", "收支", "收支类型", "交易类型"),
    "amount": ("amount", "金额", "交易金额"),
    "category": ("category", "分类", "支出分类"),
    "source": ("source", "来源", "收入来源"),
    "note": ("note", "备注", "摘要", "交易说明"),
    "account": ("account", "账户", "账户名称"),
}

_INCOME_WORDS = ("income", "收入", "入账", "入")
_EXPENSE_WORDS = ("expense", "支出", "消费", "出账", "出")

INCOME_SOURCES = ("family_support", "scholarship", "part_time",
                  "project", "investment", "other")

# 中文标签也认，用户多半直接照着界面上的字写
_CATEGORY_LABELS = {
    "餐饮": "food", "交通": "transport", "学习": "study", "住宿": "housing",
    "居住": "housing", "医疗": "medical", "娱乐": "entertainment",
    "社交": "social", "数字服务": "digital", "其他": "other",
}
_SOURCE_LABELS = {
    "家庭生活费": "family_support", "奖助学金": "scholarship", "兼职实习": "part_time",
    "个人项目": "project", "投资所得": "investment", "其他": "other",
}

_DATE_PATTERNS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")
_AMOUNT_NOISE = re.compile(r"[¥￥,\s]")


def _normalise_header(value: str) -> str:
    return str(value or "").replace("﻿", "").strip().lower()


def _parse_day(raw: str) -> Optional[str]:
    text = (raw or "").strip()
    if not text:
        return None
    # 带时间的也接受，只取日期部分
    text = text.split(" ")[0].split("T")[0]
    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> Optional[float]:
    text = _AMOUNT_NOISE.sub("", raw or "")
    if not text:
        return None
    # 会计里用括号表示负数：(12.00) 就是 -12.00
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _read_rows(text: str) -> list[list[str]]:
    sample = text.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(sample[:2000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(sample), dialect) if any(cell.strip() for cell in row)]


def looks_like_template(text: str) -> bool:
    """表头里同时有日期和金额，且不像微信/支付宝账单，就当成本平台模板。"""
    rows = _read_rows(text[:4000])
    if not rows:
        return False
    headers = {_normalise_header(cell) for cell in rows[0]}
    has_date = bool(headers & {a.lower() for a in _ALIASES["date"]})
    has_amount = bool(headers & {a.lower() for a in _ALIASES["amount"]})
    return has_date and has_amount


def parse_template(text: str, default_account_id: Optional[int] = None,
                   accounts: Optional[dict] = None) -> dict:
    """把模板 CSV 解析成和账单解析器同样形状的结果。

    accounts 是 {账户名小写: id}，用来把「账户」那一列翻译成账户 id；
    认不出的账户名不猜，落回默认账户并在该行注明。
    """
    rows = _read_rows(text)
    if len(rows) < 2:
        return {"rows": [], "review": [],
                "skipped": [{"line": 1, "reason": "这个文件只有表头，没有数据行"}],
                "summary": {"parsed": 0, "skipped": 1}}

    headers = [_normalise_header(cell) for cell in rows[0]]
    index = {}
    for key, names in _ALIASES.items():
        lowered = [n.lower() for n in names]
        index[key] = next((i for i, h in enumerate(headers) if h in lowered), -1)

    if index["date"] < 0 or index["amount"] < 0:
        return {"rows": [], "review": [],
                "skipped": [{"line": 1, "reason": "表头里必须有日期/date 和金额/amount 两列"}],
                "summary": {"parsed": 0, "skipped": 1}}

    accounts = accounts or {}
    parsed: list[dict] = []
    skipped: list[dict] = []

    def cell(row, key):
        position = index[key]
        return str(row[position]).strip() if 0 <= position < len(row) else ""

    for number, row in enumerate(rows[1:], start=2):
        occurred_on = _parse_day(cell(row, "date"))
        if not occurred_on:
            skipped.append({"line": number, "reason": f"日期认不出：{cell(row, 'date') or '（空）'}"})
            continue
        amount = _parse_amount(cell(row, "amount"))
        if amount is None or amount == 0:
            skipped.append({"line": number, "reason": f"金额必须是非零数字，读到的是「{cell(row, 'amount')}」"})
            continue

        type_text = cell(row, "type").lower()
        kind = None
        if any(word == type_text for word in _INCOME_WORDS):
            kind = "income"
        elif any(word == type_text for word in _EXPENSE_WORDS):
            kind = "expense"
        elif amount < 0:
            # 负数按支出处理，这是表格里最常见的写法
            kind = "expense"
        if not kind:
            skipped.append({"line": number, "reason": "认不出这一行是收入还是支出，请填「收入」或「支出」"})
            continue

        category_text = cell(row, "category")
        source_text = cell(row, "source")
        notes = []
        category = None
        source = None
        if kind == "expense":
            category = _CATEGORY_LABELS.get(category_text, category_text if category_text in EXPENSE_CATEGORIES else None)
            if category_text and category is None:
                notes.append(f"认不出分类「{category_text}」，先记成其他")
                category = "other"
            category = category or "other"
        else:
            source = _SOURCE_LABELS.get(source_text, source_text if source_text in INCOME_SOURCES else None)
            if source_text and source is None:
                notes.append(f"认不出收入来源「{source_text}」，先记成家庭生活费")
            source = source or "family_support"

        account_text = cell(row, "account")
        account_id = default_account_id
        if account_text:
            found = accounts.get(account_text.lower())
            if found:
                account_id = found
            else:
                notes.append(f"没有叫「{account_text}」的账户，先记到默认账户")

        parsed.append({
            "line": number,
            "occurred_on": occurred_on,
            "type": kind,
            "amount": round(abs(amount), 2),
            "category": category,
            "source": source,
            "account_id": account_id,
            "note": cell(row, "note"),
            "note_hint": "；".join(notes),
        })

    return {
        "rows": parsed,
        "review": [],
        "skipped": skipped,
        "summary": {
            "parsed": len(parsed),
            "skipped": len(skipped),
            "date_from": min((r["occurred_on"] for r in parsed), default=None),
            "date_to": max((r["occurred_on"] for r in parsed), default=None),
        },
    }
