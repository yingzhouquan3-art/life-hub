"""各生活模块与模块注册表。

每个模块保存自己的原始事实，不直接修改其他模块的数据；
跨模块的总览、日历与搜索只读取各模块公开的摘要。

MODULES 是平台唯一的模块清单。建表、备份与恢复都遍历它，
所以新增一个模块只需要在自己的文件里声明 MODULE 并在这里登记一次。

注册顺序有含义：
- 建表与备份写入按此顺序，父表在前；
- 恢复前的清空按此顺序反向进行，子表在前。
"""
from __future__ import annotations

from backend.core import registry
from backend.modules import (
    fitness,
    goals,
    ledger,
    nutrition,
    recovery,
    reflection,
    rhythm,
    study,
)

MODULES = (
    ledger.MODULE,
    fitness.MODULE,
    nutrition.MODULE,
    recovery.MODULE,
    study.MODULE,
    rhythm.MODULE,
    reflection.MODULE,
    goals.MODULE,
)

SNAPSHOT_COLUMNS = registry.snapshot_columns(MODULES)
OPTIONAL_SNAPSHOT_TABLES = registry.optional_tables(MODULES)
DELETE_ORDER = registry.delete_order(MODULES)
