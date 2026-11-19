"""PowerPoint (.pptx) 扫描、脱敏、还原与校验处理器。"""

import re
import pptx
from ..detectors import Detector, Findings, name_like
from ..masking import active_replace_map, mapping_regex
from . import ooxml_utils as ox

_PPT_TEXT_PARTS_RE = re.compile(
    r"^ppt/(?:slides/slide\d+|notesSlides/notesSlide\d+|"
    r"slideMasters/slideMaster\d+|slideLayouts/slideLayout\d+|"
    r"diagrams/data\d+|charts/chart\d+|comments/comment\d+)\.xml$"
)
_PPT_COMMENT_PARTS_RE = re.compile(r"^ppt/(?:comments/comment\d+|commentAuthors)\.xml$")


def _ppt_table_rows_text(tbl_elem) -> list[list[str]]:
    rows = []
    for tr in tbl_elem.findall(f"./{ox.A_TR}"):
        row_cells = []
        for tc in tr.findall(f"./{ox.A_TC}"):
            parts = []
            for p in tc.iter(ox.A_P):
                t_elems = ox.collect_paragraph_t_elements(p, ox.A_P, ox.A_T)
                txt = "".join((el.text or "") for el in t_elems)
                if txt.strip():
                    parts.append(txt.strip())
            row_cells.append("\n".join(parts))
        if any(row_cells):
            rows.append(row_cells)
    return rows


def _scan_ppt_table(rows: list[list[str]], det: Detector, findings: Findings, fname: str):
    if not rows:
        return
    headers = rows[0] if len(rows) >= 2 else []
    for r_idx, row in enumerate(rows):
        for c_idx, cell in enumerate(row):
            if not cell.strip():
                continue
            if headers and r_idx > 0 and c_idx < len(headers):
                for term, cat, rule, crep in det.detect_table_cell(headers[c_idx], cell):
                    findings.add(term, cat, rule, fname, sample=cell, custom_replace=crep)
            if c_idx > 0 and len(row[c_idx - 1].strip()) <= 16:
                for term, cat, rule, crep in det.detect_table_cell(row[c_idx - 1], cell):
                    findings.add(term, cat, rule, fname, sample=cell, custom_replace=crep)


def scan_file(path: str, det: Detector, findings: Findings, fname: str) -> dict:
    _, entries = ox.read_zip_entries(path)
    opts = det.cfg.get("options") or {}
    prop_info = ox.inspect_ooxml_docprops(entries)

    comment_count = 0
    hidden_slide_count = 0
    notes_slide_count = 0
    all_texts = []

    for name, data in sorted(entries.items()):
        if name == "ppt/commentAuthors.xml":
            try:
                root = ox.parse_xml(data)
                for author_el in root:
                    nm = (author_el.get("name") or "").strip()
                    if nm and det.allowed(nm) and name_like(nm):
                        findings.add(nm, "person", "PPT 批注作者", fname, sample=nm)
            except Exception:
                pass
            continue

        if not _PPT_TEXT_PARTS_RE.match(name):
            continue

        is_notes = name.startswith("ppt/notesSlides/")
        is_comment = name.startswith("ppt/comments/")
        if is_notes:
            notes_slide_count += 1

        try:
            root = ox.parse_xml(data)
        except Exception:
            continue

        if name.startswith("ppt/slides/slide") and root.get("show") == "0":
            hidden_slide_count += 1

        if is_comment:
            comment_count += sum(1 for el in root if el.tag.endswith("}cm"))
            for el in root.iter():
                if el.tag.endswith("}text") and el.text and el.text.strip():
                    for term, cat, rule, crep in det.detect_text(el.text):
                        findings.add(term, cat, "PPT 批注内容", fname, sample=el.text, custom_replace=crep)

        for a_text in ox.extract_paragraph_texts(data, ox.A_P, ox.A_T):
            all_texts.append(a_text)
            loc_rule = "演讲者备注" if is_notes else "幻灯片文本"
            for term, cat, rule, crep in det.detect_text(a_text):
                findings.add(term, cat, rule if rule != "行内标签" else f"{loc_rule}({rule})", fname, sample=a_text, custom_replace=crep)

        for tbl in root.iter(ox.A_TBL):
            _scan_ppt_table(_ppt_table_rows_text(tbl), det, findings, fname)

    ext_rels = ox.inspect_external_rels(entries)
    for _, tgt in ext_rels:
        clean_tgt = tgt[7:] if tgt.lower().startswith("mailto:") else tgt
        for term, cat, rule, crep in det.detect_text(clean_tgt):
            findings.add(term, cat, "超链接目标", fname, sample=tgt, custom_replace=crep)

    if opts.get("detect_author_in_body", True) and prop_info["authors"]:
        joined = "\n".join(all_texts)
        for author in prop_info["authors"]:
            if author in joined and det.allowed(author) and name_like(author):
                findings.add(author, "person", "文档属性作者", fname, sample=author)

    notes = []
    if hidden_slide_count:
        notes.append(f"包含 {hidden_slide_count} 张隐藏幻灯片（已一并扫描脱敏）")
    if notes_slide_count:
        notes.append(f"已扫描 {notes_slide_count} 页演讲者备注")

    return {
        "format": "PPT",
        "meta_count": prop_info["meta_count"],
        "comment_count": comment_count,
        "revision_count": 0,
        "hyperlink_count": len(ext_rels),
        "thumbnail_count": 1 if prop_info["has_thumbnail"] else 0,
        "hidden_sheet_count": 0,
        "notes": notes,
    }


