"""文隐 TextVeil — 本地多格式文档信息脱敏工具。"""

APP_NAME = "文隐 TextVeil"
APP_VERSION = "1.0.1"

SUPPORTED_EXTS = (
    ".docx",
    ".xlsx",
    ".xlsm",
    ".pptx",
    ".pdf",
    ".md",
    ".markdown",
    ".txt",
)

FORMAT_LABELS = {
    ".docx": "Word",
    ".xlsx": "Excel",
    ".xlsm": "Excel",
    ".pptx": "PPT",
    ".pdf": "PDF",
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".txt": "文本",
}
