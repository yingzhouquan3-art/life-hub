"""运动 / 健康数据导入的 HTTP 接口。

两步走：先预览看清楚要写几条、跳过几条、和已有记录重合几条，确认后再写入。
预览不写入任何数据。
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.health_import import KINDS, build_health_preview
from backend.modules.body import get_body_state, save_body_measurement
from backend.modules.fitness import get_fitness_state, record_workout

router = APIRouter()


class HealthExportIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4_000_000)
    kind: Literal["workout", "body"]
    filename: str = Field("export.csv", max_length=255)


class HealthCommitIn(BaseModel):
    kind: Literal["workout", "body"]
    rows: list[dict] = Field(..., min_length=1, max_length=5000)


@router.get("/api/health-import/kinds")
def health_import_kinds():
    return {"kinds": [{"key": key, "label": label} for key, label in KINDS.items()]}


@router.post("/api/health-import/preview")
def preview_health_export(body: HealthExportIn):
    """解析导出文件并与已有记录对账。只读，不写入任何数据。"""
    with db() as conn:
        preview = build_health_preview(conn, body.content, body.kind)
        preview["filename"] = body.filename
        return preview


@router.post("/api/health-import/commit")
def commit_health_export(body: HealthCommitIn):
    """写入预览里「还没记」的那些行。

    逐行调用对应模块自己的写入函数，不直接操作它们的表。
    """
    written, failed = [], []
    with db() as conn:
        for row in body.rows:
            try:
                if body.kind == "workout":
                    written.append(record_workout(
                        conn,
                        occurred_on=row["occurred_on"],
                        activity=row.get("activity", "other"),
                        duration_minutes=int(row["duration_minutes"]),
                        intensity=int(row.get("intensity") or 5),
                        note=row.get("note", ""),
                    ))
                else:
                    written.append(save_body_measurement(
                        conn,
                        occurred_on=row["occurred_on"],
                        weight_kg=row.get("weight_kg"),
                        body_fat_pct=row.get("body_fat_pct"),
                    ))
            except Exception as exc:  # 单行失败不该带走整批
                failed.append({"row": row, "reason": str(exc)})
        state = get_fitness_state(conn) if body.kind == "workout" else get_body_state(conn)

    return {
        "imported": len(written),
        "failed": failed,
        "state": state,
        "note": "导入的运动记录强度默认按 5 填入，因为导出文件里没有这一项，请按需修改。",
    }
