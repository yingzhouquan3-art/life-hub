"""本地自动快照。

全部生活数据都在一个文件里，这是唯一一个「出事就无法挽回」的地方。
所以这里守两件事：备份必须是一致的副本，清理必须有下限。
"""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from backend import main
from backend.core import db as db_core
from backend.core import snapshots


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.original_dir = snapshots.SNAPSHOT_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        db_core.use_database(root / "ledger.db")
        snapshots.SNAPSHOT_DIR = root / "snapshots"
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        snapshots.SNAPSHOT_DIR = self.original_dir
        self.temp_dir.cleanup()

    def age(self, name, days):
        """把某份快照的时间往前推，用来测试保留策略。"""
        path = snapshots.SNAPSHOT_DIR / name
        old = (datetime.now() - timedelta(days=days)).timestamp()
        import os
        os.utime(path, (old, old))

    # ---------- 备份本身 ----------

    def test_snapshot_is_a_usable_database(self):
        """副本必须能直接打开来读，否则等于没备份。"""
        with main.db() as conn:
            conn.execute(
                "INSERT INTO accounts (name, type, opening_balance, is_active, created_at)"
                " VALUES ('测试账户', 'cash', 100, 1, ?)",
                (datetime.now().isoformat(),),
            )
        created = snapshots.take_snapshot("test")

        copy = sqlite3.connect(snapshots.SNAPSHOT_DIR / created["name"])
        names = [row[0] for row in copy.execute("SELECT name FROM accounts")]
        copy.close()
        self.assertIn("测试账户", names)

    def test_snapshot_survives_concurrent_writes(self):
        """备份期间有连接开着也要拿到一致副本——这正是不用复制文件的原因。"""
        with main.db() as conn:
            conn.execute(
                "INSERT INTO accounts (name, type, opening_balance, is_active, created_at)"
                " VALUES ('并发', 'cash', 1, 1, ?)", (datetime.now().isoformat(),))
            created = snapshots.take_snapshot("concurrent")
        copy = sqlite3.connect(snapshots.SNAPSHOT_DIR / created["name"])
        self.assertEqual(copy.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        copy.close()

    def test_listing_is_newest_first(self):
        first = snapshots.take_snapshot("a")
        second = snapshots.take_snapshot("b")
        names = [item["name"] for item in snapshots.list_snapshots()]
        self.assertEqual(names[0], second["name"])
        self.assertIn(first["name"], names)

    # ---------- 什么时候自动备份 ----------

    def test_first_run_always_takes_one(self):
        self.assertIsNotNone(snapshots.auto_snapshot_if_due())

    def test_not_due_yet_does_nothing(self):
        snapshots.take_snapshot("recent")
        self.assertIsNone(snapshots.auto_snapshot_if_due(interval_hours=24))

    def test_due_again_after_the_interval(self):
        created = snapshots.take_snapshot("old")
        self.age(created["name"], days=2)
        self.assertIsNotNone(snapshots.auto_snapshot_if_due(interval_hours=24))

    def test_failure_does_not_raise(self):
        """备份失败最多是「这次没备份」，绝不能让服务起不来。"""
        original = snapshots.take_snapshot
        snapshots.take_snapshot = lambda reason="auto": (_ for _ in ()).throw(OSError("磁盘满了"))
        try:
            self.assertIsNone(snapshots.auto_snapshot_if_due(interval_hours=0))
        finally:
            snapshots.take_snapshot = original

    # ---------- 清理有下限 ----------

    def test_recent_snapshots_are_never_pruned(self):
        for index in range(3):
            snapshots.take_snapshot(f"keep{index}")
        self.assertEqual(snapshots.prune_snapshots(keep_days=30), [])
        self.assertEqual(len(snapshots.list_snapshots()), 3)

    def test_minimum_is_kept_even_when_everything_is_expired(self):
        """全部过期也要留下最近几份——备份的价值在最坏情况才兑现。"""
        for index in range(8):
            created = snapshots.take_snapshot(f"old{index}")
            self.age(created["name"], days=90)
        snapshots.prune_snapshots(keep_days=30, keep_minimum=5)
        self.assertEqual(len(snapshots.list_snapshots()), 5)

    def test_expired_extras_are_removed(self):
        for index in range(4):
            created = snapshots.take_snapshot(f"old{index}")
            self.age(created["name"], days=90)
        for index in range(2):
            snapshots.take_snapshot(f"new{index}")
        removed = snapshots.prune_snapshots(keep_days=30, keep_minimum=3)
        self.assertEqual(len(removed), 3)
        self.assertEqual(len(snapshots.list_snapshots()), 3)

    # ---------- 自检 ----------

    def test_integrity_check_passes_on_a_healthy_database(self):
        self.assertTrue(snapshots.check_integrity()["ok"])

    def test_state_reports_how_long_since_the_last_backup(self):
        created = snapshots.take_snapshot("x")
        self.age(created["name"], days=3)
        state = snapshots.get_snapshot_state()
        self.assertAlmostEqual(state["hours_since_last"], 72, delta=2)
        self.assertEqual(state["count"], 1)

    def test_state_is_honest_when_there_is_no_backup(self):
        state = snapshots.get_snapshot_state()
        self.assertIsNone(state["latest"])
        self.assertIsNone(state["hours_since_last"])
        self.assertEqual(state["count"], 0)

    def test_state_warns_that_snapshots_share_the_same_disk(self):
        """同一块硬盘上的备份挡不住硬盘故障，这一点必须说出来。"""
        self.assertIn("同一块硬盘", snapshots.get_snapshot_state()["note"])


if __name__ == "__main__":
    unittest.main()
