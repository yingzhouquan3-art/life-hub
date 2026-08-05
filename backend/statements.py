"""微信 / 支付宝月度账单的解析与对账。

通知监听是「尽力而为」的加速通道，月度账单才是权威事实。两者的关系是：

- 平时靠捕获和手记，覆盖当下；
- 月末导入账单，和已有交易比对，**只补差额，不重复入账**；
- 顺便算出这段时间到底漏了多少，用来判断监听通道是不是悄悄挂了。

账单文件的列名各版本略有差异，所以这里不写死列序：先找到表头行
（含「交易时间」与金额列的那一行），再按列名取值。识别不了的行不猜，
放进 skipped 让用户自己看。

**这些格式是按公开的导出样式写的，没有对着真实账单验证过。**
第一次导入请先看预览，确认条数与金额对得上再确认写入。
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Iterable, Optional

from fastapi import HTTPException

SOURCES = {
    "wechat": "微信支付账单",
    "alipay": "支付宝账单",
}

# 表头识别：这一行必须同时有时间列和金额列
_TIME_COLUMNS = ("交易时间", "交易创建时间", "付款时间")
_AMOUNT_COLUMNS = ("金额(元)", "金额", "金额（元）", "发生金额")
_DIRECTION_COLUMNS = ("收/支", "收支", "收/付款", "资金流向")
_COUNTERPARTY_COLUMNS = ("交易对方", "对方账号", "商户名称")
_ITEM_COLUMNS = ("商品", "商品说明", "商品名称", "交易分类")
_STATUS_COLUMNS = ("当前状态", "交易状态")

# 这些状态的记录不是一笔真实支出：退款成功、已全额退款、交易关闭等
_SKIP_STATUS = ("已关闭", "交易关闭", "已退款", "全额退款", "退款成功", "已撤销", "支付失败")


def _pick(row: dict, names: Iterable[str]) -> str:
    for name in names:
        if name in row and (row[name] or "").strip():
            return row[name].strip()
    return ""


def detect_source(text: str) -> Optional[str]:
    head = text[:2000]
    if "微信支付" in head or "微信昵称" in head:
        return "wechat"
    if "支付宝" in head or "淘宝" in head and "交易号" in head:
        return "alipay"
    return None


def _find_header(rows: list[list[str]]) -> int:
    for index, row in enumerate(rows):
        cells = [cell.strip() for cell in row]
        has_time = any(any(name in cell for name in _TIME_COLUMNS) for cell in cells)
        has_amount = any(any(name in cell for name in _AMOUNT_COLUMNS) for cell in cells)
        if has_time and has_amount:
            return index
    raise HTTPException(400, "找不到账单表头。请确认导出的是明细 CSV，不是汇总或图片")


def _parse_amount(raw: str) -> Optional[float]:
    cleaned = re.sub(r"[¥￥,\s]", "", raw or "")
    if not cleaned:
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return abs(round(value, 2))


def _parse_day(raw: str) -> Optional[str]:
    found = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", raw or "")
    if not found:
        return None
    try:
        return date(int(found.group(1)), int(found.group(2)), int(found.group(3))).isoformat()
    except ValueError:
        return None


def parse_statement(text: str, source: Optional[str] = None) -> dict:
    """把账单原文解析成统一的行。只读，不碰数据库。"""
    if not (text or "").strip():
        raise HTTPException(400, "账单内容为空")
    source = source or detect_source(text)
    if source not in SOURCES:
        raise HTTPException(400, "认不出这是哪家的账单，请手动指定 source")

    rows = list(csv.reader(io.StringIO(text)))
    header_index = _find_header(rows)
    header = [cell.strip() for cell in rows[header_index]]

    parsed: list[dict] = []
    skipped: list[dict] = []
    for line_number, raw_row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any((cell or "").strip() for cell in raw_row):
            continue
        row = {header[i]: (raw_row[i] if i < len(raw_row) else "") for i in range(len(header))}

        status = _pick(row, _STATUS_COLUMNS)
        if any(word in status for word in _SKIP_STATUS):
            skipped.append({"line": line_number, "reason": f"状态为「{status}」，不是一笔实际支出"})
            continue

        occurred_on = _parse_day(_pick(row, _TIME_COLUMNS))
        amount = _parse_amount(_pick(row, _AMOUNT_COLUMNS))
        if not occurred_on or amount is None or amount <= 0:
            skipped.append({"line": line_number, "reason": "认不出日期或金额"})
            continue

        direction = _pick(row, _DIRECTION_COLUMNS)
        if "收入" in direction:
            kind = "income"
        elif "支出" in direction:
            kind = "expense"
        else:
            skipped.append({"line": line_number, "reason": f"收支方向不明（「{direction or '空'}」）"})
            continue

        counterparty = _pick(row, _COUNTERPARTY_COLUMNS)
        item = _pick(row, _ITEM_COLUMNS)
        note = " ".join(part for part in (counterparty, item) if part)[:120]

        parsed.append({
            "occurred_on": occurred_on,
            "type": kind,
            "amount": amount,
            "note": note or SOURCES[source],
            "counterparty": counterparty,
            "line": line_number,
        })

    return {
        "source": source,
        "source_label": SOURCES[source],
        "rows": parsed,
        "skipped": skipped,
        "summary": {
            "parsed": len(parsed),
            "skipped": len(skipped),
            "expense": round(sum(r["amount"] for r in parsed if r["type"] == "expense"), 2),
            "income": round(sum(r["amount"] for r in parsed if r["type"] == "income"), 2),
            "date_from": min((r["occurred_on"] for r in parsed), default=None),
            "date_to": max((r["occurred_on"] for r in parsed), default=None),
        },
    }


def reconcile(conn, rows: list[dict]) -> dict:
    """把账单行和已有交易比对，分出「已经记过」和「还没记」。

    匹配规则：同一天 + 金额相同 + 同一方向。一笔已有交易只能被认领一次，
    否则同一天两笔 12 元会被一笔账单行同时认领，漏掉真正缺的那条。

    匹配不上只表示账本里没有对得上的记录，不代表这笔钱一定没记
    （比如日期填错了一天），所以结果给用户确认，不自动写入。
    """
    if not rows:
        return {"new": [], "matched": [], "summary": {"new": 0, "matched": 0, "new_amount": 0.0}}

    days = sorted({row["occurred_on"] for row in rows})
    existing = conn.execute(
        """SELECT id, occurred_on, type, amount, note FROM transactions
           WHERE occurred_on BETWEEN ? AND ? ORDER BY id""",
        (days[0], days[-1]),
    ).fetchall()

    pool: dict[tuple, list[dict]] = {}
    for record in existing:
        key = (record["occurred_on"], record["type"], round(float(record["amount"]), 2))
        pool.setdefault(key, []).append(dict(record))

    new_rows: list[dict] = []
    matched: list[dict] = []
    for row in rows:
        key = (row["occurred_on"], row["type"], row["amount"])
        bucket = pool.get(key)
        if bucket:
            claimed = bucket.pop(0)
            matched.append({**row, "transaction_id": claimed["id"], "existing_note": claimed["note"]})
        else:
            new_rows.append(row)

    return {
        "new": new_rows,
        "matched": matched,
        "summary": {
            "new": len(new_rows),
            "matched": len(matched),
            "new_amount": round(sum(r["amount"] for r in new_rows), 2),
            "matched_amount": round(sum(r["amount"] for r in matched), 2),
            "date_from": days[0],
            "date_to": days[-1],
        },
    }


def build_preview(conn, text: str, source: Optional[str] = None) -> dict:
    """解析 + 对账，一次给出可确认的预览。全程只读。"""
    parsed = parse_statement(text, source)
    result = reconcile(conn, parsed["rows"])
    return {
        **parsed,
        "reconciliation": result,
        "generated_at": datetime.now().isoformat(),
        "note": "只有「还没记」的行会写入账本；「已经记过」的行不会重复入账。",
    }
