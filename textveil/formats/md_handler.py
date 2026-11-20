"""Markdown / 纯文本 (.md / .markdown / .txt) 扫描、脱敏、还原与校验处理器。"""

import os
import re
from ..detectors import Detector, Findings, classify_header, name_like
from ..masking import active_replace_map, mapping_regex, term_present

_RE_FENCE = re.compile(r"^\s*(```+|~~~+)")
_RE_TABLE_SEP = re.compile(r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$")
_META_FRONTMATTER_KEYS = {"author", "authors", "creator", "email", "company", "organization", "owner", "maintainer"}


def _read_text_auto(path: str) -> tuple[str, str, str]:
    with open(path, "rb") as f:
        raw = f.read()
    encoding = "utf-8"
    if raw.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
        text = raw.decode("utf-8-sig")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            encoding = "gb18030"
            text = raw.decode("gb18030", errors="replace")
    eol = "\r\n" if "\r\n" in text else "\n"
    return text, encoding, eol


def _split_md_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _frontmatter_bounds(lines: list[str]) -> tuple[int, int]:
    if not lines or lines[0].strip() != "---":
        return -1, -1
    for i in range(1, min(len(lines), 80)):
        if lines[i].strip() in ("---", "..."):
            return 0, i
    return -1, -1


def scan_file(path: str, det: Detector, findings: Findings, fname: str) -> dict:
    text, _, _ = _read_text_auto(path)
    lines = text.splitlines()
    fm_start, fm_end = _frontmatter_bounds(lines)
    meta_count = 0
    fm_authors = []

    in_code = False
    fence_char = ""
    table_headers: list[str] = []

    # 标题 / 开头几行里的项目名称（frontmatter 里的 title 也算）
    head = []
    for i, ln in enumerate(lines):
        if fm_start <= i <= fm_end:
            kv = re.match(r"^\s*title\s*:\s*(.+)$", ln, re.I)
            if kv:
                head.append(kv.group(1).strip().strip("\"'"))
            continue
        if ln.strip() and not _RE_FENCE.match(ln) and "|" not in ln:
            head.append(ln.strip())
        if len(head) >= 8:
            break
    for term, cat, rule, crep in det.detect_cover_lines(head):
        findings.add(term, cat, rule, fname, sample=term, custom_replace=crep)

    for idx, line in enumerate(lines):
        # 1. YAML Frontmatter
        if fm_start <= idx <= fm_end:
            if idx not in (fm_start, fm_end):
                kv = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.+)$", line.strip())
                if kv:
                    k, v = kv.group(1).lower(), kv.group(2).strip().strip("\"'")
                    if k in _META_FRONTMATTER_KEYS and v:
                        meta_count += 1
                        if k in ("author", "creator", "owner") and name_like(v):
                            fm_authors.append(v)
                    for term, cat, rule, crep in det.detect_text(line):
                        findings.add(term, cat, "YAML Frontmatter", fname, sample=line, custom_replace=crep)
            continue

        # 2. 代码块围栏状态切换
        fm = _RE_FENCE.match(line)
        if fm:
            marker = fm.group(1)
            if not in_code:
                in_code = True
                fence_char = marker[0]
            elif marker[0] == fence_char:
                in_code = False
                fence_char = ""
            table_headers = []
            continue

        # 3. Markdown 表格上下文
        if not in_code and "|" in line:
            if _RE_TABLE_SEP.match(line) and idx > 0 and "|" in lines[idx - 1]:
                table_headers = _split_md_row(lines[idx - 1])
                continue
            if table_headers:
                cells = _split_md_row(line)
                for c_idx, cell in enumerate(cells):
                    hdr = table_headers[c_idx] if c_idx < len(table_headers) else ""
                    for term, cat, rule, crep in det.detect_table_cell(hdr, cell):
                        findings.add(term, cat, rule, fname, sample=cell, custom_replace=crep)
                    # Markdown 表格一定有表头：列头说明了含义时不再用左侧单元格猜
                    if c_idx > 0 and not classify_header(hdr):
                        for term, cat, rule, crep in det.detect_kv_cell(cells[c_idx - 1], cell):
                            findings.add(term, cat, rule, fname, sample=cell, custom_replace=crep)
                continue
        else:
            table_headers = []

        # 4. 正文 / 代码行扫描
        for term, cat, rule, crep in det.detect_text(line, in_code=in_code):
            r_label = f"代码块({rule})" if in_code else rule
            findings.add(term, cat, r_label, fname, sample=line, custom_replace=crep)

    if (det.cfg.get("options") or {}).get("detect_author_in_body", True) and fm_authors:
        for a in fm_authors:
            if det.allowed(a):
                findings.add(a, "person", "Frontmatter 作者", fname, sample=a)

    return {
        "format": "Markdown",
        "meta_count": meta_count,
        "comment_count": 0,
        "revision_count": 0,
        "hyperlink_count": len(re.findall(r"\[[^\]]*\]\([^)]+\)", text)),
        "thumbnail_count": 0,
        "hidden_sheet_count": 0,
        "notes": [],
    }


