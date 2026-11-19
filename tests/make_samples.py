#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 5 种格式的虚构脱敏测试样例文档（所有姓名、单位、证件号、密钥均属随机/算法构造）。"""

import io
import os
import sys
import zipfile
import docx
from lxml import etree
import openpyxl
from openpyxl.comments import Comment
import pptx
from pptx.util import Inches, Pt
try:
    import pymupdf
except ImportError:  # 没装 PyMuPDF 时只生成另外 4 种格式
    pymupdf = None
from PIL import Image, ImageDraw

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from textveil.formats import ooxml_utils as ox
if pymupdf is not None:
    from textveil.formats.pdf_handler import pick_cjk_font


def make_valid_idcard(prefix17: str = "11010119900307123") -> str:
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    codes = "10X98765432"
    s = sum(int(prefix17[i]) * weights[i] for i in range(17))
    return prefix17 + codes[s % 11]


def make_valid_uscc(prefix17: str = "91110108MA01ABCD2") -> str:
    chars = "0123456789ABCDEFGHJKLMNPQRTUWXY"
    weights = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)
    s = sum(chars.index(prefix17[i]) * weights[i] for i in range(17))
    return prefix17 + chars[(31 - (s % 31)) % 31]


def make_valid_luhn(prefix15: str = "622202100112233") -> str:
    digits = [int(c) for c in prefix15]
    # append placeholder 0, compute luhn sum for 16 digits
    rev = (digits + [0])[::-1]
    total = 0
    for i, d in enumerate(rev):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    check = (10 - (total % 10)) % 10
    return prefix15 + str(check)


SAMPLE_ID1 = make_valid_idcard("11010119900307123")
SAMPLE_ID2 = make_valid_idcard("31011519881122456")
SAMPLE_USCC1 = make_valid_uscc("91110108MA01ABCD2")
SAMPLE_USCC2 = make_valid_uscc("91330106MA28XY9T5")
SAMPLE_BANK1 = make_valid_luhn("622202100112233")


