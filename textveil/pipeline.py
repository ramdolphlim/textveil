"""统一文档扫描、脱敏执行、报告生成与可逆还原流水线。"""

import csv
import html
import json
import os
import re
import time
from . import APP_NAME, APP_VERSION, FORMAT_LABELS, SUPPORTED_EXTS
from .config import CAT_NAMES, merge_config
from .detectors import Detector, Findings
from .formats import apply_file, restore_file, scan_file, verify_file
from .masking import (
    build_inverse_mapping,
    build_mapping,
    inverse_regex,
    load_mapping_file,
    mapping_export,
)

_SKIP_DIR_NAMES = {"脱敏输出", "已脱敏", "还原输出", "__pycache__", ".git", ".venv", "node_modules"}
_PLACEHOLDER_REMNANT_RE = re.compile(r"\[[\u4e00-\u9fffA-Za-z]+_\d{2,4}\]")


def collect_files(
    paths: list[str],
    output_suffix: str = "_脱敏",
    skip_redacted: bool = True,
) -> list[tuple[str, str]]:
    """收集目录下所有支持格式的文档，返回 [(绝对路径, 相对路径), ...]。"""
    found: list[tuple[str, str]] = []
    seen = set()

    def maybe_add(abs_p: str, rel_p: str):
        abs_p = os.path.abspath(abs_p)
        if abs_p in seen or not os.path.isfile(abs_p):
            return
        bn = os.path.basename(abs_p)
        if bn.startswith((".", "~$")):
            return
        stem, ext = os.path.splitext(bn)
        if ext.lower() not in SUPPORTED_EXTS:
            return
        if skip_redacted and output_suffix and stem.endswith(output_suffix):
            return
        seen.add(abs_p)
        found.append((abs_p, rel_p))

    for raw in paths or []:
        if not raw:
            continue
        p = os.path.abspath(os.path.expanduser(raw))
        if os.path.isfile(p):
            maybe_add(p, os.path.basename(p))
        elif os.path.isdir(p):
            base_parent = p
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(
                    d
                    for d in dirs
                    if not d.startswith(".")
                    and d not in _SKIP_DIR_NAMES
                    and not d.startswith("_脱敏报告")
                )
                for fn in sorted(files):
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, base_parent)
                    maybe_add(full, rel)

    return found


def _output_filename(rel: str, suffix: str, strip_suffix: str = "") -> str:
    d = os.path.dirname(rel)
    bn = os.path.basename(rel)
    stem, ext = os.path.splitext(bn)
    if strip_suffix and stem.endswith(strip_suffix):
        stem = stem[: -len(strip_suffix)]
    new_bn = f"{stem}{suffix}{ext}"
    return os.path.join(d, new_bn) if d else new_bn


def scan_pipeline(
    files: list[tuple[str, str]],
    cfg: dict,
    previous_mapping=None,
    log=None,
) -> dict:
    """扫描一批文档，提取敏感词与文档元数据/批注/修订统计。"""
    t0 = time.time()
    det = Detector(cfg)
    findings = Findings()
    file_stats = []
    errors = []
    format_counts = {}
    meta_totals = {
        "meta_count": 0,
        "comment_count": 0,
        "revision_count": 0,
        "hyperlink_count": 0,
        "thumbnail_count": 0,
        "hidden_sheet_count": 0,
    }

    for abs_p, rel in files:
        if log:
            log(f"➤ 正在扫描：{rel}")
        ext = os.path.splitext(abs_p)[1].lower()
        fmt_label = FORMAT_LABELS.get(ext, ext)
        format_counts[fmt_label] = format_counts.get(fmt_label, 0) + 1
        try:
            st = scan_file(abs_p, det, findings, rel)
            for k in meta_totals:
                meta_totals[k] += int(st.get(k, 0))
            file_stats.append(
                {
                    "path": abs_p,
                    "rel": rel,
                    "format": fmt_label,
                    "status": "ok",
                    "error": "",
                    **st,
                }
            )
        except Exception as e:
            err = f"{rel}：{e}"
            errors.append(err)
            file_stats.append(
                {
                    "path": abs_p,
                    "rel": rel,
                    "format": fmt_label,
                    "status": "error",
                    "error": str(e),
                    "notes": [],
                }
            )

    mapping = build_mapping(findings, cfg, previous=previous_mapping)
    elapsed = round(time.time() - t0, 2)

    return {
        "files": len(files),
        "file_stats": file_stats,
        "format_counts": format_counts,
        "meta_totals": meta_totals,
        "errors": errors,
        "mapping": mapping,
        "terms": mapping["entries"],
        "findings": findings,
        "seconds": elapsed,
    }


