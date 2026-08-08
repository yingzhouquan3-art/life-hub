"""学习与专注模块。

学习时长只表示投入时间，不能推导知识掌握程度。

还负责番茄钟：倒计时的真相是数据库里的结束时刻，不是浏览器里的计数器，
所以刷新页面或换到手机都不会丢。一个没跑完的番茄不是一段学习记录。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException

from backend.core.registry import LifeModule


def get_study_state(conn, recent_limit: int = 30) -> dict:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    today_row = conn.execute(
        """SELECT COUNT(*) AS count, COALESCE(SUM(duration_minutes), 0) AS minutes,
                  AVG(focus) AS avg_focus
           FROM study_sessions WHERE occurred_on = ?""",
        (today.isoformat(),),
    ).fetchone()
    week_row = conn.execute(
        """SELECT COUNT(*) AS count, COALESCE(SUM(duration_minutes), 0) AS minutes,
                  AVG(focus) AS avg_focus
           FROM study_sessions WHERE occurred_on BETWEEN ? AND ?""",
        (week_start.isoformat(), today.isoformat()),
    ).fetchone()
    recent = conn.execute(
        """SELECT * FROM study_sessions
           ORDER BY occurred_on DESC, id DESC LIMIT ?""",
        (recent_limit,),
    ).fetchall()
    return {
        "today": {
            "count": int(today_row["count"] or 0),
            "minutes": int(today_row["minutes"] or 0),
            "avg_focus": round(float(today_row["avg_focus"]), 1) if today_row["avg_focus"] is not None else None,
        },
        "week": {
            "start_date": week_start.isoformat(),
            "count": int(week_row["count"] or 0),
            "minutes": int(week_row["minutes"] or 0),
            "avg_focus": round(float(week_row["avg_focus"]), 1) if week_row["avg_focus"] is not None else None,
        },
        "recent": [dict(row) for row in recent],
    }


def record_study_session(
    conn, *, occurred_on: str, subject: str, duration_minutes: int,
    focus: int, note: str = "",
) -> dict:
    date.fromisoformat(occurred_on)
    cur = conn.execute(
        """INSERT INTO study_sessions
           (occurred_on, subject, duration_minutes, focus, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (occurred_on, subject.strip(), duration_minutes, focus, note.strip(), datetime.now().isoformat()),
    )
    return dict(conn.execute("SELECT * FROM study_sessions WHERE id = ?", (cur.lastrowid,)).fetchone())

# ---------- 番茄钟 ----------
#
# 倒计时的真相是数据库里的结束时刻，不是浏览器里的一个计数器。
# 这样刷新页面、换到手机、电脑睡一觉醒来，剩余时间都还是对的。
#
# 计算剩余时间用「目标时刻 − 当前时间」，不是每秒自减：
# 后者在标签页切到后台时会被浏览器限流，越跑越慢。
# 这个做法参考 https://github.com/mohammedyh/pomodoro-timer
#
# 一个没跑完的番茄**不是**一段学习记录。中途停下时如实告诉用户
# 已经专注了多久，由他决定要不要按实际时长记一笔。

FOCUS_KINDS = {"focus": "专注", "short_break": "短休息", "long_break": "长休息"}
DEFAULT_MINUTES = {"focus": 25, "short_break": 5, "long_break": 15}