def create_docx(out_path: str):
    doc = docx.Document()
    doc.core_properties.author = "陈敏"
    doc.core_properties.last_modified_by = "王磊"
    doc.core_properties.title = "北京云枢科技有限公司合作协议"
    doc.core_properties.comments = "内部流转稿"

    sec = doc.sections[0]
    sec.header.paragraphs[0].text = "项目名称：云栖智算一期项目 · 北京云枢科技有限公司"
    sec.footer.paragraphs[0].text = "内部联系人：陈敏 · 电话：010-88886666"

    doc.add_heading("商业合作协议（测试样例）", level=1)

    # 跨 Run 拆分的敏感信息
    p = doc.add_paragraph("本协议由")
    r1 = p.add_run("北京云枢")
    r1.bold = True
    p.add_run("科技有限公司与杭州星澜智能研究院签署。项目联系人：张")
    p.add_run("伟，联系电话：138")
    p.add_run("12345678，电子邮箱：zhangwei@")
    p.add_run("yunshu-cloud.cn。")

    p2 = doc.add_paragraph("通讯地址：北京市海淀区中关村南大街甲18号院2号楼。统一社会信用代码：" + SAMPLE_USCC1 + "。")
    p3 = doc.add_paragraph("遵循中华人民共和国国家标准规范执行，本条为公开合规条款。")

    # 表格（含列头与键值对）
    tbl = doc.add_table(rows=3, cols=4)
    headers = ["姓名", "身份证号", "银行卡号", "部门"]
    for i, h in enumerate(headers):
        tbl.rows[0].cells[i].text = h
    tbl.rows[1].cells[0].text = "李雪"
    tbl.rows[1].cells[1].text = SAMPLE_ID1
    tbl.rows[1].cells[2].text = SAMPLE_BANK1
    tbl.rows[1].cells[3].text = "研发部"

    tbl.rows[2].cells[0].text = "欧阳明"
    tbl.rows[2].cells[1].text = SAMPLE_ID2
    tbl.rows[2].cells[2].text = SAMPLE_BANK1
    tbl.rows[2].cells[3].text = "财务部"

    kv_tbl = doc.add_table(rows=2, cols=2)
    kv_tbl.rows[0].cells[0].text = "合同金额"
    kv_tbl.rows[0].cells[1].text = "¥1,280,000.00"
    kv_tbl.rows[1].cells[0].text = "对公账号"
    kv_tbl.rows[1].cells[1].text = "6222021001998877665"

    doc.save(out_path)

    # 注入原生 XML 边界用例：批注 (comments.xml)、修订 (<w:del>/<w:ins>)、嵌套文本框 (<w:txbxContent>)、外部超链接、自定义属性
    order, entries = ox.read_zip_entries(out_path)
    doc_xml = ox.parse_xml(entries["word/document.xml"])
    body = doc_xml.find(f"{{{ox.NS_W}}}body")

    # 嵌套文本框段落（模拟外层 w:p 里包含 w:txbxContent -> w:p）
    outer_p = etree.Element(ox.W_P)
    r_box = etree.SubElement(outer_p, f"{{{ox.NS_W}}}r")
    pict = etree.SubElement(r_box, f"{{{ox.NS_W}}}pict")
    txbx = etree.SubElement(pict, ox.W_TXBX)
    inner_p = etree.SubElement(txbx, ox.W_P)
    inner_r = etree.SubElement(inner_p, f"{{{ox.NS_W}}}r")
    inner_t = etree.SubElement(inner_r, ox.W_T)
    inner_t.text = "文本框保密联系人：赵强 13900001111"
    body.insert(len(body) - 1, outer_p)

    # 修订记录 (<w:del> 含被删私钥 + <w:ins> 含批注锚点)
    rev_p = etree.Element(ox.W_P)
    del_el = etree.SubElement(rev_p, ox.W_DEL)
    del_el.set(f"{{{ox.NS_W}}}id", "1")
    del_el.set(f"{{{ox.NS_W}}}author", "王磊")
    del_r = etree.SubElement(del_el, f"{{{ox.NS_W}}}r")
    del_t = etree.SubElement(del_r, ox.W_DELTEXT)
    del_t.text = "被删除旧密钥sk-proj-DeletedTrackSecret99887766"

    ins_el = etree.SubElement(rev_p, ox.W_INS)
    ins_el.set(f"{{{ox.NS_W}}}id", "2")
    ins_el.set(f"{{{ox.NS_W}}}author", "王磊")
    ins_r = etree.SubElement(ins_el, f"{{{ox.NS_W}}}r")
    ins_t = etree.SubElement(ins_r, ox.W_T)
    ins_t.text = "协议附件已核定。"

    c_start = etree.SubElement(rev_p, ox.W_COMMENT_RANGE_START)
    c_start.set(f"{{{ox.NS_W}}}id", "0")
    c_end = etree.SubElement(rev_p, ox.W_COMMENT_RANGE_END)
    c_end.set(f"{{{ox.NS_W}}}id", "0")
    c_ref_r = etree.SubElement(rev_p, f"{{{ox.NS_W}}}r")
    c_ref = etree.SubElement(c_ref_r, ox.W_COMMENT_REF)
    c_ref.set(f"{{{ox.NS_W}}}id", "0")
    body.insert(len(body) - 1, rev_p)
    entries["word/document.xml"] = ox.serialize_xml(doc_xml)

    # word/comments.xml + rel + content type
    comments_xml = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:comments xmlns:w="{ox.NS_W}">'
        f'<w:comment w:id="0" w:author="陈敏" w:initials="CM">'
        f'<w:p><w:r><w:t>底价批注：李雪确认最低成交价 950000 元</w:t></w:r></w:p>'
        f'</w:comment></w:comments>'
    ).encode("utf-8")
    entries["word/comments.xml"] = comments_xml
    order.append("word/comments.xml")

    # 外部 mailto 超链接与 comments 关系
    rels_root = ox.parse_xml(entries["word/_rels/document.xml.rels"])
    rel_c = etree.SubElement(rels_root, f"{{{ox.NS_REL}}}Relationship")
    rel_c.set("Id", "rId900")
    rel_c.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments")
    rel_c.set("Target", "comments.xml")
    rel_ext = etree.SubElement(rels_root, f"{{{ox.NS_REL}}}Relationship")
    rel_ext.set("Id", "rId901")
    rel_ext.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink")
    rel_ext.set("Target", "mailto:zhangwei@yunshu-cloud.cn")
    rel_ext.set("TargetMode", "External")
    entries["word/_rels/document.xml.rels"] = ox.serialize_xml(rels_root)

    # docProps/app.xml 注入 Company
    app_root = ox.parse_xml(entries["docProps/app.xml"])
    comp_el = etree.SubElement(app_root, f"{{{ox.NS_APP}}}Company")
    comp_el.text = "北京云枢科技有限公司"
    entries["docProps/app.xml"] = ox.serialize_xml(app_root)

    # Content_Types 注册 comments.xml
    ct_root = ox.parse_xml(entries["[Content_Types].xml"])
    ov = etree.SubElement(ct_root, f"{{{ox.NS_CT}}}Override")
    ov.set("PartName", "/word/comments.xml")
    ov.set("ContentType", "application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml")
    entries["[Content_Types].xml"] = ox.serialize_xml(ct_root)

    ox.write_zip_entries(out_path, order, entries)


