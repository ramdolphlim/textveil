"""PDF (.pdf) 扫描、物理涂黑/替换脱敏、可逆还原与校验处理器（基于 PyMuPDF）。"""

import os
import re
import pymupdf
from ..detectors import Detector, Findings, name_like
from ..masking import active_replace_map

_CJK_FONT_CANDIDATES = (
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)


def pick_cjk_font() -> tuple[str, str | None]:
    """返回 (fontname, fontfile_or_None)，用于 PDF 中英文替换文本渲染与可检索嵌入。"""
    for p in _CJK_FONT_CANDIDATES:
        if os.path.isfile(p):
            return "dv_cjk", p
    return "china-s", None


def _overlap_ratio(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    inter = a & b
    if inter.is_empty or a.get_area() <= 0:
        return 0.0
    return inter.get_area() / a.get_area()


def _collect_page_spans(page) -> list[tuple[pymupdf.Rect, float]]:
    spans = []
    try:
        d = page.get_text("dict")
    except Exception:
        return spans
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for sp in line.get("spans", []):
                bbox = sp.get("bbox")
                sz = float(sp.get("size") or 10.5)
                if bbox:
                    spans.append((pymupdf.Rect(bbox), sz))
    return spans


def _estimate_fontsize(spans: list[tuple[pymupdf.Rect, float]], rect: pymupdf.Rect) -> float:
    best_overlap = 0.0
    best_size = max(7.0, min(14.0, rect.height * 0.78))
    for sr, sz in spans:
        inter = sr & rect
        if not inter.is_empty and inter.get_area() > best_overlap:
            best_overlap = inter.get_area()
            best_size = sz
    return max(6.5, min(18.0, best_size))


def _fit_fontsize(text: str, target_width: float, base_fs: float, font_obj) -> float:
    if not text or target_width <= 2:
        return base_fs
    try:
        if font_obj is not None:
            w = font_obj.text_length(text, fontsize=base_fs)
        else:
            w = pymupdf.get_text_length(text, fontname="china-s", fontsize=base_fs)
    except Exception:
        w = len(text) * base_fs * 0.7
    if w <= target_width * 0.98 or w <= 0:
        return base_fs
    scaled = base_fs * (target_width * 0.96) / w
    return max(4.2, min(base_fs, scaled))


def scan_file(path: str, det: Detector, findings: Findings, fname: str) -> dict:
    doc = pymupdf.open(path)
    opts = det.cfg.get("options") or {}
    notes = []
    scanned_pages = []
    meta_count = 0
    comment_count = 0
    hyperlink_count = 0

    try:
        if doc.is_encrypted and not doc.authenticate(""):
            raise RuntimeError("PDF 已加密且需要密码打开，无法直接扫描")

        meta = doc.metadata or {}
        authors = []
        for k, v in meta.items():
            if v and str(v).strip() and k.lower() in ("author", "creator", "producer", "title", "subject", "keywords"):
                meta_count += 1
                if k.lower() == "author":
                    authors.append(str(v).strip())
        try:
            if doc.get_xml_metadata():
                meta_count += 1
        except Exception:
            pass

        # TOC 书签扫描
        try:
            for item in doc.get_toc() or []:
                title = item[1] if len(item) > 1 else ""
                if title:
                    for term, cat, rule, crep in det.detect_text(title):
                        findings.add(term, cat, "PDF 书签目录", fname, sample=title, custom_replace=crep)
        except Exception:
            pass

        body_chunks = []
        for i, page in enumerate(doc):
            text = page.get_text("text") or ""
            if len(text.strip()) < 5 and len(page.get_images(full=False)) > 0:
                scanned_pages.append(i + 1)

            if text.strip():
                body_chunks.append(text)
                for line in text.splitlines():
                    if not line.strip():
                        continue
                    for term, cat, rule, crep in det.detect_text(line):
                        findings.add(term, cat, rule, fname, sample=line, custom_replace=crep)

            # 注释 / 批注扫描
            for annot in page.annots() or []:
                comment_count += 1
                info = annot.info or {}
                for field_name in ("content", "title", "subject"):
                    val = (info.get(field_name) or "").strip()
                    if val:
                        for term, cat, rule, crep in det.detect_text(val):
                            findings.add(term, cat, "PDF 批注", fname, sample=val, custom_replace=crep)

            # 超链接扫描
            for lk in page.get_links() or []:
                uri = (lk.get("uri") or "").strip()
                if uri:
                    hyperlink_count += 1
                    clean_uri = uri[7:] if uri.lower().startswith("mailto:") else uri
                    for term, cat, rule, crep in det.detect_text(clean_uri):
                        findings.add(term, cat, "PDF 超链接", fname, sample=uri, custom_replace=crep)

        if opts.get("detect_author_in_body", True) and authors:
            joined = "\n".join(body_chunks)
            for a in authors:
                if a in joined and det.allowed(a) and name_like(a):
                    findings.add(a, "person", "文档属性作者", fname, sample=a)

        if scanned_pages:
            p_str = "、".join(str(p) for p in scanned_pages[:6])
            if len(scanned_pages) > 6:
                p_str += f" 等 {len(scanned_pages)} 页"
            notes.append(f"第 {p_str} 页为纯图片/扫描页（无文本层），请人工确认是否含敏感图像")
    finally:
        doc.close()

    return {
        "format": "PDF",
        "meta_count": meta_count,
        "comment_count": comment_count,
        "revision_count": 0,
        "hyperlink_count": hyperlink_count,
        "thumbnail_count": 0,
        "hidden_sheet_count": 0,
        "notes": notes,
    }


def _transform_pdf(
    path: str,
    out_path: str,
    rep_map: dict,
    cfg: dict,
    restore_mode: bool = False,
) -> dict:
    doc = pymupdf.open(path)
    opts = cfg.get("options") or {}
    mode = cfg.get("mode", "placeholder")
    pdf_style = cfg.get("pdf_style", "replace")
    use_blackbox = (not restore_mode) and (mode == "mask") and (pdf_style == "blackbox")

    fontname, fontfile = pick_cjk_font()
    font_obj = pymupdf.Font(fontfile=fontfile) if fontfile else pymupdf.Font("china-s")

    changes: list[dict] = []
    removed: list[str] = []
    notes: list[str] = []

    try:
        if doc.is_encrypted and not doc.authenticate(""):
            raise RuntimeError("PDF 已加密且需要密码打开，无法写入脱敏内容")

        sorted_terms = sorted(
            ((k, v) for k, v in (rep_map or {}).items() if k and v is not None and k != v),
            key=lambda kv: len(kv[0]),
            reverse=True,
        )

        # 构建替换正则用于书签和超链接
        term_regex = None
        if sorted_terms:
            term_regex = re.compile("|".join(re.escape(k) for k, _ in sorted_terms))

        for pno, page in enumerate(doc):
            spans = _collect_page_spans(page)
            claimed_rects: list[pymupdf.Rect] = []
            draw_ops: list[tuple[pymupdf.Rect, str, float]] = []

            for term, rep in sorted_terms:
                try:
                    rects = page.search_for(term, quads=False)
                except Exception:
                    rects = []
                if not rects:
                    continue

                prev_rect = None
                for raw_r in rects:
                    # 微调高度避免误伤上下相邻行字母
                    r = pymupdf.Rect(raw_r)
                    if r.height > 6:
                        r.y0 += 0.4
                        r.y1 -= 0.4

                    if any(_overlap_ratio(r, cr) > 0.55 for cr in claimed_rects):
                        continue
                    claimed_rects.append(r)

                    # 判断是否为同一匹配项在行尾折行后的第二段矩形
                    is_wrap_cont = (
                        prev_rect is not None
                        and raw_r.y0 > prev_rect.y0 + 1.5
                        and prev_rect.x1 > page.rect.width * 0.62
                        and raw_r.x0 < prev_rect.x0 - 40
                    )
                    prev_rect = raw_r

                    fill_col = (0.08, 0.08, 0.08) if use_blackbox else (1.0, 1.0, 1.0)
                    page.add_redact_annot(r, text="", fill=fill_col)

                    if not use_blackbox and not is_wrap_cont:
                        base_fs = _estimate_fontsize(spans, raw_r)
                        draw_ops.append((pymupdf.Rect(raw_r), rep, base_fs))

                    changes.append({"location": f"P.{pno + 1}", "orig": term, "new": "[涂黑]" if use_blackbox else rep})

            if claimed_rects:
                # 物理抹除底层文本指令，只保留图片以免破坏版面配图
                page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)

            if draw_ops:
                if fontfile:
                    page.insert_font(fontname=fontname, fontfile=fontfile)
                for raw_r, rep, base_fs in draw_ops:
                    fs = _fit_fontsize(rep, raw_r.width, base_fs, font_obj)
                    baseline_y = raw_r.y1 - 0.22 * raw_r.height
                    page.insert_text(
                        (raw_r.x0 + 0.3, baseline_y),
                        rep,
                        fontname=fontname,
                        fontsize=fs,
                        color=(0.12, 0.12, 0.12),
                        overlay=True,
                    )

            # 清理批注注释
            if not restore_mode and opts.get("clean_comments", True):
                for annot in list(page.annots() or []):
                    if annot.type[0] != pymupdf.PDF_ANNOT_REDACT:
                        page.delete_annot(annot)
                        if "PDF 批注注释" not in removed:
                            removed.append("PDF 批注注释")

            # 清理超链接
            if term_regex is not None or (not restore_mode and opts.get("clean_hyperlinks", True)):
                for lk in list(page.get_links() or []):
                    uri = lk.get("uri") or ""
                    if not uri:
                        continue
                    new_uri = uri
                    if term_regex is not None:
                        new_uri = term_regex.sub(lambda m: rep_map.get(m.group(0), m.group(0)), new_uri)
                    if not restore_mode and new_uri == uri and uri.lower().startswith("mailto:"):
                        new_uri = "mailto:[已脱敏邮箱]"
                    if new_uri != uri:
                        lk["uri"] = new_uri
                        page.update_link(lk)
                        changes.append({"location": f"P.{pno + 1}(超链接)", "orig": uri, "new": new_uri})

        # 脱敏 TOC 书签标题
        if term_regex is not None:
            try:
                toc = doc.get_toc() or []
                toc_changed = False
                for item in toc:
                    if len(item) >= 2 and isinstance(item[1], str):
                        new_title = term_regex.sub(lambda m: rep_map.get(m.group(0), m.group(0)), item[1])
                        if new_title != item[1]:
                            changes.append({"location": "PDF书签", "orig": item[1], "new": new_title})
                            item[1] = new_title
                            toc_changed = True
                if toc_changed:
                    doc.set_toc(toc)
            except Exception:
                pass

        # 清理 PDF Metadata & XMP
        if not restore_mode and opts.get("clean_metadata", True):
            had_meta = any(v for v in (doc.metadata or {}).values() if v)
            doc.set_metadata({})
            try:
                if doc.get_xml_metadata():
                    doc.del_xml_metadata()
                    had_meta = True
            except Exception:
                pass
            if had_meta:
                removed.append("PDF 文档属性与 XMP 元数据")

        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        doc.save(out_path, garbage=4, deflate=True, clean=True)
    finally:
        doc.close()

    return {"changes": changes, "removed": removed, "notes": notes}


