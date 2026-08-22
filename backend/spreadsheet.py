"""把 .xlsx 读成一张表格，只用标准库。

微信和支付宝现在导出的账单是 Excel 或 PDF，**没有 CSV 这个选项**了。
原来那条只认 CSV 的导入路径，对着真实文件是用不了的。

为什么不用 openpyxl：启动器里的依赖检查把包名写死成
`import fastapi, uvicorn, pydantic`，加一个依赖它察觉不到，pip 不会跑，
用户下次启动会得到一个能开但一导入就崩的应用。要么同时改那处检查
（两个地方各写一份依赖清单，迟早对不上），要么不加依赖。xlsx 本身就是
一个 zip 装着几份 XML，读出「每格的文本」这件事标准库完全够用。

这里只做一件事：把第一张工作表变成 list[list[str]]，剩下的交给原来的
账单解析器——它已经会自己找表头、认列名了，不在乎数据是从 CSV 还是
Excel 来的。

**不求解析出 Excel 的全部语义。** 公式取缓存值，样式一概不管。
唯一特殊处理的是日期：Excel 把日期存成序号（45900.5），原样输出的话
「交易时间」那列会变成一串数字，整个文件都会被判成认不出。
"""
from __future__ import annotations

import re
import zipfile
from datetime import datetime, timedelta
from xml.etree import ElementTree

from fastapi import HTTPException

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

# Excel 内置的日期时间格式编号。自定义格式另外按格式串判断。
_BUILTIN_DATE_FORMATS = frozenset({14, 15, 16, 17, 18, 19, 20, 21, 22,
                                   27, 30, 36, 45, 46, 47, 50, 57})
_DATE_HINT = re.compile(r"[ymdhs]", re.IGNORECASE)
# 这些字符出现在格式串里说明它是数字格式而不是日期（比如 #,##0.00）
_NUMERIC_ONLY = re.compile(r"^[#0.,%\s\\\"'¥$€\[\]a-zA-Z_\-;()@*]*$")

MAX_ROWS = 20000
MAX_COLUMNS = 64


def looks_like_xlsx(filename: str, content: bytes) -> bool:
    """按内容判断，不只看后缀——用户可能把文件改过名。"""
    if content[:2] != b"PK":
        return False
    if filename.lower().endswith((".xlsx", ".xlsm")):
        return True
    try:
        with zipfile.ZipFile(_as_stream(content)) as archive:
            return "xl/workbook.xml" in archive.namelist()
    except zipfile.BadZipFile:
        return False


def looks_like_pdf(filename: str, content: bytes) -> bool:
    return content[:5] == b"%PDF-" or filename.lower().endswith(".pdf")