def _write_csv_reports(report_dir: str, mapping: dict, jobs: list[dict]) -> tuple[str, str]:
    map_csv = os.path.join(report_dir, "映射表.csv")
    with open(map_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["原文", "类别", "识别规则", "当前替换", "可逆占位符", "掩码值", "启用", "出现次数", "涉及文档"])
        for e in mapping.get("entries", []):
            w.writerow(
                [
                    e["term"],
                    e.get("cat_name") or CAT_NAMES.get(e["cat"], e["cat"]),
                    e.get("rule", ""),
                    e["replace"],
                    e.get("placeholder_replace", ""),
                    e.get("mask_replace", ""),
                    "是" if e.get("enabled", True) else "否",
                    e.get("count", 1),
                    " | ".join(e.get("files", [])),
                ]
            )

    detail_csv = os.path.join(report_dir, "改动明细.csv")
    with open(detail_csv, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["文档", "位置", "原文", "替换为"])
        for j in jobs:
            for ch in j.get("changes", []):
                w.writerow([j["rel"], ch.get("location", ""), ch.get("orig", ""), ch.get("new", "")])
    return map_csv, detail_csv


def _write_html_report(report_dir: str, cfg: dict, mapping: dict, jobs: list[dict], elapsed: float) -> str:
    path = os.path.join(report_dir, "脱敏报告.html")
    entries = mapping.get("entries", [])
    enabled_cnt = sum(1 for e in entries if e.get("enabled", True))
    total_hits = sum(e.get("count", 1) for e in entries if e.get("enabled", True))
    ok_files = sum(1 for j in jobs if not j.get("error") and (j.get("verify") or {}).get("structure_ok") and not (j.get("verify") or {}).get("residual"))
    mode_label = "可逆占位符" if cfg.get("mode") == "placeholder" else "不可逆掩码遮蔽"

    file_rows = []
    for j in jobs:
        v = j.get("verify") or {}
        res = v.get("residual") or []
        ok = (not j.get("error")) and v.get("structure_ok", False) and not res
        status_cls = "ok" if ok else "bad"
        status_txt = "通过" if ok else ("失败: " + (j.get("error") or f"残留 {len(res)} 处"))
        removed_txt = "、".join(j.get("removed") or []) or "—"
        notes_txt = "；".join(j.get("notes") or []) or "—"
        file_rows.append(
            f"<tr>"
            f"<td>{html.escape(j['rel'])}</td>"
            f"<td class='mono'>{len(j.get('changes', []))}</td>"
            f"<td>{html.escape(removed_txt)}</td>"
            f"<td>{html.escape(v.get('structure_msg', '—'))}</td>"
            f"<td class='{status_cls}'>{html.escape(status_txt)}</td>"
            f"<td>{html.escape(notes_txt)}</td>"
            f"</tr>"
        )

    map_rows = []
    for e in entries:
        if not e.get("enabled", True):
            continue
        map_rows.append(
            f"<tr>"
            f"<td>{html.escape(e['term'])}</td>"
            f"<td class='mono'>{html.escape(e['replace'])}</td>"
            f"<td>{html.escape(e.get('cat_name') or CAT_NAMES.get(e['cat'], e['cat']))}</td>"
            f"<td>{html.escape(e.get('rule', ''))}</td>"
            f"<td class='mono'>{e.get('count', 1)}</td>"
            f"<td>{html.escape('、'.join(e.get('files', [])))}</td>"
            f"</tr>"
        )

    doc_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html.escape(APP_NAME)} · 脱敏校验报告</title>
