"""数据库连接与位置。

[POS] backend/core/db.py — 全平台唯一的 SQLite 连接入口
[PROTOCOL] 数据库位置只能通过 use_database() 切换；不要在别处缓存 DB_PATH，
           否则测试与未来的多宿主部署会读到过期路径。
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from backend.core.config import DATA_DIR

DB_PATH = DATA_DIR / "ledger.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def use_database(path) -> Path:
    """切换当前数据库位置，返回生效后的路径。"""
    global DB_PATH
    DB_PATH = Path(path)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return DB_PATH


def current_path() -> Path:
    """读取当前生效的数据库位置。"""
    return DB_PATH


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