def _elapsed_minutes(started_at: str, until: Optional[datetime] = None) -> int:
    """从开始到现在实际过去了多少整分钟。"""
    started = datetime.fromisoformat(started_at)
    now = until or datetime.now()
    return max(0, int((now - started).total_seconds() // 60))


def start_focus_session(
    conn, *, kind: str = "focus", minutes: Optional[int] = None, subject: str = "",
) -> dict:
    """开一个番茄。同一时间只允许有一个在跑。"""
    if kind not in FOCUS_KINDS:
        raise HTTPException(400, f"未知的类型：{kind}")
    # 不能写成 minutes or DEFAULT：那会把 0 当成「没填」悄悄变成 25，
    # 而 0 分钟是明确的错误输入，应当报错
    planned = int(DEFAULT_MINUTES[kind] if minutes is None else minutes)
    if planned < 1 or planned > 240:
        raise HTTPException(400, "时长必须在 1 到 240 分钟之间")

    running = get_running_focus(conn)
    if running:
        raise HTTPException(409, "已经有一个在跑了，先停掉或等它结束")

    now = datetime.now()
    cur = conn.execute(
        """INSERT INTO focus_sessions
           (kind, subject, planned_minutes, started_at, ends_at, status, created_at)
           VALUES (?, ?, ?, ?, ?, 'running', ?)""",
        (kind, subject.strip(), planned, now.isoformat(),
         (now + timedelta(minutes=planned)).isoformat(), now.isoformat()),
    )
    return get_focus_session(conn, cur.lastrowid)


def get_focus_session(conn, session_id: int) -> dict:
    row = conn.execute("SELECT * FROM focus_sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, "focus session not found")
    return _describe_focus(dict(row))


def _describe_focus(item: dict) -> dict:
    """补上剩余秒数与是否已经到点。"""
    item["kind_label"] = FOCUS_KINDS.get(item["kind"], item["kind"])
    if item["status"] != "running":
        item["remaining_seconds"] = 0
        item["finished"] = True
        return item
    remaining = (datetime.fromisoformat(item["ends_at"]) - datetime.now()).total_seconds()
    item["remaining_seconds"] = max(0, int(remaining))
    item["finished"] = remaining <= 0
    item["elapsed_minutes"] = _elapsed_minutes(item["started_at"])
    return item


def get_running_focus(conn) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM focus_sessions WHERE status = 'running' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _describe_focus(dict(row)) if row else None


def finish_focus_session(
    conn, session_id: int, *, focus: Optional[int] = None, record: bool = True,
) -> dict:
    """结束一个番茄。

    record=True 时按**实际专注的分钟数**写一条学习记录——
    不是按计划时长，那样会把提前停下的番茄记成整整一个。
    不足一分钟就不记：那不构成一段学习事实。
    休息不写学习记录。
    """
    session = get_focus_session(conn, session_id)
    if session["status"] != "running":
        raise HTTPException(400, "这个番茄已经结束了")

    now = datetime.now()
    ends_at = datetime.fromisoformat(session["ends_at"])
    # 到点之后才来点结束，实际时长按计划算，不把发呆那几分钟也算进去
    actual = (session["planned_minutes"] if now >= ends_at
              else _elapsed_minutes(session["started_at"], now))

    study_id = None
    if record and session["kind"] == "focus" and actual >= 1:
        created = record_study_session(
            conn,
            occurred_on=datetime.fromisoformat(session["started_at"]).date().isoformat(),
            subject=session["subject"] or "专注",
            duration_minutes=actual,
            focus=int(focus) if focus else 3,
            note="番茄钟",
        )
        study_id = created["id"]

    conn.execute(
        """UPDATE focus_sessions
           SET status = ?, actual_minutes = ?, study_session_id = ?, ended_at = ?
           WHERE id = ?""",
        ("completed" if now >= ends_at else "stopped", actual, study_id,
         now.isoformat(), session_id),
    )
    result = get_focus_session(conn, session_id)
    result["recorded_study_session"] = study_id
    return result


def get_focus_state(conn, recent_limit: int = 10) -> dict:
    """当前番茄 + 今天完成了几个 + 最近记录。"""
    today = date.today().isoformat()
    today_row = conn.execute(
        """SELECT COUNT(*) AS count, COALESCE(SUM(actual_minutes), 0) AS minutes
           FROM focus_sessions
           WHERE kind = 'focus' AND status IN ('completed','stopped')
             AND substr(started_at, 1, 10) = ?""",
        (today,),
    ).fetchone()
    recent = conn.execute(
        "SELECT * FROM focus_sessions ORDER BY id DESC LIMIT ?",
        (max(1, min(recent_limit, 50)),),
    ).fetchall()
    return {
        "running": get_running_focus(conn),
        "defaults": DEFAULT_MINUTES,
        "kind_labels": FOCUS_KINDS,
        "today": {
            "count": int(today_row["count"] or 0),
            "minutes": int(today_row["minutes"] or 0),
        },
        "recent": [_describe_focus(dict(row)) for row in recent],
        "note": "番茄个数只表示开始并结束过几次，不代表学到了多少。",
    }


SCHEMA = """
CREATE TABLE IF NOT EXISTS study_sessions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          occurred_on TEXT NOT NULL,
          subject TEXT NOT NULL,
          duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0 AND duration_minutes <= 1440),
          focus INTEGER NOT NULL CHECK (focus BETWEEN 1 AND 5),
          note TEXT DEFAULT '',
          created_at TEXT NOT NULL
        );
CREATE TABLE IF NOT EXISTS focus_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL DEFAULT 'focus' CHECK (kind IN ('focus','short_break','long_break')),
  subject TEXT DEFAULT '',
  planned_minutes INTEGER NOT NULL CHECK (planned_minutes > 0 AND planned_minutes <= 240),
  started_at TEXT NOT NULL,
  ends_at TEXT NOT NULL,
  ended_at TEXT,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running','completed','stopped')),
  actual_minutes INTEGER,
  study_session_id INTEGER REFERENCES study_sessions(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_focus_status ON focus_sessions(status);
CREATE INDEX IF NOT EXISTS idx_study_date ON study_sessions(occurred_on);
"""


MODULE = LifeModule(
    key="study",
    label="学习与专注",
    schema=SCHEMA,
    tables={
        "study_sessions": ["id", "occurred_on", "subject", "duration_minutes", "focus", "note", "created_at"],
        "focus_sessions": ["id", "kind", "subject", "planned_minutes", "started_at", "ends_at",
                           "ended_at", "status", "actual_minutes", "study_session_id", "created_at"],
    },
    optional_tables=frozenset({"study_sessions", "focus_sessions"}),
)
