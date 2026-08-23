"""本地自动快照。

全部生活数据都在一个 data/ledger.db 里。手动导出要人记得做，
而人不会记得——所以这里在每次启动时自动留一份，出事时至少能退回去。

几条刻意的取舍：

1. **用 sqlite3 的 backup API，不是复制文件。** 复制文件时如果有写入正在进行，
   得到的会是一个损坏的副本，而且损坏得很安静——直到你真的需要它。
2. **删除有下限。** 清理旧快照时永远保留最近若干份，哪怕它们都「过期」了。
   备份的价值在最坏情况出现时才兑现，那时多占几 MB 根本不是问题。
3. **备份失败不能拖垮启动。** 最坏情况是这次没有备份，但服务照常可用；
   界面上如实显示「上次备份是多久之前」，不假装一切正常。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from backend.core.config import DATA_DIR
from backend.core.db import current_path

SNAPSHOT_DIR = DATA_DIR / "snapshots"
PREFIX = "ledger-"
SUFFIX = ".db"

# 默认策略：每天至少一份，保留 30 天，且无论如何不少于 10 份。
DEFAULT_INTERVAL_HOURS = 24
DEFAULT_KEEP_DAYS = 30
DEFAULT_KEEP_MINIMUM = 10


def snapshot_dir() -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SNAPSHOT_DIR


def list_snapshots() -> list[dict]:
    """按时间倒序列出已有快照。"""
    if not SNAPSHOT_DIR.exists():
        return []
    items = []
    for path in SNAPSHOT_DIR.glob(f"{PREFIX}*{SUFFIX}"):
        stat = path.stat()
        items.append({
            "name": path.name,
            "bytes": stat.st_size,
            # 展示到秒就够看，但排序要用原始时间戳：
            # 同一秒内做的两份，秒级精度分不出先后。
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "_mtime": stat.st_mtime,
        })
    # 文件系统的时间戳精度有限，同一刻做的两份 st_mtime 可能完全相同，
    # 这时排序会退化成目录枚举顺序（看着像随机）。用文件名兜底：
    # 名字里带毫秒时间戳，字典序就是时间序。
    items.sort(key=lambda item: (item["_mtime"], item["name"]), reverse=True)
    for item in items:
        del item["_mtime"]
    return items


def take_snapshot(reason: str = "auto") -> dict:
    """立刻留一份。

    sqlite3 的 backup API 会在源库上加读锁并逐页复制，
    即使此刻有别的连接在写，拿到的也是一个一致的副本。
    """
    source_path = current_path()
    if not source_path.exists():
        raise FileNotFoundError(f"数据库不存在：{source_path}")

    # 名字撞了的话，sqlite 的 backup 会直接把已有文件写掉——
    # **前一份快照就这么没了**，没有任何提示。备份功能里的静默丢失最糟。
    #
    # 不靠时钟保证唯一：毫秒精度在快机器上照样会撞（实测同一毫秒内做两份）。
    # 直接看文件在不在，占用了就换一个。
    safe_reason = "".join(ch for ch in reason if ch.isalnum() or ch in "-_") or "auto"
    directory = snapshot_dir()

    # 撞名了就把时间戳往后挪一毫秒再试，而不是在名字后面加序号。
    #
    # 加序号会让新文件在字典序里排到旧文件**前面**（'.' 大于 '-'，
    # 所以 "…-burst.db" > "…-burst-2.db"），而 st_mtime 相同时排序正是靠
    # 文件名兜底的——那样一来「最新在前」就反了。挪时间戳则让名字天生单调：
    # 字典序永远等于创建顺序。
    moment = datetime.now()
    while True:
        stamp = moment.strftime("%Y%m%d-%H%M%S-%f")[:-3]
        target = directory / f"{PREFIX}{stamp}-{safe_reason}{SUFFIX}"
        if not target.exists():
            break
        moment += timedelta(milliseconds=1)

    source = sqlite3.connect(source_path)
    destination = sqlite3.connect(target)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

    return {
        "name": target.name,
        "bytes": target.stat().st_size,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "reason": reason,
    }


def prune_snapshots(
    keep_days: int = DEFAULT_KEEP_DAYS, keep_minimum: int = DEFAULT_KEEP_MINIMUM,
) -> list[str]:
    """删掉过期快照，但永远至少留 keep_minimum 份。

    返回被删掉的文件名。删除有下限是刻意的：备份只在最坏情况下才兑现价值，
    那时多占几 MB 完全不是问题，而少一份可能就是全部。
    """
    snapshots = list_snapshots()
    if len(snapshots) <= keep_minimum:
        return []

    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat(timespec="seconds")
    removed = []
    # 从最旧的开始看，一旦剩余数量触到下限就停手
    for item in reversed(snapshots):
        if len(snapshots) - len(removed) <= keep_minimum:
            break
        if item["created_at"] >= cutoff:
            break
        try:
            (SNAPSHOT_DIR / item["name"]).unlink()
            removed.append(item["name"])
        except OSError:
            # 删不掉就留着，不值得为清理旧文件报错
            continue
    return removed


def hours_since_last_snapshot() -> Optional[float]:
    snapshots = list_snapshots()
    if not snapshots:
        return None
    latest = datetime.fromisoformat(snapshots[0]["created_at"])
    return (datetime.now() - latest).total_seconds() / 3600


def auto_snapshot_if_due(interval_hours: int = DEFAULT_INTERVAL_HOURS) -> Optional[dict]:
    """距上次备份超过 interval_hours 就再留一份。

    出任何问题都只是「这次没备份成」，不能让服务起不来。
    """
    try:
        elapsed = hours_since_last_snapshot()
        if elapsed is not None and elapsed < interval_hours:
            return None
        created = take_snapshot("auto")
        prune_snapshots()
        return created
    except (OSError, sqlite3.Error) as exc:
        print(f"[snapshots] 自动备份失败（服务照常运行）：{exc}", flush=True)
        return None


def check_integrity() -> dict:
    """数据库自检。

    损坏往往是安静的：读得出来、看着正常，直到某天读到坏页。
    启动时查一次，有问题当场说，而不是等用户发现数据不对。
    """
    try:
        conn = sqlite3.connect(current_path())
    except sqlite3.Error as exc:
        return {"ok": False, "problems": [f"打不开数据库：{exc}"]}
    try:
        problems = []
        result = conn.execute("PRAGMA integrity_check").fetchone()
        if result and result[0] != "ok":
            problems.append(f"完整性检查：{result[0]}")
        broken = conn.execute("PRAGMA foreign_key_check").fetchall()
        if broken:
            problems.append(f"有 {len(broken)} 条记录指向了不存在的父记录")
        return {"ok": not problems, "problems": problems}
    except sqlite3.Error as exc:
        return {"ok": False, "problems": [f"检查过程出错：{exc}"]}
    finally:
        conn.close()


def get_snapshot_state() -> dict:
    """给界面看的备份健康度。"""
    snapshots = list_snapshots()
    elapsed = hours_since_last_snapshot()
    return {
        "snapshots": snapshots[:20],
        "count": len(snapshots),
        "total_bytes": sum(item["bytes"] for item in snapshots),
        "latest": snapshots[0] if snapshots else None,
        "hours_since_last": round(elapsed, 1) if elapsed is not None else None,
        "directory": str(SNAPSHOT_DIR),
        "policy": {
            "interval_hours": DEFAULT_INTERVAL_HOURS,
            "keep_days": DEFAULT_KEEP_DAYS,
            "keep_minimum": DEFAULT_KEEP_MINIMUM,
        },
        "note": "快照和数据库在同一块硬盘上。硬盘坏了两者一起没，"
                "重要阶段请另外用「导出备份」存一份到别的地方。",
    }