def _transform_md(
    path: str,
    out_path: str,
    regex,
    rep_map: dict,
    cfg: dict,
    restore_mode: bool = False,
) -> dict:
    text, encoding, eol = _read_text_auto(path)
    lines = text.splitlines()
    fm_start, fm_end = _frontmatter_bounds(lines)
    opts = cfg.get("options") or {}
    changes: list[dict] = []
    removed: list[str] = []

    new_lines = []
    for idx, line in enumerate(lines):
        new_line = line

        if not restore_mode and fm_start < idx < fm_end and opts.get("clean_metadata", True):
            kv = re.match(r"^([A-Za-z0-9_-]+)(\s*:\s*)(.+)$", line)
            if kv and kv.group(1).lower() in _META_FRONTMATTER_KEYS:
                new_line = f"{kv.group(1)}{kv.group(2)}\"\""
                if "YAML Frontmatter 属性" not in removed:
                    removed.append("YAML Frontmatter 属性")
                new_lines.append(new_line)
                continue

        if regex is not None and rep_map:
            is_table_row = "|" in new_line and not _RE_TABLE_SEP.match(new_line)

            def sub_fn(m):
                orig = m.group(0)
                rep = rep_map.get(orig, orig)
                if is_table_row and "|" in rep:
                    rep = rep.replace("|", "\\|")
                if rep != orig:
                    changes.append({"location": f"L{idx + 1}", "orig": orig, "new": rep})
                return rep

            new_line = regex.sub(sub_fn, new_line)

        new_lines.append(new_line)

    trailing = eol if text.endswith(("\n", "\r")) else ""
    out_text = eol.join(new_lines) + trailing
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding=encoding, newline="") as f:
        f.write(out_text)

    return {"changes": changes, "removed": removed, "notes": []}


def apply_file(path: str, out_path: str, mapping: dict, cfg: dict) -> dict:
    regex = mapping_regex(mapping, only_enabled=True)
    rep_map = active_replace_map(mapping)
    return _transform_md(path, out_path, regex, rep_map, cfg, restore_mode=False)


def restore_file(path: str, out_path: str, inv_regex, inv_map: dict, cfg: dict) -> dict:
    return _transform_md(path, out_path, inv_regex, inv_map, cfg, restore_mode=True)


def verify_file(src_path: str, out_path: str, check_terms: list[str]) -> dict:
    try:
        src_text, _, _ = _read_text_auto(src_path)
        out_text, _, _ = _read_text_auto(out_path)
    except Exception as e:
        return {"structure_ok": False, "structure_msg": f"Markdown 读取失败：{e}", "residual": []}

    src_lines = len(src_text.splitlines())
    out_lines = len(out_text.splitlines())
    residual = [t for t in check_terms if term_present(t, out_text)]
    return {
        "structure_ok": src_lines == out_lines,
        "structure_msg": f"文本行数一致（{out_lines} / {src_lines} 行）",
        "residual": residual,
    }
