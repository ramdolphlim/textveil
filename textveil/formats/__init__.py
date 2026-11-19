"""多格式文档处理器分发与运行环境检查。"""

import os
from . import word_handler, excel_handler, ppt_handler, md_handler

try:  # PDF 依赖 PyMuPDF；网页版（浏览器）里没有，其余格式照常可用
    from . import pdf_handler
except ImportError:
    pdf_handler = None

PDF_UNAVAILABLE = "当前环境没有 PDF 引擎（PyMuPDF）：网页版暂不支持 PDF，请使用桌面版"

_DISPATCH = {
    ".docx": word_handler,
    ".xlsx": excel_handler,
    ".xlsm": excel_handler,
    ".pptx": ppt_handler,
    ".pdf": pdf_handler,
    ".md": md_handler,
    ".markdown": md_handler,
    ".txt": md_handler,
}


def handler_for(path: str):
    ext = os.path.splitext(path)[1].lower()
    h = _DISPATCH.get(ext)
    if ext == ".pdf" and pdf_handler is None:
        raise ValueError(PDF_UNAVAILABLE)
    if h is None:
        raise ValueError(f"不支持的文件格式：{ext or '(无扩展名)'}")
    return h


def scan_file(path: str, det, findings, fname: str) -> dict:
    return handler_for(path).scan_file(path, det, findings, fname)


def apply_file(path: str, out_path: str, mapping: dict, cfg: dict) -> dict:
    return handler_for(path).apply_file(path, out_path, mapping, cfg)


def restore_file(path: str, out_path: str, inv_regex, inv_map: dict, cfg: dict) -> dict:
    return handler_for(path).restore_file(path, out_path, inv_regex, inv_map, cfg)


def verify_file(src_path: str, out_path: str, check_terms: list[str]) -> dict:
    return handler_for(src_path).verify_file(src_path, out_path, check_terms)


def check_environment() -> dict:
    """检查 5 种文档格式引擎、PDF 中文字体与桌面窗口支持状态。"""
    engines = {}
    for key, mod in (
        ("word", "docx"),
        ("excel", "openpyxl"),
        ("ppt", "pptx"),
        ("pdf", "pymupdf"),
        ("xml", "lxml"),
    ):
        try:
            __import__(mod)
            engines[key] = True
        except Exception:
            engines[key] = False
    engines["markdown"] = True

    try:
        __import__("webview")
        has_webview = True
    except Exception:
        has_webview = False

    font_name, font_path = pdf_handler.pick_cjk_font() if pdf_handler else ("", None)
    return {
        "engines": engines,
        "all_ready": all(engines.values()),
        "pdf_font_name": font_name,
        "pdf_font_path": font_path or "PyMuPDF built-in china-s",
        "webview": has_webview,
    }