def looks_like_legacy_xls(filename: str, content: bytes) -> bool:
    """2003 版 .xls 是另一种完全不同的二进制格式，这里读不了。"""
    return content[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" or filename.lower().endswith(".xls")


def _as_stream(content: bytes):
    import io

    return io.BytesIO(content)


def _column_index(reference: str) -> int:
    """A1 -> 0，AB7 -> 27。只取字母部分。"""
    index = 0
    for char in reference:
        if not char.isalpha():
            break
        index = index * 26 + (ord(char.upper()) - 64)
    return max(index - 1, 0)


def _serial_to_text(serial: float) -> str:
    """Excel 的日期序号转成文本。

    以 1899-12-30 为原点是为了绕开 Excel 那个著名的 1900 闰年错误——
    它认为 1900 年有 2 月 29 日，所以 1900-03-01 之后的序号都比真实天数多 1，
    用 12-30 当原点正好抵消。1900 年 3 月之前的日期本来就不会出现在账单里。
    """
    base = datetime(1899, 12, 30)
    moment = base + timedelta(days=serial)
    if abs(serial - round(serial)) < 1e-6:
        return moment.strftime("%Y-%m-%d")
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def _date_styles(archive: zipfile.ZipFile) -> set[int]:
    """哪些单元格样式是日期。返回样式下标的集合。"""
    try:
        raw = archive.read("xl/styles.xml")
    except KeyError:
        return set()
    root = ElementTree.fromstring(raw)

    custom: dict[int, str] = {}
    for fmt in root.iter(f"{_NS}numFmt"):
        try:
            custom[int(fmt.get("numFmtId", "-1"))] = fmt.get("formatCode", "")
        except ValueError:
            continue

    date_styles = set()
    fills = root.find(f"{_NS}cellXfs")
    if fills is None:
        return date_styles
    for index, xf in enumerate(fills.findall(f"{_NS}xf")):
        try:
            fmt_id = int(xf.get("numFmtId", "0"))
        except ValueError:
            continue
        if fmt_id in _BUILTIN_DATE_FORMATS:
            date_styles.add(index)
            continue
        code = custom.get(fmt_id)
        if code and _DATE_HINT.search(code) and not _NUMERIC_ONLY.match(code):
            date_styles.add(index)
    return date_styles


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ElementTree.fromstring(raw)
    values = []
    for item in root.findall(f"{_NS}si"):
        # 一个 si 可能被拆成多段 t（不同格式的片段），要拼起来
        values.append("".join(node.text or "" for node in item.iter(f"{_NS}t")))
    return values


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    """按 workbook 里的顺序取第一张表，而不是文件名排序。

    sheet1.xml 不一定是用户看到的第一张表；账单文件通常只有一张，
    但按声明顺序取才是对的。
    """
    names = archive.namelist()
    try:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError:
        candidates = sorted(n for n in names if n.startswith("xl/worksheets/sheet"))
        if not candidates:
            raise HTTPException(400, "这个 Excel 文件里没有找到工作表")
        return candidates[0]

    target_by_id = {
        rel.get("Id"): rel.get("Target", "")
        for rel in rels.iter()
        if rel.get("Id")
    }
    for sheet in workbook.iter(f"{_NS}sheet"):
        target = target_by_id.get(sheet.get(f"{_REL_NS}id"))
        if not target:
            continue
        path = target if target.startswith("xl/") else f"xl/{target.lstrip('/')}"
        if path in names:
            return path
    candidates = sorted(n for n in names if n.startswith("xl/worksheets/sheet"))
    if not candidates:
        raise HTTPException(400, "这个 Excel 文件里没有找到工作表")
    return candidates[0]


def read_xlsx(content: bytes) -> list[list[str]]:
    """把第一张工作表读成一张纯文本表格。"""
    try:
        archive = zipfile.ZipFile(_as_stream(content))
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "这个文件打不开，可能不是有效的 Excel 文件") from exc

    with archive:
        strings = _shared_strings(archive)
        date_styles = _date_styles(archive)
        sheet = ElementTree.fromstring(archive.read(_first_sheet_path(archive)))

        rows: list[list[str]] = []
        for row_node in sheet.iter(f"{_NS}row"):
            if len(rows) >= MAX_ROWS:
                break
            cells: list[str] = []
            for cell in row_node.findall(f"{_NS}c"):
                position = _column_index(cell.get("r", ""))
                if position >= MAX_COLUMNS:
                    continue
                while len(cells) < position:
                    cells.append("")
                cells.append(_cell_text(cell, strings, date_styles))
            rows.append(cells)
    return rows


def _cell_text(cell, strings: list[str], date_styles: set[int]) -> str:
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        node = cell.find(f"{_NS}is")
        return "".join(t.text or "" for t in node.iter(f"{_NS}t")) if node is not None else ""

    value_node = cell.find(f"{_NS}v")
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text

    if kind == "s":
        try:
            return strings[int(raw)]
        except (ValueError, IndexError):
            return ""
    if kind in ("str", "e"):
        return raw
    if kind == "b":
        return "TRUE" if raw == "1" else "FALSE"

    # 数字。可能其实是个日期。
    try:
        number = float(raw)
    except ValueError:
        return raw
    try:
        style = int(cell.get("s", "-1"))
    except ValueError:
        style = -1
    if style in date_styles and number > 0:
        return _serial_to_text(number)
    if number.is_integer():
        return str(int(number))
    return repr(number) if len(repr(number)) < 17 else f"{number:.6f}".rstrip("0")


def to_csv_text(rows: list[list[str]]) -> str:
    """转成 CSV 文本，好交给已有的账单解析器。

    它已经会自己找表头、认列名，不该为了 Excel 再写一套。
    """
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def describe(rows: list[list[str]], limit: int = 6) -> dict:
    """解析不出东西时，把「我实际看到了什么」摊开给用户看。

    否则用户只知道「导入失败」，既不知道哪里不对，也没法告诉别人。
    """
    return {
        "rows": len(rows),
        "columns": max((len(r) for r in rows), default=0),
        "preview": [row[:12] for row in rows[:limit]],
    }
