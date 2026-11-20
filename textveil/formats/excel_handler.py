"""Excel (.xlsx / .xlsm) 扫描、脱敏、还原与校验处理器。"""

import os
import re
import openpyxl
from openpyxl.comments import Comment
from ..detectors import Detector, Findings, classify_header, name_like
from ..masking import active_replace_map, mapping_regex, term_present
from . import ooxml_utils as ox

_EXCEL_XML_PARTS_RE = re.compile(r"^xl/(?:drawings/drawing\d+|charts/chart\d+)\.xml$")
_RE_FORMULA_STR = re.compile(r'"([^"]*)"')
_INVALID_SHEET_CHARS = re.compile(r"[\\/?*\[\]:]")


def _sub_text(text: str, regex, rep_map: dict) -> str:
    if not text or regex is None or not rep_map:
        return text
    return regex.sub(lambda m: rep_map.get(m.group(0), m.group(0)), text)


def _sub_formula_literals(formula: str, regex, rep_map: dict) -> str:
    if not formula or not formula.startswith("=") or regex is None or not rep_map:
        return formula

    def rep_quoted(m):
        inner = m.group(1)
        new_inner = _sub_text(inner, regex, rep_map)
        new_inner = new_inner.replace('"', '""')
        return f'"{new_inner}"'

    return _RE_FORMULA_STR.sub(rep_quoted, formula)


def _detect_header_row(ws) -> tuple[int, dict[int, str]]:
    """在前 3 个非空行中识别包含至少 1 个已知敏感列头的表头行。"""
    non_empty_seen = 0
    for r_idx in range(1, min(ws.max_row or 0, 15) + 1):
        row_vals = {}
        matched_cats = 0
        for c_idx in range(1, min(ws.max_column or 0, 50) + 1):
            v = ws.cell(r_idx, c_idx).value
            if isinstance(v, str) and v.strip():
                s = v.strip()
                row_vals[c_idx] = s
                if classify_header(s):
                    matched_cats += 1
        if row_vals:
            non_empty_seen += 1
            if matched_cats >= 1 and len(row_vals) >= 2:
                return r_idx, row_vals
            if non_empty_seen >= 3:
                break
    return 0, {}


def _iter_hf_texts(ws):
    for hf_name in ("oddHeader", "oddFooter", "evenHeader", "evenFooter", "firstHeader", "firstFooter"):
        hf = getattr(ws, hf_name, None)
        if not hf:
            continue
        for side in ("left", "center", "right"):
            part = getattr(hf, side, None)
            if part and part.text:
                yield part


