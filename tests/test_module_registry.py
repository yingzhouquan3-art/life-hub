"""模块注册表契约。

这些测试保证「新增一个生活模块」只需要改自己的文件加登记一次，
而不会在建表、备份、恢复三处留下悄悄的不一致。
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend import main
from backend.core import db as db_core
from backend.core.registry import LifeModule
from backend.modules import DELETE_ORDER, MODULES, OPTIONAL_SNAPSHOT_TABLES, SNAPSHOT_COLUMNS


class ModuleRegistryTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def table_names(self):
        with main.db() as conn:
            return {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }

    def test_every_table_has_exactly_one_owning_module(self):
        seen = {}
        for module in MODULES:
            for table in module.tables:
                self.assertNotIn(
                    table, seen,
                    f"表 {table} 同时被 {seen.get(table)} 和 {module.key} 声明所有权",
                )
                seen[table] = module.key
        self.assertEqual(set(seen), set(SNAPSHOT_COLUMNS))

    def test_created_tables_match_registry_declarations(self):
        self.assertEqual(
            self.table_names(), set(SNAPSHOT_COLUMNS),
            "建出来的表与注册表声明的表不一致：要么建了没登记，要么登记了没建",
        )

    def test_backup_columns_match_real_table_columns(self):
        with main.db() as conn:
            for table, declared in SNAPSHOT_COLUMNS.items():
                actual = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
                self.assertEqual(
                    sorted(declared), sorted(actual),
                    f"{table} 的备份列与实际列漂移了；备份会丢字段",
                )

    def test_delete_order_covers_every_table_and_reverses_insert_order(self):
        self.assertEqual(sorted(DELETE_ORDER), sorted(SNAPSHOT_COLUMNS))
        self.assertEqual(len(DELETE_ORDER), len(set(DELETE_ORDER)))
        insert_order = list(SNAPSHOT_COLUMNS)
        for table in DELETE_ORDER:
            self.assertIn(table, insert_order)

    def test_foreign_keys_point_backwards_in_insert_order(self):
        """写入顺序必须让父表排在子表前面，否则恢复备份会撞外键。"""
        insert_order = list(SNAPSHOT_COLUMNS)
        with main.db() as conn:
            for table in insert_order:
                for row in conn.execute(f"PRAGMA foreign_key_list({table})"):
                    parent = row[2]
                    if parent not in insert_order:
                        continue
                    self.assertLess(
                        insert_order.index(parent), insert_order.index(table),
                        f"{table} 依赖 {parent}，但写入顺序把父表排在了后面",
                    )

    def test_optional_tables_are_declared_tables(self):
        self.assertTrue(OPTIONAL_SNAPSHOT_TABLES <= set(SNAPSHOT_COLUMNS))

    def test_schema_is_repeatable(self):
        """init_db 必须可以反复执行而不报错，也不改变表集合。"""
        before = self.table_names()
        main.init_db()
        main.init_db()
        self.assertEqual(self.table_names(), before)

    def test_module_rejects_inconsistent_declaration(self):
        with self.assertRaises(ValueError):
            LifeModule(key="bad", label="坏模块", schema="", tables={"a": ["id"]},
                       optional_tables=frozenset({"b"}))
        with self.assertRaises(ValueError):
            LifeModule(key="bad", label="坏模块", schema="", tables={"a": ["id"]},
                       delete_order=("a", "b"))

    def test_restore_uses_registry_order(self):
        """备份导出的表与注册表一致，恢复才不会漏表。"""
        with main.db() as conn:
            snapshot = main.build_snapshot(conn)
        self.assertEqual(set(snapshot["tables"]), set(SNAPSHOT_COLUMNS))


if __name__ == "__main__":
    unittest.main()
