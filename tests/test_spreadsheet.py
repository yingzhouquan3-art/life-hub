"""读 .xlsx。

微信和支付宝现在导出的是 Excel 或 PDF，没有 CSV 了，所以这条路必须通。

下面的样本是**合成的**：按 Excel 真实产出的结构手工拼出来（共享字符串表、
带日期格式的样式、内联字符串、数字单元格）。它证明不了「所有真实文件都能读」，
只能证明这几种常见构造读得对。真实文件读不动时，导入界面会把实际看到的
表格摊出来——那才是排查的依据。
"""
import io
import unittest
import zipfile

from fastapi import HTTPException

from backend.spreadsheet import (
    describe,
    looks_like_legacy_xls,
    looks_like_pdf,
    looks_like_xlsx,
    read_xlsx,
    to_csv_text,
)

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
</Types>"""

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_WORKBOOK = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
          xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="交易明细" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>"""

_WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""

# 样式 0 普通，样式 1 是日期时间格式（自定义 numFmtId 176）
_STYLES = """<?xml version="1.0" encoding="UTF-8"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="1">
    <numFmt numFmtId="176" formatCode="yyyy\\-mm\\-dd\\ hh:mm:ss"/>
  </numFmts>
  <cellXfs count="3">
    <xf numFmtId="0"/>
    <xf numFmtId="176"/>
    <xf numFmtId="4"/>
  </cellXfs>
</styleSheet>"""


def build_xlsx(shared, sheet_rows_xml):
    """按 Excel 真实产出的结构拼一个 xlsx。"""
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared)}" uniqueCount="{len(shared)}">'
        + "".join(f"<si><t>{value}</t></si>" for value in shared)
        + "</sst>"
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{sheet_rows_xml}</sheetData></worksheet>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("xl/workbook.xml", _WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        archive.writestr("xl/styles.xml", _STYLES)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


class XlsxReadingTests(unittest.TestCase):
    def sample(self):
        shared = ["交易时间", "交易对方", "商品", "收/支", "金额(元)", "星巴克", "拿铁", "支出"]
        rows = (
            '<row r="1">'
            '<c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>'
            '<c r="C1" t="s"><v>2</v></c><c r="D1" t="s"><v>3</v></c>'
            '<c r="E1" t="s"><v>4</v></c></row>'
            # 第二行：日期是序号 + 日期样式，金额是数字，其余是共享字符串
            '<row r="2">'
            '<c r="A2" s="1"><v>46235.383333</v></c>'
            '<c r="B2" t="s"><v>5</v></c><c r="C2" t="s"><v>6</v></c>'
            '<c r="D2" t="s"><v>7</v></c>'
            '<c r="E2" s="2"><v>32</v></c></row>'
            # 第三行：内联字符串，且中间空了一格（B 列缺失）
            '<row r="3">'
            '<c r="A3" t="inlineStr"><is><t>2026-08-02 12:30:00</t></is></c>'
            '<c r="C3" t="inlineStr"><is><t>快车</t></is></c>'
            '<c r="D3" t="s"><v>7</v></c>'
            '<c r="E3"><v>18.5</v></c></row>'
        )
        return build_xlsx(shared, rows)

    def test_headers_come_through_as_text(self):
        table = read_xlsx(self.sample())
        self.assertEqual(table[0][:5],
                         ["交易时间", "交易对方", "商品", "收/支", "金额(元)"])

    def test_date_serials_become_readable_dates(self):
        """Excel 把日期存成 46235.38 这样的序号。原样输出的话「交易时间」
        整列都是数字，账单解析器会判定认不出，整个文件白导。"""
        table = read_xlsx(self.sample())
        self.assertTrue(table[1][0].startswith("2026-"), table[1][0])
        self.assertIn(":", table[1][0], "带时间的序号应当保留时分秒")

    def test_plain_numbers_are_not_mistaken_for_dates(self):
        """金额那列也是数字，不能被当成日期转成 1900 年的某一天。"""
        table = read_xlsx(self.sample())
        self.assertEqual(table[1][4], "32")
        self.assertEqual(table[2][4], "18.5")

    def test_inline_strings_are_read(self):
        table = read_xlsx(self.sample())
        self.assertEqual(table[2][0], "2026-08-02 12:30:00")

    def test_missing_cells_keep_the_column_alignment(self):
        """B 列缺失时不能让后面的值整体左移一格，否则金额会跑到分类列。"""
        table = read_xlsx(self.sample())
        self.assertEqual(table[2][1], "")
        self.assertEqual(table[2][2], "快车")

    def test_the_result_feeds_the_existing_csv_parser(self):
        """Excel 只是换了一种装法，不该为它再写一套账单解析。"""
        text = to_csv_text(read_xlsx(self.sample()))
        self.assertIn("交易时间", text)
        self.assertIn("星巴克", text)

    def test_a_broken_file_says_so_instead_of_crashing(self):
        with self.assertRaises(HTTPException):
            read_xlsx("这不是一个 zip".encode("utf-8"))

    def test_describe_shows_what_was_actually_seen(self):
        """真实文件读不动时，得让用户看到「我读到了什么」才有排查的余地。"""
        info = describe(read_xlsx(self.sample()))
        self.assertEqual(info["rows"], 3)
        self.assertGreaterEqual(info["columns"], 5)
        self.assertIn("交易时间", info["preview"][0])


class FormatDetectionTests(unittest.TestCase):
    def test_xlsx_is_recognised_by_content_not_just_by_name(self):
        data = XlsxReadingTests().sample()
        self.assertTrue(looks_like_xlsx("账单.xlsx", data))
        self.assertTrue(looks_like_xlsx("改过名字", data), "改了名字也该认得出来")

    def test_csv_is_not_mistaken_for_xlsx(self):
        self.assertFalse(looks_like_xlsx("账单.csv", "交易时间,金额\n".encode()))

    def test_pdf_is_recognised(self):
        self.assertTrue(looks_like_pdf("账单.pdf", b"%PDF-1.7 ..."))
        self.assertFalse(looks_like_pdf("账单.csv", b"a,b\n"))

    def test_legacy_xls_is_recognised_so_it_can_be_refused_clearly(self):
        """2003 版 .xls 是完全不同的二进制格式，这里读不了——
        但要认出来并说清楚，而不是丢一句「文件损坏」。"""
        self.assertTrue(looks_like_legacy_xls("账单.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest"))


if __name__ == "__main__":
    unittest.main()