def create_xlsx(out_path: str):
    wb = openpyxl.Workbook()
    wb.properties.creator = "陈敏"
    wb.properties.lastModifiedBy = "王磊"
    wb.properties.title = "2026项目台账"

    ws = wb.active
    ws.title = "项目台账"
    ws.oddHeader.center.text = "北京云枢科技有限公司 · 内部项目台账"
    ws.append(["姓名", "手机", "邮箱", "所属企业", "统一社会信用代码", "合同金额", "备注"])
    ws.append(["张伟", "13812345678", "zhangwei@yunshu-cloud.cn", "北京云枢科技有限公司", SAMPLE_USCC1, 1280000, "重点客户"])
    ws.append(["李雪", "13900001111", "lixue@xinglan-ai.cn", "杭州星澜智能研究院", SAMPLE_USCC2, 560000, "已签约"])
    ws.append(["合计", "", "", "", "", "=SUM(F2:F3)", '=IF(F2>100000,"张伟负责","普通")'])

    ws["A2"].comment = Comment("内部备注：张伟直属电话 010-88886666", "陈敏")
    ws["C2"].hyperlink = "mailto:zhangwei@yunshu-cloud.cn"

    ws_hidden = wb.create_sheet("内部密钥")
    ws_hidden.sheet_state = "hidden"
    ws_hidden.append(["配置项", "敏感值"])
    ws_hidden.append(["OpenAI Key", "sk-proj-XlsxHiddenKeyAbCdEf12345678"])
    ws_hidden.append(["AWS Key", "AKIAIOSFODNN7EXAMPLE"])
    ws_hidden.append(["数据库连接", "postgresql://dbadmin:SuperSecret99@10.20.30.40:5432/prod"])
    ws_hidden.append(["内网主机", "192.168.10.88"])
    ws_hidden.append(["本机证书路径", "/Users/chenmin/Secrets/prod_cert.pem"])

    wb.save(out_path)
    wb.close()


def create_pptx(out_path: str):
    prs = pptx.Presentation()
    prs.core_properties.author = "王磊"
    prs.core_properties.title = "杭州星澜智能研究院项目方案"

    slide1 = prs.slides.add_slide(prs.slide_layouts[0])
    slide1.shapes.title.text = "云栖智算平台交付方案"
    sub = slide1.placeholders[1].text_frame
    p = sub.paragraphs[0]
    r1 = p.add_run()
    r1.text = "编制单位：杭州星澜智能研究院  联系人：周"
    r2 = p.add_run()
    r2.text = "杰  手机：13711112222"

    slide2 = prs.slides.add_slide(prs.slide_layouts[5])
    slide2.shapes.title.text = "运维与接口联系人"
    tbl_shape = slide2.shapes.add_table(3, 4, Inches(0.8), Inches(1.8), Inches(8.4), Inches(2.4))
    tbl = tbl_shape.table
    for idx, h in enumerate(["负责人", "邮箱", "预算", "服务器IP"]):
        tbl.cell(0, idx).text = h
    tbl.cell(1, 0).text = "周杰"
    tbl.cell(1, 1).text = "zhoujie@xinglan-ai.cn"
    tbl.cell(1, 2).text = "¥850,000.00"
    tbl.cell(1, 3).text = "10.88.12.34"

    tbl.cell(2, 0).text = "陈敏"
    tbl.cell(2, 1).text = "chenmin@yunshu-cloud.cn"
    tbl.cell(2, 2).text = "¥420,000.00"
    tbl.cell(2, 3).text = "172.16.8.99"

    notes = slide1.notes_slide.notes_text_frame
    notes.text = "演讲备注：演示环境 Token 为 ghp_1234567890abcdef1234567890abcdef1234，请勿外泄；对接人周杰。"

    prs.save(out_path)

    # 注入 PPT 批注与作者部件，测试干净清理
    order, entries = ox.read_zip_entries(out_path)
    entries["ppt/commentAuthors.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:cmAuthorLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cmAuthor id="0" name="王磊" initials="WL" lastIdx="1" clrIdx="0"/>'
        '</p:cmAuthorLst>'
    ).encode("utf-8")
    entries["ppt/comments/comment1.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<p:cmLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        '<p:cm authorId="0" dt="2026-11-18T10:00:00.000" idx="1">'
        '<p:pos x="100" y="100"/><p:text>内部批注：周杰要求保密预算金额</p:text>'
        '</p:cm></p:cmLst>'
    ).encode("utf-8")
    order.extend(["ppt/commentAuthors.xml", "ppt/comments/comment1.xml"])
    ox.write_zip_entries(out_path, order, entries)


