#!/bin/bash
cd "$(dirname "$0")"
if [ -x "./.venv/bin/python3" ]; then
  exec "./.venv/bin/python3" desktop/textveil_desktop.py "$@"
elif command -v uv >/dev/null 2>&1; then
  exec uv run python desktop/textveil_desktop.py "$@"
elif command -v python3 >/dev/null 2>&1; then
  exec python3 desktop/textveil_desktop.py "$@"
else
  osascript -e 'display alert "需要 Python 3" message "请先安装 Python 3.11-3.14 或运行 uv venv .venv && uv pip install -r requirements.txt。"'
fi