<style>
  :root {{
    --paper:#FBFAF6; --card:#FEFDFB; --ink:#3D3D3A; --muted:#6B6A64;
    --line:#DCD9CD; --brand:#144A74; --ok:#15803D; --bad:#B91C1C; --warn-bg:#FBF1DC; --warn:#92400E;
  }}
  body {{ margin:0; padding:36px 24px 60px; background:var(--paper); color:var(--ink);
          font:14px/1.6 -apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif; }}
  .wrap {{ max-width:980px; margin:0 auto; }}
  h1 {{ margin:0 0 6px; font-family:'Source Han Serif SC','Songti SC',Charter,Georgia,serif; font-size:28px; }}
  .sub {{ color:var(--muted); margin:0 0 20px; font-size:13px; }}
  .warn {{ background:var(--warn-bg); color:var(--warn); padding:12px 16px; border-radius:10px;
           border:1px solid #EBD7AD; margin-bottom:24px; font-weight:500; }}
  .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:28px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
  .card .k {{ color:var(--muted); font-size:12px; }}
  .card .v {{ font-size:24px; font-weight:600; margin-top:4px; font-variant-numeric:tabular-nums; }}
  h2 {{ font-size:16px; margin:28px 0 10px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }}
  th, td {{ padding:10px 12px; border-bottom:1px solid #EFEDE5; text-align:left; font-size:13px; vertical-align:top; }}
  th {{ background:#F5F3EC; font-weight:600; color:var(--muted); }}
  .mono {{ font-family:'SF Mono',ui-monospace,Menlo,Consolas,monospace; }}
  .ok {{ color:var(--ok); font-weight:600; }}
  .bad {{ color:var(--bad); font-weight:600; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{html.escape(APP_NAME)} 脱敏校验报告</h1>
  <p class="sub">生成时间：{time.strftime("%Y-%m-%d %H:%M:%S")} · 脱敏模式：{html.escape(mode_label)} · 用时 {elapsed}s · {html.escape(APP_NAME)} v{APP_VERSION}</p>
  <div class="warn">⚠ 重要提示：本报告与同目录下的映射表文件包含脱敏前敏感原文，仅限内部留存或后续逆向还原使用，切勿随脱敏文档一同对外发送！</div>
  <div class="cards">
    <div class="card"><div class="k">处理文档</div><div class="v">{len(jobs)}</div></div>
    <div class="card"><div class="k">校验通过</div><div class="v ok">{ok_files} / {len(jobs)}</div></div>
    <div class="card"><div class="k">启用脱敏条目</div><div class="v">{enabled_cnt}</div></div>
    <div class="card"><div class="k">累计替换次数</div><div class="v">{total_hits}</div></div>
  </div>
  <h2>文档校验明细</h2>
  <table>
    <thead><tr><th>文档</th><th>替换数</th><th>清理隐藏元素</th><th>结构校验</th><th>残留复查</th><th>备注</th></tr></thead>
    <tbody>{''.join(file_rows)}</tbody>
  </table>
  <h2>敏感信息映射明细</h2>
  <table>
    <thead><tr><th>原文</th><th>替换为</th><th>类别</th><th>规则</th><th>次数</th><th>涉及文档</th></tr></thead>
    <tbody>{''.join(map_rows) if map_rows else '<tr><td colspan="6" style="color:#6B6A64">未启用内容替换（仅清理元数据）</td></tr>'}</tbody>
  </table>
</div>
</body>
</html>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc_html)
    return path


def apply_pipeline(
    files: list[tuple[str, str]],
    out_dir: str,
    cfg: dict,
    report_dir: str | None = None,
    decisions: dict | None = None,
    previous_mapping=None,
    scan_result: dict | None = None,
    log=None,
    dry_run: bool = False,
) -> dict:
    """执行文档脱敏、校验并写出报告与映射表。"""
    t0 = time.time()
    cfg = merge_config(cfg)
    if scan_result is None:
        scan_result = scan_pipeline(files, cfg, previous_mapping=previous_mapping, log=log)

    mapping = build_mapping(
        scan_result["findings"],
        cfg,
        decisions=decisions,
        previous=previous_mapping,
    )

    enabled_entries = [e for e in mapping["entries"] if e.get("enabled", True)]
    # 复查时只检查确实被替换为不同字符串的原文（或者若用户设置替换词包含了原词则跳过自身包含检测）
    check_terms = [
        e["term"]
        for e in enabled_entries
        if e["term"] and e["replace"] != e["term"] and e["term"] not in e["replace"]
    ]

    suffix = cfg.get("output_suffix", "_脱敏")
    os.makedirs(out_dir, exist_ok=True)
    if report_dir is None:
        report_dir = os.path.join(out_dir, "_脱敏报告(含原文,勿外发)")

    jobs = []
    for abs_p, rel in files:
        out_rel = _output_filename(rel, suffix)
        out_p = os.path.join(out_dir, out_rel)

        if dry_run:
            jobs.append(
                {
                    "src": abs_p,
                    "rel": rel,
                    "output": out_p,
                    "changes": [],
                    "removed": [],
                    "notes": ["Dry-run 预览，未写出文件"],
                    "error": "",
                    "verify": {"structure_ok": True, "structure_msg": "预览模式", "residual": []},
                }
            )
            continue

        if log:
            log(f"➤ 正在脱敏：{rel}")
        try:
            res = apply_file(abs_p, out_p, mapping, cfg)
            v = verify_file(abs_p, out_p, check_terms)
            jobs.append(
                {
                    "src": abs_p,
                    "rel": rel,
                    "output": out_p,
                    "changes": res.get("changes", []),
                    "removed": res.get("removed", []),
                    "notes": res.get("notes", []),
                    "error": "",
                    "verify": v,
                }
            )
        except Exception as e:
            jobs.append(
                {
                    "src": abs_p,
                    "rel": rel,
                    "output": "",
                    "changes": [],
                    "removed": [],
                    "notes": [],
                    "error": str(e),
                    "verify": {"structure_ok": False, "structure_msg": str(e), "residual": []},
                }
            )

    elapsed = round(time.time() - t0, 2)
    report_html = ""
    mapping_json = ""
    mapping_csv = ""
    detail_csv = ""

    if not dry_run:
        os.makedirs(report_dir, exist_ok=True)
        export_obj = mapping_export(mapping)
        mapping_json = os.path.join(report_dir, "映射表.json")
        with open(mapping_json, "w", encoding="utf-8") as f:
            json.dump(export_obj, f, ensure_ascii=False, indent=2)
        mapping_csv, detail_csv = _write_csv_reports(report_dir, mapping, jobs)
        report_html = _write_html_report(report_dir, cfg, mapping, jobs, elapsed)

    ok_count = sum(
        1
        for j in jobs
        if not j["error"] and j["verify"].get("structure_ok") and not j["verify"].get("residual")
    )

    return {
        "jobs": jobs,
        "mapping": mapping,
        "report_dir": report_dir,
        "report_html": report_html,
        "mapping_json": mapping_json,
        "mapping_csv": mapping_csv,
        "detail_csv": detail_csv,
        "ok": ok_count,
        "total": len(jobs),
        "seconds": elapsed,
        "dry_run": dry_run,
    }


def restore_pipeline(
    files: list[tuple[str, str]],
    mapping_source,
    out_dir: str,
    cfg: dict | None = None,
    log=None,
) -> dict:
    """依据可逆占位符映射表，将脱敏文档一键还原回原始内容。"""
    t0 = time.time()
    cfg = merge_config(cfg)
    mapping_data = load_mapping_file(mapping_source) if isinstance(mapping_source, str) else mapping_source
    inv_map, warnings = build_inverse_mapping(mapping_data)
    inv_regex = inverse_regex(inv_map)

    os.makedirs(out_dir, exist_ok=True)
    strip_suffix = cfg.get("output_suffix", "_脱敏")
    jobs = []

    for abs_p, rel in files:
        if log:
            log(f"➤ 正在还原：{rel}")
        out_rel = _output_filename(rel, "_已还原", strip_suffix=strip_suffix)
        out_p = os.path.join(out_dir, out_rel)
        try:
            res = restore_file(abs_p, out_p, inv_regex, inv_map, cfg)
            # 校验输出结构并检查是否还有未命中映射表的残留占位符
            v = verify_file(abs_p, out_p, list(inv_map.keys()))
            # 读取输出文件内所有尚未被还原的 [类别_NN] 形制占位符
            ext = os.path.splitext(out_p)[1].lower()
            unmapped = []
            if ext in (".md", ".markdown", ".txt"):
                with open(out_p, "r", encoding="utf-8", errors="ignore") as f:
                    unmapped = sorted(set(_PLACEHOLDER_REMNANT_RE.findall(f.read())))
            jobs.append(
                {
                    "src": abs_p,
                    "rel": rel,
                    "output": out_p,
                    "changes": res.get("changes", []),
                    "restored_count": len(res.get("changes", [])),
                    "error": "",
                    "verify": v,
                    "unmapped_placeholders": unmapped,
                }
            )
        except Exception as e:
            jobs.append(
                {
                    "src": abs_p,
                    "rel": rel,
                    "output": "",
                    "changes": [],
                    "restored_count": 0,
                    "error": str(e),
                    "verify": {"structure_ok": False, "structure_msg": str(e), "residual": []},
                    "unmapped_placeholders": [],
                }
            )

    ok_count = sum(1 for j in jobs if not j["error"] and j["verify"].get("structure_ok"))
    return {
        "jobs": jobs,
        "warnings": warnings,
        "inv_count": len(inv_map),
        "ok": ok_count,
        "total": len(jobs),
        "seconds": round(time.time() - t0, 2),
    }