def apply_file(path: str, out_path: str, mapping: dict, cfg: dict) -> dict:
    rep_map = active_replace_map(mapping)
    return _transform_pdf(path, out_path, rep_map, cfg, restore_mode=False)


def restore_file(path: str, out_path: str, inv_regex, inv_map: dict, cfg: dict) -> dict:
    return _transform_pdf(path, out_path, inv_map, cfg, restore_mode=True)


def verify_file(src_path: str, out_path: str, check_terms: list[str]) -> dict:
    try:
        d_src = pymupdf.open(src_path)
        src_pages = len(d_src)
        d_src.close()

        d_out = pymupdf.open(out_path)
        out_pages = len(d_out)
        chunks = [page.get_text("text") or "" for page in d_out]
        for k, v in (d_out.metadata or {}).items():
            if v:
                chunks.append(str(v))
        try:
            for item in d_out.get_toc() or []:
                if len(item) > 1 and item[1]:
                    chunks.append(str(item[1]))
        except Exception:
            pass
        for page in d_out:
            for annot in page.annots() or []:
                for val in (annot.info or {}).values():
                    if val:
                        chunks.append(str(val))
            for lk in page.get_links() or []:
                if lk.get("uri"):
                    chunks.append(str(lk["uri"]))
        d_out.close()
    except Exception as e:
        return {"structure_ok": False, "structure_msg": f"PDF 验证打开失败：{e}", "residual": []}

    full_text = "\n".join(chunks)
    residual = [t for t in check_terms if t and t in full_text]
    return {
        "structure_ok": src_pages == out_pages,
        "structure_msg": f"PDF 页数完整（{out_pages} / {src_pages} 页）",
        "residual": residual,
    }
