"""统一导入口的 HTTP 接口。

三步走：identify 认这是什么 → preview 看清楚会写入什么 → commit 写入。
前两步全程只读。

写入这一步**不自己实现**，而是转交给各模块原本的导入接口：账单交给账本的
批量导入（那里有内容防重和整批撤销），运动和体重交给健康导入。这样每条
写入路径全平台只有一份实现，不会出现"统一入口写进去的记录和原来那条路
写进去的不一样"这种事。
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.api import health_import as health_import_api
from backend.api import ledger as ledger_api
from backend.core.db import db
from backend.ingest import build_ingest_preview, formats, identify

router = APIRouter()

KindLiteral = Literal["wechat_statement", "alipay_statement", "health_workout", "health_body"]


class IdentifyIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4_000_000)
    filename: str = Field("导入文件.csv", max_length=255)


class IngestPreviewIn(IdentifyIn):
    kind: KindLiteral


class IngestCommitIn(BaseModel):
    kind: KindLiteral
    filename: str = Field("导入文件.csv", max_length=255)
    rows: list[dict] = Field(..., min_length=1, max_length=5000)


@router.get("/api/ingest/formats")
def ingest_formats():
    """能导入哪些东西，各自会写进哪个模块。"""
    return {"formats": formats()}


@router.post("/api/ingest/identify")
def ingest_identify(body: IdentifyIn):
    """认一下这是什么文件。只读，连解析都不做。"""
    return identify(body.filename, body.content)


@router.post("/api/ingest/preview")
def ingest_preview(body: IngestPreviewIn):
    """按选定的类型解析并对账。只读，不写入任何数据。"""
    with db() as conn:
        return build_ingest_preview(conn, body.kind, body.filename, body.content)


@router.post("/api/ingest/commit")
def ingest_commit(body: IngestCommitIn):
    """写入预览里「还没记过」的那些行，转交给对应模块原本的导入接口。"""
    if body.kind in ("wechat_statement", "alipay_statement"):
        payload = ledger_api.ImportBatchIn(
            filename=body.filename,
            rows=[
                ledger_api.ImportTransactionIn(
                    occurred_on=row["occurred_on"],
                    type=row["type"],
                    amount=row["amount"],
                    category=row.get("category"),
                    note=row.get("note", ""),
                )
                for row in body.rows
            ],
        )
        result = ledger_api.import_transactions(payload)
        # 两条写入路径原本一个叫 imported_count、一个叫 imported，
        # 这里统一成 imported，界面只需要认一个字段。
        return {"kind": body.kind, "module": "ledger",
                "imported": result["imported_count"], **result}

    health_kind = "workout" if body.kind == "health_workout" else "body"
    result = health_import_api.commit_health_export(
        health_import_api.HealthCommitIn(kind=health_kind, rows=body.rows)
    )
    return {"kind": body.kind, "module": "fitness" if health_kind == "workout" else "body", **result}
