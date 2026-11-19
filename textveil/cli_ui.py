"""Mole 风格终端界面组件（配色、图标、横幅、进度摘要块与键盘交互菜单）。"""

import os
import shutil
import sys
import termios
import tty
from . import APP_NAME, APP_VERSION


def _use_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty()


class Colors:
    def __init__(self):
        on = _use_color()
        self.GREEN = "\033[0;32m" if on else ""
        self.BLUE = "\033[1;34m" if on else ""
        self.CYAN = "\033[0;36m" if on else ""
        self.YELLOW = "\033[0;33m" if on else ""
        self.PURPLE = "\033[0;35m" if on else ""
        self.PURPLE_BOLD = "\033[1;35m" if on else ""
        self.RED = "\033[0;31m" if on else ""
        self.GRAY = "\033[0;38;5;244m" if on else ""
        self.BOLD = "\033[1m" if on else ""
        self.NC = "\033[0m" if on else ""


C = Colors()

ICON_ARROW = "➤"
ICON_OK = "✓"
ICON_WARN = "◎"
ICON_ERR = "✗"
ICON_SOLID = "●"
ICON_EMPTY = "○"
ICON_ADMIN = "⚙"
ICON_SUB = "↳"


def show_brand_banner():
    art = [
        "  ____             __     __   _ _ ",
        " |  _ \\  ___   ___ \\ \\   / /__(_) |",
        " | | | |/ _ \\ / __| \\ \\ / / _ \\ | |",
        " | |_| | (_) | (__   \\ V /  __/ | |",
        " |____/ \\___/ \\___|   \\_/ \\___|_|_|",
    ]
    for line in art:
        print(f"{C.PURPLE_BOLD}{line}{C.NC}")
    print(f"  {C.BOLD}{APP_NAME}{C.NC} {C.GRAY}v{APP_VERSION} · Word · Excel · PPT · PDF · Markdown 本地脱敏{C.NC}")


def print_section(title: str):
    print(f"\n{C.CYAN}{ICON_ARROW} {title}{C.NC}")


def print_ok(msg: str):
    print(f"  {C.GREEN}{ICON_OK}{C.NC} {msg}")


def print_warn(msg: str):
    print(f"  {C.YELLOW}{ICON_WARN}{C.NC} {msg}")


def print_err(msg: str):
    print(f"  {C.RED}{ICON_ERR}{C.NC} {msg}")


def print_summary_block(heading: str, details: list[str]):
    cols = shutil.get_terminal_size((70, 24)).columns
    width = min(max(cols, 40), 70)
    divider = "=" * width
    print()
    print(divider)
    if heading:
        print(f"{C.BLUE}{heading}{C.NC}")
    for line in details:
        if line:
            print(line)
    print(divider)


def _read_key() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            if seq == "[A":
                return "UP"
            if seq == "[B":
                return "DOWN"
            return "QUIT"
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch in ("k", "K"):
            return "UP"
        if ch in ("j", "J"):
            return "DOWN"
        if ch in ("q", "Q", "\x03"):
            return "QUIT"
        if ch in ("1", "2", "3", "4", "5"):
            return f"NUM:{ch}"
        return "OTHER"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def interactive_menu(handlers: dict):
    """Mole 风格终端主菜单（↑↓ / jk / 数字键选择，Enter 确认，Q 退出）。"""
    options = [
        ("1", "Scan        扫描文档并预览敏感信息", "scan"),
        ("2", "Desensitize 批量脱敏（可逆占位符 / 掩码遮蔽）", "run"),
        ("3", "Restore     依据映射表一键还原占位符文档", "restore"),
        ("4", "Desktop UI  打开图形界面（拖拽核对与报告）", "gui"),
        ("5", "Status      检查五类格式引擎与当前规则", "check"),
    ]
    selected = 0

    def draw():
        sys.stdout.write("\033[2J\033[H")
        print()
        show_brand_banner()
        print()
        for idx, (num, text, _) in enumerate(options):
            if idx == selected:
                print(f"{C.CYAN}{ICON_ARROW} {num}. {text}{C.NC}")
            else:
                print(f"  {num}. {text}")
        print()
        print(f"{C.GRAY}↑↓  |  Enter 确认  |  1-5 快捷启动  |  Q 退出{C.NC}")
        sys.stdout.flush()

    while True:
        draw()
        key = _read_key()
        if key == "UP":
            selected = max(0, selected - 1)
        elif key == "DOWN":
            selected = min(len(options) - 1, selected + 1)
        elif key == "QUIT":
            print()
            return 0
        elif key == "ENTER" or key.startswith("NUM:"):
            idx = int(key.split(":")[1]) - 1 if key.startswith("NUM:") else selected
            action = options[idx][2]
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.flush()
            fn = handlers.get(action)
            if fn:
                return fn()
            return 0
