"""待确认捕获模块。

手机上的支付通知和银行短信只带金额与商户，没有分类，也没有账户归属。
把它们直接写成交易等于系统替用户虚构事实，所以它们先落在这里：

- 待确认捕获**不进入任何统计**：余额、月度、预算、报表都读不到它们；
- 只有用户主动确认，才由账本模块创建真正的交易；
- 同一笔付款可能同时触发微信通知和银行扣款短信，
  金额相同且时间相差 60 秒以内的视为同一笔，合并成一条并保留两个来源；
- **捕获通道没有产生事件，不代表消费没有发生**。待确认数为零只说明
  这条通道当时没抓到东西，不能反推当天没有支出。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException

from backend.core.registry import LifeModule

CHANNELS = ("wechat_notification", "bank_sms", "manual", "other")
CHANNEL_LABELS = {
    "wechat_notification": "微信支付通知",
    "bank_sms": "银行扣款短信",
    "manual": "手动补录",
    "other": "其他来源",
}

DEDUPE_WINDOW_SECONDS = 60


def _parse_moment(value: Optional[str]) -> datetime:
    if not value:
        return datetime.now()
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, "occurred_at 必须是 ISO 时间，例如 2026-08-05T12:30:00") from exc


def find_duplicate(
    conn, *, amount: float, moment: datetime, direction: str = "expense"
) -> Optional[dict]:
    """找出可能是同一笔付款的既有捕获。

    只按金额与时间窗口判断，不看通道：两条通道抓到同一笔付款正是要合并的情况。
    已经被忽略（dismissed）的捕获不参与合并，否则用户刚划掉就会被重新塞回来。
    """
    low = (moment - timedelta(seconds=DEDUPE_WINDOW_SECONDS)).isoformat()
    high = (moment + timedelta(seconds=DEDUPE_WINDOW_SECONDS)).isoformat()
    row = conn.execute(
        """SELECT * FROM pending_captures
           WHERE status != 'dismissed'
             AND direction = ?
             AND ABS(amount - ?) < 0.005
             AND occurred_at BETWEEN ? AND ?
           ORDER BY id LIMIT 1""",
        (direction, amount, low, high),
    ).fetchone()
    return dict(row) if row else None


def record_capture(
    conn, *, channel: str, raw_text: str, amount: float,
    occurred_at: Optional[str] = None, merchant: str = "",
    direction: str = "expense", note: str = "",
) -> dict:
    """记下一条捕获。返回记录本身以及它是否被并进了已有的一条。"""
    if channel not in CHANNELS:
        raise HTTPException(400, f"未知的捕获通道：{channel}")
    if direction not in ("expense", "income"):
        raise HTTPException(400, "direction must be expense or income")
    if amount is None or amount <= 0:
        raise HTTPException(400, "金额必须大于 0")
    if not raw_text.strip():
        raise HTTPException(400, "raw_text 不能为空")

    moment = _parse_moment(occurred_at)
    now = datetime.now().isoformat()
    amount = round(float(amount), 2)

    existing = find_duplicate(conn, amount=amount, moment=moment, direction=direction)
    if existing:
        conn.execute(
            """INSERT INTO capture_channel_hits
               (capture_id, channel, raw_text, occurred_at, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (existing["id"], channel, raw_text.strip(), moment.isoformat(), now),
        )
        # 商户名以先抓到非空值的那条为准，不覆盖已有信息
        if merchant.strip() and not (existing["merchant"] or "").strip():
            conn.execute(
                "UPDATE pending_captures SET merchant = ? WHERE id = ?",
                (merchant.strip(), existing["id"]),
            )
        return {"capture": get_capture(conn, existing["id"]), "merged": True}

    cur = conn.execute(
        """INSERT INTO pending_captures
           (channel, raw_text, amount, direction, merchant, occurred_at, occurred_on,
            status, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (channel, raw_text.strip(), amount, direction, merchant.strip(),
         moment.isoformat(), moment.date().isoformat(), note.strip(), now),
    )
    capture_id = cur.lastrowid
    conn.execute(
        """INSERT INTO capture_channel_hits
           (capture_id, channel, raw_text, occurred_at, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (capture_id, channel, raw_text.strip(), moment.isoformat(), now),
    )
    return {"capture": get_capture(conn, capture_id), "merged": False}


def get_capture(conn, capture_id: int) -> dict:
    row = conn.execute("SELECT * FROM pending_captures WHERE id = ?", (capture_id,)).fetchone()
    if not row:
        raise HTTPException(404, "capture not found")
    item = dict(row)
    item["channels"] = [
        dict(hit) for hit in conn.execute(
            "SELECT channel, raw_text, occurred_at FROM capture_channel_hits "
            "WHERE capture_id = ? ORDER BY id",
            (capture_id,),
        ).fetchall()
    ]
    item["channel_labels"] = [CHANNEL_LABELS.get(hit["channel"], hit["channel"])
                              for hit in item["channels"]]
    return item


def mark_capture_confirmed(conn, capture_id: int, transaction_id: int) -> dict:
    """把捕获标记为已确认，并记下它变成了哪一笔交易。

    交易由账本模块创建；捕获模块不写 transactions 表。
    """
    capture = get_capture(conn, capture_id)
    if capture["status"] != "pending":
        raise HTTPException(400, "这条捕获已经处理过了")
    conn.execute(
        """UPDATE pending_captures
           SET status = 'confirmed', transaction_id = ?, resolved_at = ?
           WHERE id = ?""",
        (transaction_id, datetime.now().isoformat(), capture_id),
    )
    return get_capture(conn, capture_id)


def dismiss_capture(conn, capture_id: int) -> dict:
    """忽略一条捕获。只表示用户不打算把它记成交易，不代表这笔钱没花。"""
    capture = get_capture(conn, capture_id)
    if capture["status"] == "confirmed":
        raise HTTPException(400, "已确认的捕获不能忽略，请删除对应交易")
    conn.execute(
        "UPDATE pending_captures SET status = 'dismissed', resolved_at = ? WHERE id = ?",
        (datetime.now().isoformat(), capture_id),
    )
    return get_capture(conn, capture_id)


def delete_capture(conn, capture_id: int) -> int:
    get_capture(conn, capture_id)
    conn.execute("DELETE FROM pending_captures WHERE id = ?", (capture_id,))
    return capture_id


def get_capture_state(conn, limit: int = 50) -> dict:
    """待确认列表与轻量汇总。这里的数字只描述通道，不描述消费。"""
    pending_rows = conn.execute(
        """SELECT * FROM pending_captures WHERE status = 'pending'
           ORDER BY occurred_at DESC, id DESC LIMIT ?""",
        (max(1, min(limit, 200)),),
    ).fetchall()
    pending = [get_capture(conn, row["id"]) for row in pending_rows]

    counts = conn.execute(
        """SELECT status, COUNT(*) AS count, COALESCE(SUM(amount), 0) AS amount
           FROM pending_captures GROUP BY status"""
    ).fetchall()
    by_status = {row["status"]: {"count": int(row["count"]), "amount": round(float(row["amount"]), 2)}
                 for row in counts}

    by_channel = {
        row["channel"]: int(row["count"])
        for row in conn.execute(
            """SELECT channel, COUNT(*) AS count FROM capture_channel_hits GROUP BY channel"""
        ).fetchall()
    }

    last_hit = conn.execute(
        "SELECT channel, occurred_at FROM capture_channel_hits ORDER BY occurred_at DESC LIMIT 1"
    ).fetchone()

    return {
        "pending": pending,
        "summary": {
            "pending_count": by_status.get("pending", {}).get("count", 0),
            "pending_amount": by_status.get("pending", {}).get("amount", 0.0),
            "confirmed_count": by_status.get("confirmed", {}).get("count", 0),
            "dismissed_count": by_status.get("dismissed", {}).get("count", 0),
            "by_channel": by_channel,
            "last_capture_at": last_hit["occurred_at"] if last_hit else None,
            "last_capture_channel": last_hit["channel"] if last_hit else None,
        },
        "channel_labels": CHANNEL_LABELS,
    }


def get_capture_coverage(conn, target_month: Optional[str] = None) -> dict:
    """捕获覆盖率：本月的支出交易里，有多少是由捕获确认而来的。

    这个数字的用途是发现「通道悄悄挂了」，不是用来评价记账是否完整。
    覆盖率低只说明手动记的多，或者监听没抓到，不能推导有支出没记。
    """
    month = target_month or date.today().strftime("%Y-%m")
    try:
        start = date.fromisoformat(f"{month}-01")
    except ValueError as exc:
        raise HTTPException(400, "month must be YYYY-MM") from exc
    end = date(start.year + (start.month // 12), start.month % 12 + 1, 1)

    total = conn.execute(
        """SELECT COUNT(*) AS count FROM transactions
           WHERE type = 'expense' AND occurred_on >= ? AND occurred_on < ?""",
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    from_capture = conn.execute(
        """SELECT COUNT(*) AS count FROM transactions t
           WHERE t.type = 'expense' AND t.occurred_on >= ? AND t.occurred_on < ?
             AND EXISTS (SELECT 1 FROM pending_captures c
                         WHERE c.transaction_id = t.id AND c.status = 'confirmed')""",
        (start.isoformat(), end.isoformat()),
    ).fetchone()

    total_count = int(total["count"] or 0)
    captured_count = int(from_capture["count"] or 0)
    return {
        "month": month,
        "expense_transactions": total_count,
        "from_capture": captured_count,
        "coverage": round(captured_count / total_count, 3) if total_count else None,
        "still_pending": conn.execute(
            """SELECT COUNT(*) AS count FROM pending_captures
               WHERE status = 'pending' AND occurred_on >= ? AND occurred_on < ?""",
            (start.isoformat(), end.isoformat()),
        ).fetchone()["count"],
    }


SCHEMA = """
CREATE TABLE IF NOT EXISTS pending_captures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT NOT NULL CHECK (channel IN ('wechat_notification','bank_sms','manual','other')),
  raw_text TEXT NOT NULL,
  amount REAL NOT NULL CHECK (amount > 0),
  direction TEXT NOT NULL DEFAULT 'expense' CHECK (direction IN ('expense','income')),
  merchant TEXT DEFAULT '',
  occurred_at TEXT NOT NULL,
  occurred_on TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','confirmed','dismissed')),
  transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
  resolved_at TEXT,
  note TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capture_channel_hits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  capture_id INTEGER NOT NULL REFERENCES pending_captures(id) ON DELETE CASCADE,
  channel TEXT NOT NULL,
  raw_text TEXT NOT NULL,
  occurred_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_capture_status ON pending_captures(status, occurred_at);
CREATE INDEX IF NOT EXISTS idx_capture_dedupe ON pending_captures(amount, occurred_at);
CREATE INDEX IF NOT EXISTS idx_capture_hit ON capture_channel_hits(capture_id);
"""

MODULE = LifeModule(
    key="capture",
    label="待确认捕获",
    schema=SCHEMA,
    tables={
        "pending_captures": ["id", "channel", "raw_text", "amount", "direction", "merchant",
                             "occurred_at", "occurred_on", "status", "transaction_id",
                             "resolved_at", "note", "created_at"],
        "capture_channel_hits": ["id", "capture_id", "channel", "raw_text", "occurred_at", "created_at"],
    },
    optional_tables=frozenset({"pending_captures", "capture_channel_hits"}),
)
