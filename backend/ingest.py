"""一个文件进来，先弄清楚它是什么、该进哪个模块。

平台现在有好几种能导入的东西：微信账单、支付宝账单、本平台的通用模板、
运动 App 导出的训练记录和体重记录。让用户自己先想清楚"我这个文件算哪一类、
该点哪个按钮"，是把平台内部的分工推给了用户。这里把那一步接过来。

三条边界：

1. **只判断，不写入。** 识别和预览全程只读，写入永远是用户看过预览之后的
   另一次动作。
2. **判断要说得出依据。** 每个候选都带着"我为什么这么认为"——表头里有哪几列、
   文件开头出现了什么字样。用户能据此判断我是不是猜错了。
3. **猜错必须能改。** 识别给的是候选列表而不是结论，排第二的那个也列出来，
   用户可以直接改选，不需要换一个页面重来。

识别不认识的文件不硬套一个类型：宁可说"认不出来"，也不要把体重数据
当成账单写进账本。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException

from backend.health_import import build_health_preview
from backend.spreadsheet import (
    describe,
    looks_like_legacy_xls,
    looks_like_pdf,
    looks_like_xlsx,
    read_xlsx,
    to_csv_text,
)
from backend.statements import build_preview as build_statement_preview
from backend.statements import detect_source
from backend.statements import reconcile as reconcile_transactions
from backend.template_csv import parse_template


@dataclass(frozen=True)
class Format:
    """一种能被导入的文件。

    module 是它最终会写进哪个模块，用来在界面上说清楚"确认之后东西会去哪"。
    """

    key: str
    label: str
    module: str
    module_label: str
    outcome: str


FORMATS = (
    Format("wechat_statement", "微信支付账单", "ledger", "个人账本",
           "和已有交易对账，只写入还没记过的那些行"),
    Format("alipay_statement", "支付宝账单", "ledger", "个人账本",
           "和已有交易对账，只写入还没记过的那些行"),
    Format("health_workout", "运动 App 的训练记录", "fitness", "个人健身",
           "和已有训练对账，只补没记过的那些天"),
    Format("health_body", "运动 App 的体重 / 体脂记录", "body", "身体数据",
           "和已有测量对账，只补没记过的那些天"),
    Format("ledger_template", "本平台的账目模板", "ledger", "个人账本",
           "和已有交易对账，只写入还没记过的那些行"),
)

FORMAT_BY_KEY = {item.key: item for item in FORMATS}

# 只看开头一段：表头总在前面，整篇扫一遍既慢又容易被正文里的字样带偏。
_HEAD_CHARS = 4000

# 各格式的判断线索。命中一条加一分，并把这条线索原样讲给用户听。
_SIGNALS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "wechat_statement": (
        ("文件开头出现「微信支付」字样", ("微信支付", "微信昵称")),
        ("表头里有「交易时间」", ("交易时间",)),
        ("表头里有「收/支」", ("收/支", "收支")),
        ("表头里有「当前状态」", ("当前状态",)),
    ),
    "alipay_statement": (
        ("文件开头出现「支付宝」字样", ("支付宝",)),
        ("表头里有「交易号」或「商家订单号」", ("交易号", "商家订单号")),
        ("表头里有「交易时间」或「交易创建时间」", ("交易时间", "交易创建时间")),
        ("表头里有「资金流向」或「收/支」", ("资金流向", "收/支")),
    ),
    "health_workout": (
        ("表头里有运动类型这一列", ("运动类型", "运动项目", "exerciseType")),
        ("表头里有时长这一列", ("运动时长", "锻炼时长", "时长", "duration")),
        ("表头里有距离或消耗这一列", ("距离", "卡路里", "消耗", "distance", "calories")),
    ),
    "health_body": (
        ("表头里有体重这一列", ("体重", "weight")),
        ("表头里有体脂这一列", ("体脂", "bodyFat")),
        ("表头里有测量时间或日期这一列", ("测量时间", "日期", "date")),
    ),
    "ledger_template": (
        ("表头里有 date 或「日期」这一列", ("date", "日期")),
        ("表头里有 amount 或「金额」这一列", ("amount", "金额")),
        ("表头里有 type 或「类型」这一列", ("type", "类型")),
        ("表头里有 category 或「分类」这一列", ("category", "分类")),
    ),
}

# 低于这个分数就不当成一个真的候选：一条线索命中往往只是巧合，
# 「日期」这种列名几乎每种文件都有。
_MIN_SCORE = 2


def _evidence(head: str, key: str) -> list[str]:
    hits = []
    for reason, needles in _SIGNALS[key]:
        if any(needle in head for needle in needles):
            hits.append(reason)
    return hits


def identify(filename: str, text: str) -> dict:
    """看一眼这是什么文件，给出候选和依据。只读，不解析全文。"""
    head = text[:_HEAD_CHARS]
    candidates = []
    for item in FORMATS:
        evidence = _evidence(head, item.key)
        if len(evidence) < _MIN_SCORE:
            continue
        candidates.append({
            "kind": item.key,
            "label": item.label,
            "module": item.module,
            "module_label": item.module_label,
            "outcome": item.outcome,
            "score": len(evidence),
            "evidence": evidence,
        })

    # detect_source 是账单解析器自己的判断，比这里的通用线索更权威，
    # 命中时把对应候选顶到最前面，理由也如实写出来。
    source = detect_source(text)
    if source:
        preferred = f"{source}_statement"
        for candidate in candidates:
            if candidate["kind"] == preferred:
                candidate["score"] += 2
                candidate["evidence"].insert(0, "账单解析器认出了这是它能处理的格式")

    candidates.sort(key=lambda item: (-item["score"], item["kind"]))
    lowered = (filename or "").lower()
    return {
        "filename": filename,
        "candidates": candidates,
        "best": candidates[0]["kind"] if candidates else None,
        "ambiguous": len(candidates) > 1 and len({c["score"] for c in candidates}) == 1,
        "note": (
            "认出来的只是文件的样子，不是它的内容对不对。"
            "确认写入前请看一遍预览里的条数和金额。"
            if candidates else
            "认不出这是什么文件。可以自己指定类型再试，"
            "或者确认导出的是 CSV 而不是 Excel、PDF。"
        ),
        "looks_like_spreadsheet": lowered.endswith((".xls", ".xlsx")),
    }


def to_table_text(filename: str, raw: bytes) -> str:
    """把上传的文件变成一段可解析的文本表格。

    微信和支付宝现在导出的是 **Excel 或 PDF，没有 CSV**。所以这一层先把
    Excel 转成 CSV 文本，后面那套账单解析器一个字都不用改——它本来就会
    自己找表头、认列名，不在乎数据是从哪种容器里倒出来的。

    读不了的格式要**当场说清楚是什么、该怎么办**，而不是丢一句「解析失败」
    让人去猜。PDF 是版式文件，里面的表格是画出来的不是存出来的；
    2003 版 .xls 是另一套二进制格式。这两种都让用户回去换个导出格式，
    比我在这里勉强猜要可靠。
    """
    if looks_like_pdf(filename, raw):
        raise HTTPException(
            400,
            "这是 PDF。PDF 里的表格是画上去的，取不回可靠的金额和日期。"
            "请在微信里重新导出时选 Excel（.xlsx）。",
        )
    if looks_like_legacy_xls(filename, raw):
        raise HTTPException(
            400,
            "这是老版 .xls 格式，读不了。用 Excel 或 WPS 打开它，"
            "另存为「Excel 工作簿 (.xlsx)」再导入。",
        )
    if looks_like_xlsx(filename, raw):
        table = read_xlsx(raw)
        if not table:
            raise HTTPException(400, "这个 Excel 文件里没有读到任何一行")
        return to_csv_text(table)

    # 剩下的按文本处理。微信和支付宝的 CSV 导出常是 GB18030。
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "这个文件的编码认不出来，可能不是表格文件")


def inspect_table(filename: str, raw: bytes) -> dict:
    """认不出来的时候，把实际读到的表格摊开给用户看。

    只说「认不出这是什么文件」，用户既不知道哪里不对，也没法告诉别人。
    把前几行原样列出来，至少能看出是表头不对、还是整份文件都读空了。
    """
    if not looks_like_xlsx(filename, raw):
        return {}
    try:
        return describe(read_xlsx(raw))
    except HTTPException:
        return {}


def _statement_envelope(conn, kind: str, filename: str, text: str) -> dict:
    source = "wechat" if kind == "wechat_statement" else "alipay"
    preview = build_statement_preview(conn, text, source)
    reconciliation = preview["reconciliation"]
    return {
        "rows": reconciliation["new"],
        "matched": reconciliation["matched"],
        "skipped": preview.get("skipped", []),
        "review": preview.get("review", []),
        "summary": {
            "parsed": len(preview["rows"]),
            "will_write": len(reconciliation["new"]),
            "already_have": len(reconciliation["matched"]),
            "skipped": len(preview.get("skipped", [])),
            "amount": reconciliation["summary"].get("new_amount"),
            "date_from": reconciliation["summary"].get("date_from"),
            "date_to": reconciliation["summary"].get("date_to"),
        },
        "categories": preview.get("categories"),
        "detail": preview,
    }


def _health_envelope(conn, kind: str, filename: str, text: str) -> dict:
    health_kind = "workout" if kind == "health_workout" else "body"
    preview = build_health_preview(conn, text, health_kind)
    reconciliation = preview["reconciliation"]
    return {
        "rows": reconciliation["new"],
        "matched": reconciliation["matched"],
        "skipped": preview.get("skipped", []),
        "review": preview.get("review", []),
        "summary": {
            "parsed": len(preview.get("rows", [])),
            "will_write": len(reconciliation["new"]),
            "already_have": len(reconciliation["matched"]),
            "skipped": len(preview.get("skipped", [])),
        },
        "detail": preview,
    }


def _template_envelope(conn, kind: str, filename: str, text: str) -> dict:
    """本平台模板走和账单同一套对账与分类，只是解析器不同。"""
    from backend.modules.categorize import suggest_category

    accounts = {row["name"].strip().lower(): row["id"]
                for row in conn.execute(
                    "SELECT id, name FROM accounts WHERE is_active = 1")}
    default_account = conn.execute(
        "SELECT id FROM accounts WHERE is_active = 1 ORDER BY id LIMIT 1").fetchone()
    parsed = parse_template(text, default_account["id"] if default_account else None, accounts)

    # 模板里没填分类的支出，按商户规则猜一个——和账单那条路一致。
    # 同样不回写规则：批量导入不是用户对每一行的确认。
    for row in parsed["rows"]:
        if row["type"] != "expense" or row.get("category") not in (None, "other"):
            continue
        hit = suggest_category(conn, row.get("note", ""))
        if hit:
            row["category"] = hit["category"]
            row["category_by"] = hit["keyword"]

    result = reconcile_transactions(conn, parsed["rows"])
    return {
        "rows": result["new"],
        "matched": result["matched"],
        "skipped": parsed["skipped"],
        "review": parsed["review"],
        "summary": {
            "parsed": len(parsed["rows"]),
            "will_write": len(result["new"]),
            "already_have": len(result["matched"]),
            "skipped": len(parsed["skipped"]),
            "amount": result["summary"].get("new_amount"),
            "date_from": result["summary"].get("date_from"),
            "date_to": result["summary"].get("date_to"),
        },
        "detail": parsed,
    }


_BUILDERS = {
    "wechat_statement": _statement_envelope,
    "alipay_statement": _statement_envelope,
    "health_workout": _health_envelope,
    "health_body": _health_envelope,
    "ledger_template": _template_envelope,
}


def build_ingest_preview(conn, kind: str, filename: str, text: str) -> dict:
    """按已选定的类型做预览。全程只读。

    真正的解析仍然交给各自的解析器，这里只把结果套进同一个信封，
    好让一个界面能显示所有类型。
    """
    item = FORMAT_BY_KEY.get(kind)
    if not item:
        raise HTTPException(400, f"未知的导入类型：{kind}")
    envelope = _BUILDERS[kind](conn, kind, filename, text)
    return {
        "kind": item.key,
        "label": item.label,
        "module": item.module,
        "module_label": item.module_label,
        "outcome": item.outcome,
        "filename": filename,
        **envelope,
        "note": "预览不写入任何数据。确认之后只写「还没记过」的那些行。",
    }


def formats() -> list[dict]:
    return [
        {"kind": item.key, "label": item.label, "module": item.module,
         "module_label": item.module_label, "outcome": item.outcome}
        for item in FORMATS
    ]
