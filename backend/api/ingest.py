"""统一导入口的 HTTP 接口。

三步走：identify 认这是什么 → preview 看清楚会写入什么 → commit 写入。
前两步全程只读。

写入这一步**不自己实现**，而是转交给各模块原本的导入接口：账单交给账本的
批量导入（那里有内容防重和整批撤销），运动和体重交给健康导入。这样每条
写入路径全平台只有一份实现，不会出现"统一入口写进去的记录和原来那条路
写进去的不一样"这种事。
"""
from __future__ import annotations

import base64
import binascii
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from backend.api import health_import as health_import_api
from backend.api import ledger as ledger_api
from backend.core.db import db
from backend.ingest import (
    build_ingest_preview,
    formats,
    identify,
    inspect_table,
    to_table_text,
)

router = APIRouter()

KindLiteral = Literal["wechat_statement", "alipay_statement", "health_workout", "health_body"]


class IdentifyIn(BaseModel):
    """文件内容。文本走 content，二进制（Excel）走 content_base64。

    微信和支付宝现在导出的是 Excel，那是个 zip，没法当文本传。
    """

    content: Optional[str] = Field(None, max_length=4_000_000)
    content_base64: Optional[str] = Field(None, max_length=12_000_000)
    filename: str = Field("导入文件.csv", max_length=255)

    @model_validator(mode="after")
    def _need_one(self):
        if not self.content and not self.content_base64:
            raise ValueError("需要 content 或 content_base64")
        return self

    def raw_bytes(self) -> bytes:
        if self.content_base64:
            try:
                return base64.b64decode(self.content_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(400, "文件内容传坏了，请重新选一次文件") from exc
        return (self.content or "").encode("utf-8")


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
    """认一下这是什么文件。只读，不写入任何数据。

    Excel 会先转成文本表格再判断——后面那套识别和解析一个字都不用改。
    """
    raw = body.raw_bytes()
    text = to_table_text(body.filename, raw)
    result = identify(body.filename, text)
    if not result["candidates"]:
        # 认不出来时把实际读到的前几行摊开，否则用户没有排查的余地
        result["seen"] = inspect_table(body.filename, raw)
    return result


@router.post("/api/ingest/preview")
def ingest_preview(body: IngestPreviewIn):
    """按选定的类型解析并对账。只读，不写入任何数据。"""
    text = to_table_text(body.filename, body.raw_bytes())
    with db() as conn:
        return build_ingest_preview(conn, body.kind, body.filename, text)


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