def scan_file(path: str, det: Detector, findings: Findings, fname: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    wb = openpyxl.load_workbook(path, data_only=False, keep_vba=(ext == ".xlsm"))
    opts = det.cfg.get("options") or {}

    _, entries = ox.read_zip_entries(path)
    prop_info = ox.inspect_ooxml_docprops(entries)

    comment_count = 0
    hidden_sheet_count = 0
    hyperlink_count = 0
    all_texts = []

    try:
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                hidden_sheet_count += 1

            # 工作表名称
            for term, cat, rule, crep in det.detect_text(ws.title):
                findings.add(term, cat, "工作表名称", fname, sample=ws.title, custom_replace=crep)

            hdr_row, headers = _detect_header_row(ws)
            max_r = ws.max_row or 0
            max_c = ws.max_column or 0

            # 表格顶部标题（如合并单元格里的「XX项目工程量清单」）里的项目名称
            top = [ws.cell(r, c).value for r in range(1, min(max_r, 3) + 1) for c in range(1, min(max_c, 12) + 1)]
            top = [v for v in top if isinstance(v, str) and v.strip() and not v.startswith("=")]
            for term, cat, rule, crep in det.detect_cover_lines(top + [ws.title]):
                findings.add(term, cat, rule, fname, sample=term, custom_replace=crep)

            for r in range(1, max_r + 1):
                for c in range(1, max_c + 1):
                    cell = ws.cell(r, c)
                    val = cell.value

                    if isinstance(val, str) and val.strip():
                        if val.startswith("="):
                            for m in _RE_FORMULA_STR.finditer(val):
                                lit = m.group(1)
                                if lit.strip():
                                    all_texts.append(lit)
                                    for term, cat, rule, crep in det.detect_text(lit):
                                        findings.add(term, cat, "公式字符串", fname, sample=val[:60], custom_replace=crep)
                        else:
                            all_texts.append(val)
                            # 列头上下文 + 左侧标签上下文（仅在非表头行应用）
                            is_header_row = (hdr_row and r == hdr_row)
                            col_hdr = headers.get(c, "") if (hdr_row and r > hdr_row) else ""
                            left_hdr = ""
                            if not is_header_row and not col_hdr and c > 1:
                                lv = ws.cell(r, c - 1).value
                                if isinstance(lv, str) and len(lv.strip()) <= 16:
                                    left_hdr = lv.strip()

                            matched = []
                            if col_hdr:
                                matched.extend(det.detect_table_cell(col_hdr, val))
                            elif left_hdr:
                                matched.extend(det.detect_kv_cell(left_hdr, val) or det.detect_text(val))
                            else:
                                matched.extend(det.detect_text(val))

                            for term, cat, rule, crep in matched:
                                findings.add(term, cat, rule, fname, sample=val, custom_replace=crep)

                    if cell.comment and cell.comment.text:
                        comment_count += 1
                        ctext = cell.comment.text
                        for term, cat, rule, crep in det.detect_text(ctext):
                            findings.add(term, cat, "单元格批注", fname, sample=ctext, custom_replace=crep)

                    if cell.hyperlink:
                        hyperlink_count += 1
                        for h_val in (cell.hyperlink.target or "", cell.hyperlink.tooltip or ""):
                            clean_h = h_val[7:] if h_val.lower().startswith("mailto:") else h_val
                            if clean_h:
                                for term, cat, rule, crep in det.detect_text(clean_h):
                                    findings.add(term, cat, "单元格超链接", fname, sample=h_val, custom_replace=crep)

            for part in _iter_hf_texts(ws):
                for term, cat, rule, crep in det.detect_text(part.text):
                    findings.add(term, cat, "页眉页脚", fname, sample=part.text, custom_replace=crep)
    finally:
        wb.close()

    # 图形与图表 XML（DrawingML）
    for name, data in sorted(entries.items()):
        if not _EXCEL_XML_PARTS_RE.match(name):
            continue
        for a_text in ox.extract_paragraph_texts(data, ox.A_P, ox.A_T):
            all_texts.append(a_text)
            for term, cat, rule, crep in det.detect_text(a_text):
                findings.add(term, cat, "表格图形/图表", fname, sample=a_text, custom_replace=crep)

    if opts.get("detect_author_in_body", True) and prop_info["authors"]:
        joined = "\n".join(all_texts)
        for author in prop_info["authors"]:
            if author in joined and det.allowed(author) and name_like(author):
                findings.add(author, "person", "文档属性作者", fname, sample=author)

    return {
        "format": "Excel",
        "meta_count": prop_info["meta_count"],
        "comment_count": comment_count,
        "revision_count": 0,
        "hyperlink_count": hyperlink_count,
        "thumbnail_count": 1 if prop_info["has_thumbnail"] else 0,
        "hidden_sheet_count": hidden_sheet_count,
        "notes": [f"包含 {hidden_sheet_count} 个隐藏工作表"] if hidden_sheet_count else [],
    }


def _sanitize_sheet_title(title: str, existing: set[str]) -> str:
    clean = _INVALID_SHEET_CHARS.sub("_", title).strip("'") or "Sheet"
    clean = clean[:31]
    base = clean
    idx = 2
    while clean in existing:
        suf = f"_{idx}"
        clean = base[: 31 - len(suf)] + suf
        idx += 1
    return clean


def _transform_excel(
    path: str,
    out_path: str,
    regex,
    rep_map: dict,
    cfg: dict,
    restore_mode: bool = False,
) -> dict:
    ext = os.path.splitext(path)[1].lower()
    wb = openpyxl.load_workbook(path, data_only=False, keep_vba=(ext == ".xlsm"))
    opts = cfg.get("options") or {}
    changes: list[dict] = []
    removed: list[str] = []
    notes: list[str] = []

    try:
        # 1. 可选删除隐藏工作表（仅脱敏模式且至少保留 1 个可见表）
        if not restore_mode and opts.get("clean_hidden_sheets", False):
            visible_sheets = [ws for ws in wb.worksheets if ws.sheet_state == "visible"]
            if visible_sheets:
                for ws in list(wb.worksheets):
                    if ws.sheet_state != "visible":
                        title = ws.title
                        wb.remove(ws)
                        removed.append(f"隐藏工作表「{title}」")
            else:
                notes.append("所有工作表均处于隐藏状态，保留并脱敏内容以避免空工作簿")

        # 2. 重命名含敏感词的工作表并更新跨表公式引用
        title_renames: dict[str, str] = {}
        existing_titles = {ws.title for ws in wb.worksheets}
        for ws in wb.worksheets:
            new_raw = _sub_text(ws.title, regex, rep_map)
            if new_raw != ws.title:
                existing_titles.discard(ws.title)
                safe_title = _sanitize_sheet_title(new_raw, existing_titles)
                existing_titles.add(safe_title)
                title_renames[ws.title] = safe_title
                changes.append({"location": f"Sheet:{ws.title}", "orig": ws.title, "new": safe_title})
                ws.title = safe_title

        # 3. 逐工作表替换单元格、公式字符串、批注、超链接、页眉页脚
        for ws in wb.worksheets:
            max_r = ws.max_row or 0
            max_c = ws.max_column or 0
            for r in range(1, max_r + 1):
                for c in range(1, max_c + 1):
                    cell = ws.cell(r, c)
                    val = cell.value

                    if isinstance(val, str) and val:
                        if val.startswith("="):
                            new_val = val
                            for old_t, new_t in title_renames.items():
                                new_val = re.sub(
                                    rf"(?:'{re.escape(old_t)}'|{re.escape(old_t)})!",
                                    f"'{new_t}'!",
                                    new_val,
                                )
                            new_val = _sub_formula_literals(new_val, regex, rep_map)
                            if new_val != val:
                                cell.value = new_val
                                changes.append({"location": f"{ws.title}!{cell.coordinate}", "orig": val, "new": new_val})
                        else:
                            new_val = _sub_text(val, regex, rep_map)
                            if new_val != val:
                                cell.value = new_val
                                changes.append({"location": f"{ws.title}!{cell.coordinate}", "orig": val, "new": new_val})

                    if cell.comment:
                        if not restore_mode and opts.get("clean_comments", True):
                            cell.comment = None
                            if "Excel 单元格批注" not in removed:
                                removed.append("Excel 单元格批注")
                        else:
                            orig_ct = cell.comment.text or ""
                            new_ct = _sub_text(orig_ct, regex, rep_map)
                            if new_ct != orig_ct:
                                cell.comment = Comment(new_ct, "")
                                changes.append({"location": f"{ws.title}!{cell.coordinate}(批注)", "orig": orig_ct, "new": new_ct})

                    if cell.hyperlink and (restore_mode or opts.get("clean_hyperlinks", True)):
                        tgt = cell.hyperlink.target or ""
                        new_tgt = _sub_text(tgt, regex, rep_map)
                        if not restore_mode and new_tgt == tgt and tgt.lower().startswith("mailto:"):
                            new_tgt = "mailto:[已脱敏邮箱]"
                        if new_tgt != tgt:
                            cell.hyperlink.target = new_tgt
                            changes.append({"location": f"{ws.title}!{cell.coordinate}(超链接)", "orig": tgt, "new": new_tgt})
                        if cell.hyperlink.tooltip:
                            new_tip = _sub_text(cell.hyperlink.tooltip, regex, rep_map)
                            if new_tip != cell.hyperlink.tooltip:
                                cell.hyperlink.tooltip = new_tip

            for part in _iter_hf_texts(ws):
                new_hf = _sub_text(part.text, regex, rep_map)
                if new_hf != part.text:
                    changes.append({"location": f"{ws.title}(页眉页脚)", "orig": part.text, "new": new_hf})
                    part.text = new_hf

        if not restore_mode and opts.get("clean_metadata", True):
            p = wb.properties
            for attr in ("creator", "lastModifiedBy", "title", "subject", "keywords", "description", "category"):
                if getattr(p, attr, None):
                    setattr(p, attr, None)

        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        wb.save(out_path)
    finally:
        wb.close()

    # 4. 二次 ZIP/XML 处理：脱敏图形/图表内部文本 + 彻底清理 docProps/app.xml、custom.xml、缩略图
    order, entries = ox.read_zip_entries(out_path)
    xml_changed = False
    for name in list(entries.keys()):
        if _EXCEL_XML_PARTS_RE.match(name):
            new_xml, ch = ox.replace_in_xml_paragraphs(entries[name], ox.A_P, ox.A_T, regex, rep_map, loc_prefix=name)
            if ch:
                entries[name] = new_xml
                changes.extend(ch)
                xml_changed = True

    if not restore_mode:
        rel_ch = ox.scrub_external_rels(entries, regex, rep_map, cfg)
        if rel_ch:
            changes.extend(rel_ch)
            xml_changed = True
        doc_rem = ox.scrub_ooxml_docprops(order, entries, cfg)
        if doc_rem:
            removed.extend(doc_rem)
            xml_changed = True

    if xml_changed:
        ox.write_zip_entries(out_path, order, entries)

    return {"changes": changes, "removed": removed, "notes": notes}


def apply_file(path: str, out_path: str, mapping: dict, cfg: dict) -> dict:
    regex = mapping_regex(mapping, only_enabled=True)
    rep_map = active_replace_map(mapping)
    return _transform_excel(path, out_path, regex, rep_map, cfg, restore_mode=False)


def restore_file(path: str, out_path: str, inv_regex, inv_map: dict, cfg: dict) -> dict:
    return _transform_excel(path, out_path, inv_regex, inv_map, cfg, restore_mode=True)


def verify_file(src_path: str, out_path: str, check_terms: list[str]) -> dict:
    ext = os.path.splitext(out_path)[1].lower()
    try:
        wb_src = openpyxl.load_workbook(src_path, read_only=True, data_only=False)
        src_vis = sum(1 for ws in wb_src.worksheets if ws.sheet_state == "visible")
        wb_src.close()

        wb_out = openpyxl.load_workbook(out_path, data_only=False, keep_vba=(ext == ".xlsm"))
        out_vis = sum(1 for ws in wb_out.worksheets if ws.sheet_state == "visible")
        out_total = len(wb_out.worksheets)
        wb_out.close()
    except Exception as e:
        return {"structure_ok": False, "structure_msg": f"Excel 打开校验失败：{e}", "residual": []}

    _, out_entries = ox.read_zip_entries(out_path)
    full_text = ox.collect_all_xml_text(out_entries, include_rels=True)
    residual = [t for t in check_terms if term_present(t, full_text)]
    return {
        "structure_ok": True,
        "structure_msg": f"工作簿结构完整（可见表 {src_vis} → {out_vis}，总计 {out_total}）",
        "residual": residual,
    }
