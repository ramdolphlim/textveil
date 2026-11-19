"""Word (.docx) 扫描、脱敏、还原与校验处理器。"""

import re
from lxml import etree
from ..detectors import Detector, Findings, name_like
from ..masking import active_replace_map, mapping_regex
from . import ooxml_utils as ox

_WORD_TEXT_PARTS_RE = re.compile(
    r"^word/(?:document|header\d+|footer\d+|footnotes|endnotes|comments|"
    r"diagrams/data\d+|charts/chart\d+)\.xml$"
)


def _table_rows_text(tbl_elem) -> list[list[str]]:
    rows = []
    for tr in tbl_elem.findall(f"./{ox.W_TR}"):
        row_cells = []
        for tc in tr.findall(f"./{ox.W_TC}"):
            parts = []
            for p in tc.findall(f"./{ox.W_P}"):
                t_elems = ox.collect_paragraph_t_elements(p, ox.W_P, ox.W_T)
                txt = "".join((el.text or "") for el in t_elems)
                if txt.strip():
                    parts.append(txt.strip())
            row_cells.append("\n".join(parts))
        if any(row_cells):
            rows.append(row_cells)
    return rows


def _scan_table(rows: list[list[str]], det: Detector, findings: Findings, fname: str):
    if not rows:
        return
    headers = rows[0] if len(rows) >= 2 else []
    for r_idx, row in enumerate(rows):
        for c_idx, cell in enumerate(row):
            if not cell.strip():
                continue
            # 1) 按首行表头匹配
            if headers and r_idx > 0 and c_idx < len(headers):
                for term, cat, rule, crep in det.detect_table_cell(headers[c_idx], cell):
                    findings.add(term, cat, rule, fname, sample=cell, custom_replace=crep)
            # 2) 按左侧相邻标签单元格匹配（键值对表格常见，如 | 联系人 | 张伟 |）
            if c_idx > 0 and len(row[c_idx - 1].strip()) <= 16:
                for term, cat, rule, crep in det.detect_table_cell(row[c_idx - 1], cell):
                    findings.add(term, cat, rule, fname, sample=cell, custom_replace=crep)


def _strip_word_revisions(root) -> int:
    """接受插入 (<w:ins> 解包) 并彻底移除删除 (<w:del>) 与修订作者属性。"""
    removed = 0
    # 1. 删除 <w:del>（含被删除原文 <w:delText>）
    for del_el in list(root.iter(ox.W_DEL)):
        parent = del_el.getparent()
        if parent is not None:
            parent.remove(del_el)
            removed += 1
    # 2. 解包 <w:ins>，保留内部正文但移除作者与日期标签
    for ins_el in list(root.iter(ox.W_INS)):
        parent = ins_el.getparent()
        if parent is not None:
            idx = list(parent).index(ins_el)
            for child in list(ins_el):
                parent.insert(idx, child)
                idx += 1
            parent.remove(ins_el)
            removed += 1
    # 3. 清理残留的修订作者/时间属性（如 rPrChange / pPrChange / tblPrChange 等）
    author_attr = f"{{{ox.NS_W}}}author"
    date_attr = f"{{{ox.NS_W}}}date"
    for el in root.iter():
        if author_attr in el.attrib:
            del el.attrib[author_attr]
            removed += 1
        if date_attr in el.attrib:
            del el.attrib[date_attr]
    return removed


def _strip_word_comment_anchors(root) -> int:
    removed = 0
    for tag in (ox.W_COMMENT_RANGE_START, ox.W_COMMENT_RANGE_END, ox.W_COMMENT_REF):
        for el in list(root.iter(tag)):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)
                removed += 1
    return removed


def scan_file(path: str, det: Detector, findings: Findings, fname: str) -> dict:
    _, entries = ox.read_zip_entries(path)
    opts = det.cfg.get("options") or {}

    prop_info = ox.inspect_ooxml_docprops(entries)
    comment_count = 0
    revision_count = 0
    hyperlink_count = 0

    all_body_texts = []
    for name, data in sorted(entries.items()):
        if not _WORD_TEXT_PARTS_RE.match(name):
            continue
        is_comment = name.startswith("word/comments")
        try:
            root = ox.parse_xml(data)
        except Exception:
            continue

        if is_comment:
            comment_count += sum(1 for _ in root.iter(f"{{{ox.NS_W}}}comment"))

        revision_count += sum(1 for _ in root.iter(ox.W_DEL)) + sum(1 for _ in root.iter(ox.W_INS))

        # 普通段落 (<w:p>)
        for p_text in ox.extract_paragraph_texts(data, ox.W_P, ox.W_T):
            all_body_texts.append(p_text)
            for term, cat, rule, crep in det.detect_text(p_text):
                findings.add(term, cat, rule, fname, sample=p_text, custom_replace=crep)

        # DrawingML 形状 / SmartArt / 图表文字 (<a:p>)
        for a_text in ox.extract_paragraph_texts(data, ox.A_P, ox.A_T):
            all_body_texts.append(a_text)
            for term, cat, rule, crep in det.detect_text(a_text):
                findings.add(term, cat, rule, fname, sample=a_text, custom_replace=crep)

        # 修订删除原文 (<w:delText>)：即使隐藏也扫出提示用户
        for dt in root.iter(ox.W_DELTEXT):
            if dt.text and dt.text.strip():
                for term, cat, rule, crep in det.detect_text(dt.text):
                    findings.add(term, cat, "修订删除留痕", fname, sample=dt.text, custom_replace=crep)

        # 表格上下文扫描
        for tbl in root.iter(ox.W_TBL):
            _scan_table(_table_rows_text(tbl), det, findings, fname)

    # 外部超链接扫描
    ext_rels = ox.inspect_external_rels(entries)
    hyperlink_count = len(ext_rels)
    for rel_name, tgt in ext_rels:
        clean_tgt = tgt[7:] if tgt.lower().startswith("mailto:") else tgt
        for term, cat, rule, crep in det.detect_text(clean_tgt):
            findings.add(term, cat, "超链接目标", fname, sample=tgt, custom_replace=crep)

    # 文档属性作者出现在正文中时自动补检
    if opts.get("detect_author_in_body", True) and prop_info["authors"]:
        joined = "\n".join(all_body_texts)
        for author in prop_info["authors"]:
            if author in joined and det.allowed(author) and name_like(author):
                findings.add(author, "person", "文档属性作者", fname, sample=author)

    return {
        "format": "Word",
        "meta_count": prop_info["meta_count"],
        "comment_count": comment_count,
        "revision_count": revision_count,
        "hyperlink_count": hyperlink_count,
        "thumbnail_count": 1 if prop_info["has_thumbnail"] else 0,
        "hidden_sheet_count": 0,
        "notes": [],
    }


