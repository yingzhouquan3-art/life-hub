"""商户分类记忆的 HTTP 接口。"""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.db import db
from backend.modules.categorize import (
    delete_rule,
    get_categorize_state,
    learn_category,
    suggest_category,
    update_rule,
)

router = APIRouter()


class RuleIn(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=40)
    category: Literal["food", "transport", "study", "housing", "medical",
                      "entertainment", "social", "digital", "other"]


@router.get("/api/categorize")
def categorize_state():
    with db() as conn:
        return get_categorize_state(conn)


@router.get("/api/categorize/suggest")
def categorize_suggest(text: str = ""):
    """给一段文本猜分类。猜不出来返回 null，不硬给默认值。"""
    with db() as conn:
        return {"suggestion": suggest_category(conn, text)}


@router.post("/api/categorize/rules")
def add_rule(body: RuleIn):
    """手动加一条规则。和确认时学到的规则等价，可以随时删掉。"""
    with db() as conn:
        rule = learn_category(conn, body.keyword, body.category, keyword=body.keyword)
        return {"rule": rule, "categorize": get_categorize_state(conn)}


class RulePatchIn(BaseModel):
    """只带上要改的字段。两个都可以单独改。"""

    keyword: Optional[str] = Field(None, min_length=1, max_length=40)
    category: Optional[
        Literal["food", "transport", "study", "housing", "medical",
                "entertainment", "social", "digital", "other"]
    ] = None


@router.patch("/api/categorize/rules/{rule_id}")
def patch_rule(rule_id: int, body: RulePatchIn):
    """改一条规则的关键字或分类。

    改分类也能靠「同名再添加一次」做到，但关键字本身改不了——写错一个字
    只能删了重建，而重建会把命中次数清零。
    """
    given = body.model_dump(exclude_unset=True)
    if not given:
        raise HTTPException(400, "没有要修改的字段")
    with db() as conn:
        rule = update_rule(conn, rule_id, **given)
        return {"rule": rule, "categorize": get_categorize_state(conn)}


@router.delete("/api/categorize/rules/{rule_id}")
def remove_rule(rule_id: int):
    with db() as conn:
        return {"deleted": delete_rule(conn, rule_id), "categorize": get_categorize_state(conn)}
