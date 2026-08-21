"""平台级常量与路径。

[POS] backend/core/config.py — 不含业务逻辑，只描述项目布局与共享枚举
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND = ROOT / "frontend"
DATA_DIR = Path(os.environ.get("LIFE_HUB_DATA_DIR", str(ROOT / "data"))).expanduser().resolve()

EXPENSE_CATEGORIES = (
    "food", "transport", "study", "housing", "medical",
    "entertainment", "social", "digital", "other",
)

SNAPSHOT_VERSION = 1