def _transform_word(
    path: str,
    out_path: str,
    regex,
    rep_map: dict,
    cfg: dict,
    restore_mode: bool = False,
) -> dict:
    order, entries = ox.read_zip_entries(path)
    opts = cfg.get("options") or {}
    changes: list[dict] = []
    removed: list[str] = []

    if not restore_mode:
        if opts.get("clean_comments", True):
            for cpart in ("word/comments.xml", "word/commentsExtended.xml", "word/commentsIds.xml", "word/commentsExtensible.xml"):
                if ox.remove_ooxml_part(order, entries, cpart):
                    removed.append(f"Word 批注 ({cpart})")

    for name in list(entries.keys()):
        if not _WORD_TEXT_PARTS_RE.match(name):
            continue
        data = entries[name]

        if not restore_mode:
            try:
                root = ox.parse_xml(data)
                xml_dirty = False
                if opts.get("clean_revisions", True):
                    if _strip_word_revisions(root) > 0:
                        xml_dirty = True
                        if "Word 修订记录" not in removed:
                            removed.append("Word 修订记录（<w:del>/<w:ins> 与修改人）")
                if opts.get("clean_comments", True):
                    if _strip_word_comment_anchors(root) > 0:
                        xml_dirty = True
                if xml_dirty:
                    data = ox.serialize_xml(root)
            except Exception:
                pass

        data, ch1 = ox.replace_in_xml_paragraphs(data, ox.W_P, ox.W_T, regex, rep_map, loc_prefix=name)
        data, ch2 = ox.replace_in_xml_paragraphs(data, ox.A_P, ox.A_T, regex, rep_map, loc_prefix=f"{name}(图形)")
        changes.extend(ch1)
        changes.extend(ch2)
        entries[name] = data

    if not restore_mode:
        changes.extend(ox.scrub_external_rels(entries, regex, rep_map, cfg))
        removed.extend(ox.scrub_ooxml_docprops(order, entries, cfg))

    ox.write_zip_entries(out_path, order, entries)
    return {
        "changes": changes,
        "removed": removed,
        "notes": [],
    }


def apply_file(path: str, out_path: str, mapping: dict, cfg: dict) -> dict:
    regex = mapping_regex(mapping, only_enabled=True)
    rep_map = active_replace_map(mapping)
    return _transform_word(path, out_path, regex, rep_map, cfg, restore_mode=False)


def restore_file(path: str, out_path: str, inv_regex, inv_map: dict, cfg: dict) -> dict:
    return _transform_word(path, out_path, inv_regex, inv_map, cfg, restore_mode=True)


def verify_file(src_path: str, out_path: str, check_terms: list[str]) -> dict:
    try:
        _, src_entries = ox.read_zip_entries(src_path)
        _, out_entries = ox.read_zip_entries(out_path)
    except Exception as e:
        return {"structure_ok": False, "structure_msg": f"无法打开输出 DOCX：{e}", "residual": []}

    # 检查输出 ZIP 内所有 XML 皆可被正确解析，且段落/表格结构未损坏
    src_paras = 0
    out_paras = 0
    try:
        if "word/document.xml" in src_entries:
            src_root = ox.parse_xml(src_entries["word/document.xml"])
            src_paras = sum(1 for _ in src_root.iter(ox.W_P))
        if "word/document.xml" in out_entries:
            out_root = ox.parse_xml(out_entries["word/document.xml"])
            out_paras = sum(1 for _ in out_root.iter(ox.W_P))
        for name, data in out_entries.items():
            if name.endswith(".xml") or name.endswith(".rels"):
                ox.parse_xml(data)
    except Exception as e:
        return {"structure_ok": False, "structure_msg": f"XML 结构校验失败：{e}", "residual": []}

    try:
        import docx
        doc = docx.Document(out_path)
        _ = len(doc.paragraphs)
    except Exception as e:
        return {"structure_ok": False, "structure_msg": f"python-docx 打开验证失败：{e}", "residual": []}

    full_text = ox.collect_all_xml_text(out_entries, include_rels=True)
    residual = [t for t in check_terms if t and t in full_text]
    return {
        "structure_ok": True,
        "structure_msg": f"XML 结构完整（段落 {src_paras} → {out_paras}）",
        "residual": residual,
    }
