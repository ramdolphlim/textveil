#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文隐 TextVeil — 本地多格式文档信息脱敏工具（CLI / Mole 交互菜单 / 桌面界面入口）。

支持格式：Word (.docx) · Excel (.xlsx / .xlsm) · PowerPoint (.pptx) · PDF (.pdf) · Markdown (.md / .txt)
"""

import argparse
import json
import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from textveil import APP_NAME, APP_VERSION  # noqa: E402
from textveil.cli_ui import (  # noqa: E402
    C,
    ICON_ADMIN,
    interactive_menu,
    print_err,
    print_ok,
    print_section,
    print_summary_block,
    print_warn,
    show_brand_banner,
)
from textveil.config import CAT_NAMES, DEFAULT_CONFIG, load_config, merge_config, preset_options  # noqa: E402
from textveil.formats import check_environment  # noqa: E402
from textveil.masking import load_mapping_file  # noqa: E402
from textveil.pipeline import apply_pipeline, collect_files, restore_pipeline, scan_pipeline  # noqa: E402


def _build_cfg(args) -> dict:
    cfg = load_config(args.config) if getattr(args, "config", None) else merge_config(None)
    if getattr(args, "preset", None):
        cfg["preset"] = args.preset
        cfg["options"] = preset_options(args.preset)
        if args.preset == "ai" and not getattr(args, "mode", None):
            cfg["mode"] = "placeholder"
    if getattr(args, "mode", None):
        cfg["mode"] = args.mode
    if getattr(args, "pdf_style", None):
        cfg["pdf_style"] = args.pdf_style
    if getattr(args, "keywords", None):
        extra = [x.strip() for x in args.keywords.split(",") if x.strip()]
        cfg["keywords"] = list(cfg.get("keywords") or []) + extra
    return cfg


def _cmd_check() -> int:
    env = check_environment()
    print()
    show_brand_banner()
    print()
    print(f"{ICON_ADMIN} 环境与格式引擎状态")
    print_section("格式引擎检查")
    labels = {
        "word": "Word (.docx)       python-docx + lxml",
        "excel": "Excel (.xlsx/.xlsm) openpyxl + lxml",
        "ppt": "PowerPoint (.pptx) python-pptx + lxml",
        "pdf": f"PDF (.pdf)         PyMuPDF ({env['pdf_font_path']})",
        "markdown": "Markdown (.md/.txt) 内置编码自适应引擎",
    }
    for key, desc in labels.items():
        if env["engines"].get(key):
            print_ok(desc)
        else:
            print_err(f"{desc} — 未安装")

    print_section("界面运行模式")
    if env["webview"]:
        print_ok("原生桌面窗口 (pywebview) 已就绪")
    else:
        print_warn("未安装 pywebview，桌面模式将自动使用本地浏览器视图 (--browser)")

    print_summary_block(
        "检查完成" if env["all_ready"] else "存在缺失依赖",
        [f"支持格式：Word / Excel / PPT / PDF / Markdown", f"当前默认模式：{DEFAULT_CONFIG['mode']}"],
    )
    return 0 if env["all_ready"] else 1


def _cmd_scan(args) -> int:
    cfg = _build_cfg(args)
    files = collect_files(args.paths, output_suffix=cfg.get("output_suffix", "_脱敏"))
    if not files:
        print_err("未找到支持的文档（.docx / .xlsx / .xlsm / .pptx / .pdf / .md / .txt）")
        return 1

    prev = load_mapping_file(args.mapping) if getattr(args, "mapping", None) else None
    if not getattr(args, "json", False):
        print()
        print(f"{C.PURPLE_BOLD}Scan Documents{C.NC}")
        print(f"{ICON_ADMIN} 模式：{'可逆占位符' if cfg['mode'] == 'placeholder' else '不可逆掩码'} | 文档数：{len(files)}")
        print_section("扫描进度")

    res = scan_pipeline(
        files,
        cfg,
        previous_mapping=prev,
        log=(None if getattr(args, "json", False) else lambda m: print(f"  {C.GRAY}{m}{C.NC}")),
    )

    if getattr(args, "json", False):
        out = {
            "files": res["files"],
            "seconds": res["seconds"],
            "format_counts": res["format_counts"],
            "meta_totals": res["meta_totals"],
            "errors": res["errors"],
            "terms": res["terms"],
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    print_section("扫描发现汇总")
    by_cat = {}
    for t in res["terms"]:
        by_cat[t["cat"]] = by_cat.get(t["cat"], 0) + t["count"]
    for cat, cnt in sorted(by_cat.items(), key=lambda x: -x[1]):
        print_ok(f"{CAT_NAMES.get(cat, cat)} · {cnt} 处")

    mt = res["meta_totals"]
    if any(mt.values()):
        print_section("隐藏元数据与批注")
        if mt["meta_count"]:
            print_ok(f"文档属性字段 · {mt['meta_count']} 项")
        if mt["comment_count"]:
            print_ok(f"批注 / 注释 · {mt['comment_count']} 条")
        if mt["revision_count"]:
            print_ok(f"修订记录 · {mt['revision_count']} 处")
        if mt["hidden_sheet_count"]:
            print_warn(f"Excel 隐藏工作表 · {mt['hidden_sheet_count']} 个")

    for st in res["file_stats"]:
        for n in st.get("notes") or []:
            print_warn(f"{st['rel']}：{n}")
    for err in res["errors"]:
        print_err(err)

    total_hits = sum(t["count"] for t in res["terms"])
    print_summary_block(
        "Scan complete",
        [
            f"敏感条目：{len(res['terms'])} 项（共 {total_hits} 处）",
            f"文档数量：{res['files']} 份 · 用时 {res['seconds']}s",
        ],
    )
    return 0


def _cmd_run(args) -> int:
    cfg = _build_cfg(args)
    files = collect_files(args.paths, output_suffix=cfg.get("output_suffix", "_脱敏"))
    if not files:
        print_err("未找到支持的文档（.docx / .xlsx / .xlsm / .pptx / .pdf / .md / .txt）")
        return 1

    first_src = files[0][0]
    default_out = (
        os.path.join(args.paths[0], "脱敏输出")
        if len(args.paths) == 1 and os.path.isdir(args.paths[0])
        else os.path.join(os.path.dirname(first_src), "脱敏输出")
    )
    out_dir = os.path.abspath(args.output or default_out)
    prev = load_mapping_file(args.mapping) if getattr(args, "mapping", None) else None

    print()
    print(f"{C.PURPLE_BOLD}Desensitize Documents{C.NC}")
    mode_lbl = "可逆占位符" if cfg["mode"] == "placeholder" else f"掩码遮蔽 ({cfg['pdf_style']})"
    print(f"{ICON_ADMIN} 模式：{mode_lbl} | 预设：{cfg['preset']} | 文档：{len(files)} 份" + (" | DRY-RUN" if args.dry_run else ""))

    print_section("处理文档")
    res = apply_pipeline(
        files,
        out_dir=out_dir,
        cfg=cfg,
        previous_mapping=prev,
        log=lambda m: print(f"  {C.GRAY}{m}{C.NC}"),
        dry_run=args.dry_run,
    )

    print_section("校验结果")
    for j in res["jobs"]:
        v = j.get("verify") or {}
        res_list = v.get("residual") or []
        if j["error"]:
            print_err(f"{j['rel']} · 失败：{j['error']}")
        elif not v.get("structure_ok") or res_list:
            print_warn(f"{j['rel']} · {v.get('structure_msg')} · 残留 {len(res_list)} 处: {', '.join(res_list[:4])}")
        else:
            print_ok(f"{j['rel']} · 替换 {len(j['changes'])} 处 · {v.get('structure_msg')} · 残留 0")

    details = [
        f"校验通过：{res['ok']} / {res['total']} 份 · 用时 {res['seconds']}s",
        f"输出目录：{out_dir}",
    ]
    if res["report_html"]:
        details.append(f"内部报告：{res['report_html']}（含原文，勿外发）")
    print_summary_block("Desensitization complete", details)
    return 0 if res["ok"] == res["total"] else 2


def _cmd_restore(args) -> int:
    cfg = _build_cfg(args)
    files = collect_files(args.paths, skip_redacted=False)
    if not files:
        print_err("未找到待还原的文档")
        return 1
    first_src = files[0][0]
    default_out = os.path.join(os.path.dirname(first_src), "还原输出")
    out_dir = os.path.abspath(args.output or default_out)

    print()
    print(f"{C.PURPLE_BOLD}Restore Documents{C.NC}")
    print(f"{ICON_ADMIN} 映射表：{args.mapping} | 文档：{len(files)} 份")
    print_section("还原执行")
    res = restore_pipeline(
        files,
        args.mapping,
        out_dir=out_dir,
        cfg=cfg,
        log=lambda m: print(f"  {C.GRAY}{m}{C.NC}"),
    )
    for w in res["warnings"]:
        print_warn(w)
    for j in res["jobs"]:
        if j["error"]:
            print_err(f"{j['rel']} · {j['error']}")
        else:
            msg = f"{j['rel']} · 还原 {j['restored_count']} 处"
            if j["unmapped_placeholders"]:
                msg += f"（未匹配占位符: {', '.join(j['unmapped_placeholders'][:3])}）"
                print_warn(msg)
            else:
                print_ok(msg)

    print_summary_block(
        "Restore complete",
        [f"成功还原：{res['ok']} / {res['total']} 份 · 用时 {res['seconds']}s", f"输出目录：{out_dir}"],
    )
    return 0 if res["ok"] == res["total"] else 2


def _cmd_gui(args) -> int:
    from desktop import textveil_desktop
    argv = []
    if getattr(args, "browser", False):
        argv.append("--browser")
    if getattr(args, "no_open", False):
        argv.append("--no-open")
    if getattr(args, "port", None):
        argv.append(f"--port={args.port}")
    sys.argv = [sys.argv[0]] + argv
    textveil_desktop.main()
    return 0


def _interactive_prompt_action(action: str) -> int:
    if action == "check":
        return _cmd_check()
    if action == "gui":
        return _cmd_gui(argparse.Namespace(browser=False, no_open=False, port=None))

    path_str = input("请输入待处理的文档或文件夹路径: ").strip().strip("\"'")
    if not path_str:
        print_warn("已取消")
        return 0

    if action == "scan":
        mode = input("策略 [1=可逆占位符(默认) / 2=掩码遮蔽]: ").strip()
        ns = argparse.Namespace(
            paths=[path_str],
            mode="mask" if mode == "2" else "placeholder",
            preset=None,
            config=None,
            keywords=None,
            mapping=None,
            json=False,
        )
        return _cmd_scan(ns)

    if action == "run":
        mode = input("策略 [1=可逆占位符(默认) / 2=掩码遮蔽]: ").strip()
        out = input("输出目录（直接回车则输出到原文件旁「脱敏输出」）: ").strip().strip("\"'") or None
        ns = argparse.Namespace(
            paths=[path_str],
            output=out,
            mode="mask" if mode == "2" else "placeholder",
            pdf_style="replace",
            preset=None,
            config=None,
            keywords=None,
            mapping=None,
            dry_run=False,
        )
        return _cmd_run(ns)

    if action == "restore":
        mp = input("请输入 映射表.json 路径: ").strip().strip("\"'")
        if not mp:
            print_err("必须提供映射表路径")
            return 1
        out = input("还原输出目录（直接回车则输出到原文件旁「还原输出」）: ").strip().strip("\"'") or None
        ns = argparse.Namespace(paths=[path_str], mapping=mp, output=out, config=None)
        return _cmd_restore(ns)

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="doc_desensitize.py",
        description=f"{APP_NAME} v{APP_VERSION} — 本地文档信息脱敏工具 (Word / Excel / PPT / PDF / Markdown)",
    )
    sub = p.add_subparsers(dest="cmd")

    def add_common(sp):
        sp.add_argument("--mode", choices=("placeholder", "mask"), help="脱敏模式：placeholder(可逆占位符) / mask(掩码遮蔽)")
        sp.add_argument("--preset", choices=("standard", "ai", "strict", "meta"), help="规则预设")
        sp.add_argument("-c", "--config", help="自定义 JSON 配置文件路径")
        sp.add_argument("-k", "--keywords", help="补充敏感词，逗号分隔（支持 原词=替换词、re:正则）")
        sp.add_argument("-m", "--mapping", help="复用历史 映射表.json 保持代号一致")

    sp_scan = sub.add_parser("scan", help="只扫描并预览识别到的敏感信息")
    sp_scan.add_argument("paths", nargs="+", help="文档或文件夹路径")
    sp_scan.add_argument("--json", action="store_true", help="输出 JSON 格式结果")
    add_common(sp_scan)

    sp_run = sub.add_parser("run", help="执行文档脱敏与校验")
    sp_run.add_argument("paths", nargs="+", help="文档或文件夹路径")
    sp_run.add_argument("-o", "--output", help="输出目录（默认放在原文件旁 脱敏输出/）")
    sp_run.add_argument("--pdf-style", choices=("replace", "blackbox"), help="PDF 替换样式：replace(白底替换) / blackbox(纯黑涂黑)")
    sp_run.add_argument("--dry-run", "-n", action="store_true", help="仅预览，不写出文件")
    add_common(sp_run)

    sp_res = sub.add_parser("restore", help="根据可逆映射表还原脱敏文档")
    sp_res.add_argument("paths", nargs="+", help="待还原的脱敏文档或文件夹路径")
    sp_res.add_argument("-m", "--mapping", required=True, help="映射表.json 路径")
    sp_res.add_argument("-o", "--output", help="输出目录（默认 还原输出/）")
    sp_res.add_argument("-c", "--config", help="自定义配置文件路径")

    sp_gui = sub.add_parser("gui", help="启动图形界面")
    sp_gui.add_argument("--browser", action="store_true", help="强制在浏览器中打开界面")
    sp_gui.add_argument("--port", type=int, help="浏览器模式监听端口")
    sp_gui.add_argument("--no-open", action="store_true", help="浏览器模式下不自动弹出浏览器")

    sub.add_parser("check", help="检查 5 类格式引擎与运行环境")

    sp_init = sub.add_parser("init-config", help="导出默认配置模板 JSON")
    sp_init.add_argument("path", nargs="?", default="脱敏配置示例.json", help="输出路径")

    return p


def main():
    parser = build_parser()
    if len(sys.argv) == 1:
        if sys.stdin.isatty() and sys.stdout.isatty():
            rc = interactive_menu(
                {
                    "scan": lambda: _interactive_prompt_action("scan"),
                    "run": lambda: _interactive_prompt_action("run"),
                    "restore": lambda: _interactive_prompt_action("restore"),
                    "gui": lambda: _interactive_prompt_action("gui"),
                    "check": lambda: _interactive_prompt_action("check"),
                }
            )
            sys.exit(rc)
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()
    if args.cmd == "check":
        sys.exit(_cmd_check())
    if args.cmd == "scan":
        sys.exit(_cmd_scan(args))
    if args.cmd == "run":
        sys.exit(_cmd_run(args))
    if args.cmd == "restore":
        sys.exit(_cmd_restore(args))
    if args.cmd == "gui":
        sys.exit(_cmd_gui(args))
    if args.cmd == "init-config":
        with open(args.path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        print_ok(f"已导出默认配置模板：{args.path}")
        sys.exit(0)
    parser.print_help()


if __name__ == "__main__":
    main()