def create_pdf(out_path: str):
    doc = pymupdf.open()
    fontname, fontfile = pick_cjk_font()
    page1 = doc.new_page()
    if fontfile:
        page1.insert_font(fontname=fontname, fontfile=fontfile)

    lines = [
        "技术架构与合同摘要（测试样例）",
        "建设单位：北京云枢科技有限公司",
        f"统一社会信用代码：{SAMPLE_USCC1}",
        f"项目负责人：陈敏    身份证：{SAMPLE_ID1}",
        "联系电话：13666667777    邮箱：ops@yunshu-cloud.cn",
        "办公地址：上海市浦东新区张江路88号",
        "合同金额：¥560,000.00",
        "生产密钥：sk-proj-PdfSecretToken9876543210abcd",
        "数据库：mysql://root:DbPass123@10.0.1.50:3306/app",
        "内网后台：http://192.168.100.10:8080/admin",
        "合规声明：严格遵循中华人民共和国网络安全法及国家标准。",
    ]
    y = 72
    for idx, line in enumerate(lines):
        fs = 15 if idx == 0 else 11
        page1.insert_text((56, y), line, fontname=fontname, fontsize=fs, color=(0.1, 0.1, 0.1))
        y += 28 if idx == 0 else 24

    # 批注与超链接
    page1.add_text_annot((460, 180), "批注：请陈敏核对北京云枢科技有限公司账号")
    page1.insert_link(
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(180, 175, 340, 195),
            "uri": "mailto:ops@yunshu-cloud.cn",
        }
    )

    # 第 2 页：纯图片扫描页（无文本层）
    img = Image.new("RGB", (600, 400), (245, 245, 240))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 560, 360], outline=(80, 80, 80), width=3)
    draw.text((80, 180), "Scanned Image Page Placeholder", fill=(60, 60, 60))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    page2 = doc.new_page()
    page2.insert_image(pymupdf.Rect(50, 50, 550, 380), stream=buf.getvalue())

    doc.set_metadata({"author": "陈敏", "title": "北京云枢科技有限公司架构摘要", "creator": "TextVeil Fixture"})
    doc.set_toc([[1, "1. 北京云枢科技有限公司概况", 1]])
    doc.save(out_path, deflate=True)
    doc.close()


def create_md(out_path: str):
    content = f"""---
title: 云栖系统运维手册
author: 周杰
email: zhoujie@yunshu-cloud.cn
company: 北京云枢科技有限公司
---

# 系统运维手册（测试样例）

本系统由北京云枢科技有限公司（统一社会信用代码：{SAMPLE_USCC1}）承建，办公地址位于北京市海淀区中关村南大街甲18号院2号楼。
紧急联系人：周杰，手机：13711112222，固定电话：010-88886666。

## 值班人员表

| 负责人 | 手机 | 邮箱 | 服务器IP |
| --- | --- | --- | --- |
| 周杰 | 13711112222 | zhoujie@yunshu-cloud.cn | 10.88.12.34 |
| 张伟 | 13812345678 | zhangwei@yunshu-cloud.cn | 192.168.10.88 |

## 环境配置示例

```bash
export OPENAI_API_KEY=sk-proj-MdCodeBlockSecret1234567890
export ALIYUN_AK=LTAI5tSecretKey123456
export DB_URL=redis://:RedisPwd99@10.10.20.30:6379/0
export LOCAL_KEY=/Users/zhoujie/.ssh/id_rsa
export JWT_DEMO=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ6aG91amllIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c
```

## 非敏感技术说明

系统版本 v1.2.3.4 遵循中华人民共和国国家标准规范，本地回环监听地址为 `127.0.0.1` (`localhost`)。
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)


def make_all(target_dir: str) -> dict:
    os.makedirs(target_dir, exist_ok=True)
    paths = {
        "docx": os.path.join(target_dir, "样例_商业合作协议.docx"),
        "xlsx": os.path.join(target_dir, "样例_员工与项目台账.xlsx"),
        "pptx": os.path.join(target_dir, "样例_项目汇报方案.pptx"),
        "pdf": os.path.join(target_dir, "样例_技术架构与合同摘要.pdf"),
        "md": os.path.join(target_dir, "样例_系统运维手册.md"),
    }
    create_docx(paths["docx"])
    create_xlsx(paths["xlsx"])
    create_pptx(paths["pptx"])
    if pymupdf is not None:
        create_pdf(paths["pdf"])
    else:
        paths.pop("pdf")
    create_md(paths["md"])
    return paths


if __name__ == "__main__":
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT_DIR, "样例文档")
    res = make_all(out_dir)
    for k, p in res.items():
        print(f"生成 {k}: {p}")
