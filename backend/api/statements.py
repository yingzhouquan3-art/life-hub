"""月度账单导入与对账的 HTTP 接口。

两步走：先 `POST /api/statements/preview` 看清楚要写入几条、跳过几条、
和已有交易重合几条，确认后再把「还没记」的那批交给账本的安全导入。
预览这一步不写入任何数据。
"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.statements import SOURCES, build_preview

router = APIRouter()


class StatementIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4_000_000)
    source: Optional[Literal["wechat", "alipay"]] = None
    filename: str = Field("statement.csv", max_length=255)


@router.get("/api/statements/sources")
def statement_sources():
    return {"sources": [{"key": key, "label": label} for key, label in SOURCES.items()]}


@router.post("/api/statements/preview")
def preview_statement(body: StatementIn):
    """解析账单并与已有交易对账。只读，不写入任何数据。

    返回里的 reconciliation.new 就是建议写入的行，可以原样交给
    /api/import/transactions，那边还有一层内容防重和整批撤销。
    """
    with db() as conn:
        preview = build_preview(conn, body.content, body.source)
        preview["filename"] = body.filename
        preview["import_payload"] = {
            "filename": body.filename,
            "rows": [
                {
                    "occurred_on": row["occurred_on"],
                    "type": row["type"],
                    "amount": row["amount"],
                    "note": row["note"],
                }
                for row in preview["reconciliation"]["new"]
            ],
        }
        return preview
