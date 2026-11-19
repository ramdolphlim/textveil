"""OOXML（DOCX / XLSX / PPTX）共享 XML 解析、跨 Run 替换、部件移除与元数据清理工具。"""

import os
import posixpath
import re
import zipfile
from lxml import etree

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_CP = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_DCTERMS = "http://purl.org/dc/terms/"
NS_APP = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
NS_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"

W_P = f"{{{NS_W}}}p"
W_T = f"{{{NS_W}}}t"
W_TBL = f"{{{NS_W}}}tbl"
W_TR = f"{{{NS_W}}}tr"
W_TC = f"{{{NS_W}}}tc"
W_INS = f"{{{NS_W}}}ins"
W_DEL = f"{{{NS_W}}}del"
W_DELTEXT = f"{{{NS_W}}}delText"
W_TXBX = f"{{{NS_W}}}txbxContent"
W_COMMENT_RANGE_START = f"{{{NS_W}}}commentRangeStart"
W_COMMENT_RANGE_END = f"{{{NS_W}}}commentRangeEnd"
W_COMMENT_REF = f"{{{NS_W}}}commentReference"

A_P = f"{{{NS_A}}}p"
A_T = f"{{{NS_A}}}t"
A_TBL = f"{{{NS_A}}}tbl"
A_TR = f"{{{NS_A}}}tr"
A_TC = f"{{{NS_A}}}tc"

_CORE_SCRUB_TAGS = {
    f"{{{NS_DC}}}creator",
    f"{{{NS_CP}}}lastModifiedBy",
    f"{{{NS_DC}}}title",
    f"{{{NS_DC}}}subject",
    f"{{{NS_CP}}}keywords",
    f"{{{NS_DC}}}description",
    f"{{{NS_CP}}}category",
    f"{{{NS_CP}}}lastPrinted",
    f"{{{NS_CP}}}contentStatus",
}
_APP_SCRUB_TAGS = {
    f"{{{NS_APP}}}Company",
    f"{{{NS_APP}}}Manager",
    f"{{{NS_APP}}}HyperlinkBase",
}

_PARSER = etree.XMLParser(remove_blank_text=False, resolve_entities=False, huge_tree=True)


def read_zip_entries(path: str) -> tuple[list[str], dict[str, bytes]]:
    """读取 ZIP 内所有条目的顺序与字节内容。"""
    order: list[str] = []
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(path, "r") as zf:
        for info in zf.infolist():
            order.append(info.filename)
            entries[info.filename] = zf.read(info.filename)
    return order, entries


def write_zip_entries(out_path: str, order: list[str], entries: dict[str, bytes]) -> None:
    """将条目按原始顺序写回 ZIP（自动跳过已移除的条目并补齐新增条目）。"""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    written = set()
    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in order:
            if name in entries:
                zf.writestr(name, entries[name])
                written.add(name)
        for name, data in entries.items():
            if name not in written:
                zf.writestr(name, data)


def parse_xml(xml_bytes: bytes):
    return etree.fromstring(xml_bytes, parser=_PARSER)


def serialize_xml(root) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def collect_paragraph_t_elements(p_elem, p_tag: str, t_tag: str) -> list:
    """
    收集属于 p_elem 的所有文字节点 t_tag。
    遇到嵌套段落（如 Word 文本框 w:txbxContent 内的 w:p）立即停止深入，
    避免同一段文字被外层段落与内层段落重复处理或破坏。
    """
    out = []

    def walk(node):
        for child in node:
            tag = child.tag
            if tag == p_tag or tag == W_TXBX or tag == W_DEL:
                continue
            if tag == t_tag:
                out.append(child)
            else:
                walk(child)

    walk(p_elem)
    return out


def extract_paragraph_texts(xml_bytes: bytes, p_tag: str, t_tag: str) -> list[str]:
    """按段落拼接跨 Run 文本，用于精确扫描。"""
    try:
        root = parse_xml(xml_bytes)
    except Exception:
        return []
    texts = []
    for p in root.iter(p_tag):
        t_elems = collect_paragraph_t_elements(p, p_tag, t_tag)
        if not t_elems:
            continue
        s = "".join((el.text or "") for el in t_elems)
        if s.strip():
            texts.append(s)
    return texts


