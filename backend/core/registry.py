"""模块契约。

[POS] backend/core/registry.py — 只定义「一个生活模块要交代清楚什么」，不认识任何具体模块

每个模块用一个 LifeModule 声明自己拥有哪些表、这些表怎么建、备份时导出哪些列、
恢复时按什么顺序清空。平台侧的建表、备份与恢复因此只需要遍历注册表，
新增模块不必再回头修改四个地方。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional


@dataclass(frozen=True)
class LifeModule:
    """一个生活模块对平台的全部承诺。"""

    key: str
    """模块标识，与前端导航和搜索结果里的 module 字段一致。"""

    label: str
    """给人看的模块名。"""

    schema: str
    """建表与建索引语句，必须可重复执行（一律 IF NOT EXISTS）。"""

    tables: dict[str, list[str]]
    """备份契约：表名 -> 导出列。顺序即恢复时的写入顺序，父表必须排在子表前面。"""

    optional_tables: frozenset[str] = frozenset()
    """旧版本数据库里可能不存在的表；恢复时缺失不算错误。"""

    delete_order: tuple[str, ...] = ()
    """恢复前清空本模块表的顺序：先子表后父表。留空表示与 tables 顺序相反。"""

    migrate: Optional[Callable] = field(default=None, compare=False)
    """旧库迁移。在所有模块建表完成之后统一执行。"""

    def __post_init__(self):
        unknown = set(self.optional_tables) - set(self.tables)
        if unknown:
            raise ValueError(f"{self.key}: optional_tables 里有未声明的表 {sorted(unknown)}")
        if self.delete_order and set(self.delete_order) != set(self.tables):
            raise ValueError(f"{self.key}: delete_order 与 tables 覆盖的表不一致")

    def resolved_delete_order(self) -> tuple[str, ...]:
        return self.delete_order or tuple(reversed(list(self.tables)))


def create_schema(conn, modules: Iterable[LifeModule]) -> None:
    """建好所有模块的表，然后统一跑迁移。

    分两趟是刻意的：迁移可能读到别的模块的表，建表阶段先全部就绪更安全。
    """
    modules = list(modules)
    for module in modules:
        conn.executescript(module.schema)
    for module in modules:
        if module.migrate:
            module.migrate(conn)


def snapshot_columns(modules: Iterable[LifeModule]) -> dict[str, list[str]]:
    """备份契约：表名 -> 列，按模块注册顺序拼接。"""
    columns: dict[str, list[str]] = {}
    for module in modules:
        for table, cols in module.tables.items():
            if table in columns:
                raise ValueError(f"表 {table} 被多个模块声明所有权")
            columns[table] = list(cols)
    return columns


def optional_tables(modules: Iterable[LifeModule]) -> set[str]:
    return {table for module in modules for table in module.optional_tables}


def delete_order(modules: Iterable[LifeModule]) -> list[str]:
    """恢复前的清空顺序：模块反序，模块内先子表后父表。"""
    order: list[str] = []
    for module in reversed(list(modules)):
        order.extend(module.resolved_delete_order())
    return order


def owner_of(modules: Iterable[LifeModule], table: str) -> Optional[LifeModule]:
    for module in modules:
        if table in module.tables:
            return module
    return None
