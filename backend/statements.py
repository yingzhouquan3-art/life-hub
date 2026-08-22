"""微信 / 支付宝月度账单的解析与对账。

通知监听是「尽力而为」的加速通道，月度账单才是权威事实。两者的关系是：

- 平时靠捕获和手记，覆盖当下；
- 月末导入账单，和已有交易比对，**只补差额，不重复入账**；
- 顺便算出这段时间到底漏了多少，用来判断监听通道是不是悄悄挂了。

账单文件的列名各版本略有差异，所以这里不写死列序：先找到表头行
（含「交易时间」与金额列的那一行），再按列名取值。识别不了的行不猜，
放进 skipped 让用户自己看。

列名、状态取值与那些「凭猜想不到」的怪癖，参照 china_bean_importers
对真实账单的处理校准过：https://github.com/jiegec/china_bean_importers
（微信的斜杠占位、空的收/支列、支付宝的「不计收支」与尾部分隔线等。）

仍然**没有对你自己的账单验证过**——各人导出的版本可能不同。
第一次导入请先看预览，确认条数与金额对得上再确认写入。
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Iterable, Optional

from fastapi import HTTPException

from backend.modules.categorize import suggest_category

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


def _pick(row: dict, names: Iterable[str]) -> str:
    """按列名依次取值，取到第一个非空的。列名各版本略有差异，所以不写死列序。"""
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

# 微信把「没有对方 / 没有商品」写成一个斜杠，不是真的内容
_PLACEHOLDER = "/"

# 微信有些交易的「收/支」列就是一个斜杠，方向要从交易类型推。
# 这些映射来自 china_bean_importers 对真实账单的处理。
_WECHAT_DIRECTION_BY_TYPE = (
    ("信用卡还款", "expense"),
    ("零钱提现", "expense"),
    ("零钱充值", "income"),
)

# 支付宝除了收入/支出，还有「不计收支」和「其他」：
# 余额宝转入转出、花呗还款、退款都落在这里。
# 它们是真实的资金变动，不能当成噪声丢掉，但方向也不该由系统猜——
# 一律放进「需要你判断」，由用户在预览里决定。
_UNCLEAR_DIRECTIONS = ("不计收支", "其他")

# 微信把「这笔退掉了」写成原交易的状态：整笔退掉就等于没花过，可以跳过。
# 但「已退款(¥5.00)」是部分退款，原来那笔钱确实花掉了一部分，整行丢掉会少记。
_WECHAT_FULLY_REFUNDED = ("已全额退款", "全额退款")

# 支付宝不一样：退款是**单独一行收入**，原来那笔支出仍然留在账单里。
# 把这行跳过会变成「支出照算、退款不算」，账目偏高。所以交给用户判断。
_REFUND_MARKERS = ("退款", "退回")

_CLOSED_STATUS = ("已关闭", "交易关闭", "已撤销", "支付失败", "交易失败")


def _clean(value: str) -> str:
    """把占位斜杠当成空。"""
    text = (value or "").strip()
    return "" if text == _PLACEHOLDER else text


def _resolve_direction(row: dict, source: str) -> tuple[str, str]:
    """返回（方向, 说明）。方向为 expense / income / unclear。"""
    raw = _clean(_pick(row, _DIRECTION_COLUMNS))
    if "支出" in raw:
        return "expense", ""
    if "收入" in raw:
        return "income", ""

    kind = _pick(row, ("交易类型", "交易分类"))
    if source == "wechat":
        for keyword, direction in _WECHAT_DIRECTION_BY_TYPE:
            if keyword in kind:
                return direction, f"「收/支」为空，按交易类型「{kind}」判为{'支出' if direction == 'expense' else '收入'}"
    if raw in _UNCLEAR_DIRECTIONS or not raw:
        return "unclear", f"账单把它标成「{raw or '空'}」，需要你判断是收入还是支出"
    return "unclear", f"收支方向「{raw}」认不出来"


def parse_statement(text: str, source: Optional[str] = None) -> dict:
    """把账单原文解析成统一的行。只读，不碰数据库。

    列名与状态取值参照 china_bean_importers 对真实账单的处理：
    https://github.com/jiegec/china_bean_importers
    """
    if not (text or "").strip():
        raise HTTPException(400, "账单内容为空")
    source = source or detect_source(text)
    if source not in SOURCES:
        raise HTTPException(400, "认不出这是哪家的账单，请手动指定 source")

    rows = list(csv.reader(io.StringIO(text)))
    header_index = _find_header(rows)
    header = [cell.strip() for cell in rows[header_index]]

    parsed: list[dict] = []
    review: list[dict] = []
    skipped: list[dict] = []
    for line_number, raw_row in enumerate(rows[header_index + 1:], start=header_index + 2):
        if not any((cell or "").strip() for cell in raw_row):
            continue
        # 支付宝导出的明细后面还有一段分隔线和汇总，遇到就停，
        # 否则会产生一堆「认不出日期或金额」的噪声。
        if (raw_row[0] or "").strip().startswith("---"):
            break
        row = {header[i]: (raw_row[i] if i < len(header) else "") for i in range(len(header))}

        occurred_on = _parse_day(_pick(row, _TIME_COLUMNS))
        amount = _parse_amount(_pick(row, _AMOUNT_COLUMNS))
        if not occurred_on or amount is None or amount <= 0:
            skipped.append({"line": line_number, "reason": "认不出日期或金额"})
            continue

        status = _pick(row, _STATUS_COLUMNS)
        if any(word in status for word in _CLOSED_STATUS):
            skipped.append({"line": line_number, "reason": f"状态为「{status}」，交易没有真的发生"})
            continue
        if source == "wechat" and any(word in status for word in _WECHAT_FULLY_REFUNDED):
            skipped.append({
                "line": line_number,
                "reason": f"状态为「{status}」，整笔已退，这笔钱没有真的花出去",
            })
            continue

        direction, note = _resolve_direction(row, source)

        # 支付宝的退款是单独一行，钱是退回来的。方向由用户确认，
        # 不能当噪声丢掉——丢掉就变成支出照算、退款不算。
        kind = _pick(row, ("交易类型", "交易分类"))
        looks_like_refund = any(
            word in status or word in kind for word in _REFUND_MARKERS
        )
        if source == "alipay" and looks_like_refund and direction != "expense":
            direction = "unclear"
            note = f"看起来是一笔退款（{status or kind}），退回的钱通常算收入，请确认"

        counterparty = _clean(_pick(row, _COUNTERPARTY_COLUMNS))
        item = _clean(_pick(row, _ITEM_COLUMNS))
        summary = " ".join(part for part in (counterparty, item) if part)[:120]

        entry = {
            "occurred_on": occurred_on,
            "type": "expense" if direction == "expense" else "income",
            "amount": amount,
            "note": summary or SOURCES[source],
            "counterparty": counterparty,
            "status": status,
            "line": line_number,
        }

        if direction == "unclear":
            # 部分退款也走这里：钱确实动了一部分，但金额要由用户核对
            review.append({**entry, "reason": note})
            continue
        if note:
            entry["note_hint"] = note
        parsed.append(entry)

    return {
        "source": source,
        "source_label": SOURCES[source],
        "rows": parsed,
        "review": review,
        "skipped": skipped,
        "summary": {
            "parsed": len(parsed),
            "review": len(review),
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


def apply_categories(conn, rows: list[dict]) -> dict:
    """给每一行猜一个支出分类，并说明依据。

    不猜就等于全部落进「其他」，那样导进来的几百笔在分类统计里毫无意义——
    一个说得出依据的猜测，比一个沉默的默认值有用。

    两条边界：
    - 收入行不参与，支出分类对它没有意义；
    - **不回写规则**。批量导入不是用户对每一行的确认，
      拿它去学习会让一次误判在几百行上自我强化。学习只发生在逐条确认时。
    """
    guessed = 0
    for row in rows:
        if row["type"] != "expense":
            continue
        hit = suggest_category(conn, row.get("note", ""))
        if not hit:
            continue
        row["category"] = hit["category"]
        row["category_by"] = hit["keyword"]
        guessed += 1
    return {
        "guessed": guessed,
        "unguessed": sum(1 for row in rows if row["type"] == "expense" and not row.get("category")),
        "note": "分类是按关键字猜的，写入前可以改；导入不会把这些猜测变成新规则。",
    }


def build_preview(conn, text: str, source: Optional[str] = None) -> dict:
    """解析 + 对账 + 猜分类，一次给出可确认的预览。全程只读。"""
    parsed = parse_statement(text, source)
    categories = apply_categories(conn, parsed["rows"])
    result = reconcile(conn, parsed["rows"])
    return {
        **parsed,
        "reconciliation": result,
        "categories": categories,
        "generated_at": datetime.now().isoformat(),
        "note": "只有「还没记」的行会写入账本；「已经记过」的行不会重复入账。",
    }