def replace_in_xml_paragraphs(
    xml_bytes: bytes,
    p_tag: str,
    t_tag: str,
    regex,
    rep_map: dict,
    loc_prefix: str = "",
) -> tuple[bytes, list[dict]]:
    """
    对 XML 中每个段落执行跨 Run 文本替换（从右向左），完整保留原有格式 (<rPr>)。
    """
    if regex is None or not rep_map:
        return xml_bytes, []
    try:
        root = parse_xml(xml_bytes)
    except Exception:
        return xml_bytes, []

    changed = False
    changes: list[dict] = []

    for p_idx, p in enumerate(root.iter(p_tag), 1):
        t_elems = collect_paragraph_t_elements(p, p_tag, t_tag)
        if not t_elems:
            continue

        # 建立字符偏移映射: (t_elem, start_pos, end_pos, text)
        runs = []
        pos = 0
        for el in t_elems:
            txt = el.text or ""
            runs.append([el, pos, pos + len(txt), txt])
            pos += len(txt)

        full_text = "".join(r[3] for r in runs)
        if not full_text:
            continue

        matches = list(regex.finditer(full_text))
        if not matches:
            continue

        # 从右向左替换，确保偏移量不会失效
        for m in reversed(matches):
            orig = m.group(0)
            rep = rep_map.get(orig)
            if rep is None or rep == orig:
                continue

            m_start, m_end = m.start(), m.end()
            inserted = False
            for r in runs:
                el, r_start, r_end, r_txt = r
                if r_end <= m_start or r_start >= m_end:
                    continue
                overlap_start = max(m_start, r_start) - r_start
                overlap_end = min(m_end, r_end) - r_start
                if not inserted:
                    new_txt = r_txt[:overlap_start] + rep + r_txt[overlap_end:]
                    inserted = True
                else:
                    new_txt = r_txt[:overlap_start] + r_txt[overlap_end:]
                r[3] = new_txt
                el.text = new_txt
                if new_txt != new_txt.strip():
                    el.set(XML_SPACE, "preserve")
                elif XML_SPACE in el.attrib and t_tag == W_T:
                    el.set(XML_SPACE, "preserve")

            changed = True
            changes.append(
                {
                    "location": f"{loc_prefix}#{p_idx}" if loc_prefix else f"P#{p_idx}",
                    "orig": orig,
                    "new": rep,
                }
            )

    if not changed:
        return xml_bytes, []
    return serialize_xml(root), changes


def _resolve_rel_target(rels_path: str, target: str) -> str:
    """将 .rels 文件内的相对 Target 解析为 ZIP 内规范路径。"""
    if not target or "://" in target or target.startswith("mailto:"):
        return ""
    # word/_rels/document.xml.rels -> base_dir = word
    # _rels/.rels -> base_dir = ""
    rels_dir = posixpath.dirname(rels_path)
    if posixpath.basename(rels_dir) == "_rels":
        base_dir = posixpath.dirname(rels_dir)
    else:
        base_dir = rels_dir
    if target.startswith("/"):
        return target.lstrip("/")
    joined = posixpath.join(base_dir, target) if base_dir else target
    return posixpath.normpath(joined)


def remove_ooxml_part(order: list[str], entries: dict[str, bytes], part_path: str) -> bool:
    """
    安全移除 OOXML 内部部件（例如 comments.xml / custom.xml / thumbnail），
    同步清理所有 .rels 引用与 [Content_Types].xml 中的 Override，防止 Office 打开报修复警告。
    """
    norm_part = posixpath.normpath(part_path).lstrip("/")
    removed = False
    if norm_part in entries:
        entries.pop(norm_part, None)
        removed = True
    while norm_part in order:
        order.remove(norm_part)

    # 清理 .rels 引用
    for rel_name in list(entries.keys()):
        if not rel_name.endswith(".rels"):
            continue
        try:
            root = parse_xml(entries[rel_name])
        except Exception:
            continue
        rel_changed = False
        for rel in list(root):
            if rel.get("TargetMode") == "External":
                continue
            resolved = _resolve_rel_target(rel_name, rel.get("Target", ""))
            if resolved == norm_part:
                root.remove(rel)
                rel_changed = True
        if rel_changed:
            entries[rel_name] = serialize_xml(root)

    # 清理 [Content_Types].xml
    ct_name = "[Content_Types].xml"
    if ct_name in entries:
        try:
            ct_root = parse_xml(entries[ct_name])
            ct_changed = False
            for child in list(ct_root):
                if child.tag.endswith("Override"):
                    pname = (child.get("PartName") or "").lstrip("/")
                    if posixpath.normpath(pname) == norm_part:
                        ct_root.remove(child)
                        ct_changed = True
            if ct_changed:
                entries[ct_name] = serialize_xml(ct_root)
        except Exception:
            pass

    return removed