def _transform_ppt(
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

    if not restore_mode and opts.get("clean_comments", True):
        for name in list(entries.keys()):
            if _PPT_COMMENT_PARTS_RE.match(name):
                if ox.remove_ooxml_part(order, entries, name):
                    if "PPT 批注与作者" not in removed:
                        removed.append("PPT 批注与作者记录")

    for name in list(entries.keys()):
        if not _PPT_TEXT_PARTS_RE.match(name):
            continue
        data = entries[name]
        data, ch = ox.replace_in_xml_paragraphs(data, ox.A_P, ox.A_T, regex, rep_map, loc_prefix=name)
        if ch:
            changes.extend(ch)
            entries[name] = data

    if not restore_mode:
        changes.extend(ox.scrub_external_rels(entries, regex, rep_map, cfg))
        removed.extend(ox.scrub_ooxml_docprops(order, entries, cfg))

    ox.write_zip_entries(out_path, order, entries)
    return {"changes": changes, "removed": removed, "notes": []}


def apply_file(path: str, out_path: str, mapping: dict, cfg: dict) -> dict:
    regex = mapping_regex(mapping, only_enabled=True)
    rep_map = active_replace_map(mapping)
    return _transform_ppt(path, out_path, regex, rep_map, cfg, restore_mode=False)


def restore_file(path: str, out_path: str, inv_regex, inv_map: dict, cfg: dict) -> dict:
    return _transform_ppt(path, out_path, inv_regex, inv_map, cfg, restore_mode=True)


def verify_file(src_path: str, out_path: str, check_terms: list[str]) -> dict:
    try:
        prs_src = pptx.Presentation(src_path)
        src_slides = len(prs_src.slides)
        prs_out = pptx.Presentation(out_path)
        out_slides = len(prs_out.slides)
    except Exception as e:
        return {"structure_ok": False, "structure_msg": f"PPTX 结构打开失败：{e}", "residual": []}

    _, out_entries = ox.read_zip_entries(out_path)
    full_text = ox.collect_all_xml_text(out_entries, include_rels=True)
    residual = [t for t in check_terms if t and t in full_text]
    return {
        "structure_ok": src_slides == out_slides,
        "structure_msg": f"幻灯片结构完整（{out_slides} / {src_slides} 页）",
        "residual": residual,
    }