def inspect_ooxml_docprops(entries: dict[str, bytes]) -> dict:
    """检查 OOXML 文档属性（作者、公司、自定义属性、缩略图）。"""
    info = {
        "authors": [],
        "meta_count": 0,
        "has_thumbnail": False,
        "has_custom_props": False,
    }
    if "docProps/core.xml" in entries:
        try:
            root = parse_xml(entries["docProps/core.xml"])
            for el in root:
                if el.tag in _CORE_SCRUB_TAGS and el.text and el.text.strip():
                    info["meta_count"] += 1
                    if el.tag in (f"{{{NS_DC}}}creator", f"{{{NS_CP}}}lastModifiedBy"):
                        val = el.text.strip()
                        if val not in info["authors"]:
                            info["authors"].append(val)
        except Exception:
            pass

    if "docProps/app.xml" in entries:
        try:
            root = parse_xml(entries["docProps/app.xml"])
            for el in root:
                if el.tag in _APP_SCRUB_TAGS and el.text and el.text.strip():
                    info["meta_count"] += 1
        except Exception:
            pass

    if "docProps/custom.xml" in entries:
        info["has_custom_props"] = True
        info["meta_count"] += 1

    for name in entries:
        if name.startswith("docProps/thumbnail."):
            info["has_thumbnail"] = True
            break

    return info


def scrub_ooxml_docprops(order: list[str], entries: dict[str, bytes], cfg: dict) -> list[str]:
    """清理 OOXML core.xml / app.xml / custom.xml / 缩略图。"""
    opts = cfg.get("options") or {}
    removed_items: list[str] = []

    if opts.get("clean_metadata", True):
        if "docProps/core.xml" in entries:
            try:
                root = parse_xml(entries["docProps/core.xml"])
                changed = False
                for el in root:
                    if el.tag in _CORE_SCRUB_TAGS and el.text and el.text.strip():
                        el.text = ""
                        changed = True
                if changed:
                    entries["docProps/core.xml"] = serialize_xml(root)
                    removed_items.append("文档核心属性（作者/修改人/标题等）")
            except Exception:
                pass

        if "docProps/app.xml" in entries:
            try:
                root = parse_xml(entries["docProps/app.xml"])
                changed = False
                for el in root:
                    if el.tag in _APP_SCRUB_TAGS and el.text and el.text.strip():
                        el.text = ""
                        changed = True
                if changed:
                    entries["docProps/app.xml"] = serialize_xml(root)
                    removed_items.append("扩展属性（公司/管理者/超链接基址）")
            except Exception:
                pass

        if remove_ooxml_part(order, entries, "docProps/custom.xml"):
            removed_items.append("自定义属性 (docProps/custom.xml)")

    if opts.get("clean_thumbnails", True):
        for name in list(entries.keys()):
            if name.startswith("docProps/thumbnail."):
                if remove_ooxml_part(order, entries, name):
                    removed_items.append(f"文档缩略图 ({name})")

    return removed_items


def inspect_external_rels(entries: dict[str, bytes]) -> list[tuple[str, str]]:
    """收集所有 *.rels 中的外部链接目标。"""
    out = []
    for name, data in entries.items():
        if not name.endswith(".rels"):
            continue
        try:
            root = parse_xml(data)
        except Exception:
            continue
        for rel in root:
            if rel.get("TargetMode") == "External":
                tgt = (rel.get("Target") or "").strip()
                if tgt:
                    out.append((name, tgt))
    return out


def scrub_external_rels(entries: dict[str, bytes], regex, rep_map: dict, cfg: dict) -> list[dict]:
    """脱敏外部超链接 Target（包括 mailto: 与含敏感词 URL）。"""
    opts = cfg.get("options") or {}
    if not opts.get("clean_hyperlinks", True):
        return []
    changes = []
    for name, data in list(entries.items()):
        if not name.endswith(".rels"):
            continue
        try:
            root = parse_xml(data)
        except Exception:
            continue
        changed = False
        for rel in root:
            if rel.get("TargetMode") != "External":
                continue
            tgt = rel.get("Target") or ""
            if not tgt:
                continue
            new_tgt = tgt
            if regex is not None and rep_map:
                new_tgt = regex.sub(lambda m: rep_map.get(m.group(0), m.group(0)), new_tgt)
            if new_tgt == tgt and tgt.lower().startswith("mailto:"):
                new_tgt = "mailto:[已脱敏邮箱]"
            if new_tgt != tgt:
                rel.set("Target", new_tgt)
                changed = True
                changes.append({"location": name, "orig": tgt, "new": new_tgt})
        if changed:
            entries[name] = serialize_xml(root)
    return changes


def collect_all_xml_text(entries: dict[str, bytes], include_rels: bool = True) -> str:
    """提取 ZIP 中所有 XML 部件的纯文本与属性，用于残留校验。"""
    chunks = []
    for name, data in entries.items():
        if not (name.endswith(".xml") or (include_rels and name.endswith(".rels"))):
            continue
        try:
            root = parse_xml(data)
        except Exception:
            continue
        for txt in root.itertext():
            if txt and txt.strip():
                chunks.append(txt)
        if name.endswith(".rels"):
            for rel in root:
                if rel.get("TargetMode") == "External" and rel.get("Target"):
                    chunks.append(rel.get("Target"))
    return "\n".join(chunks)
