#!/bin/bash
# 文隐 TextVeil · macOS 本机打包：双击运行，生成 dist/TextVeil-mac.dmg
set -e
cd "$(dirname "$0")"
echo "== 文隐 TextVeil · 打包 macOS 版 =="
PY=$(command -v python3 || true)
if [ -z "$PY" ]; then echo "没有找到 python3。请先安装：https://www.python.org/downloads/macos/"; read -p "按回车退出"; exit 1; fi
V=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' ../textveil/__init__.py)
[ -d .venv ] || "$PY" -m venv .venv
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
rm -rf build dist
pyinstaller --noconfirm --clean --windowed --name "文隐" \
  --icon assets/icon.icns \
  --osx-bundle-identifier cc.limch.textveil \
  --add-data "ui:ui" --paths .. --collect-submodules textveil \
  textveil_desktop.py
PL="dist/文隐.app/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string 文隐 TextVeil" "$PL" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $V" "$PL" 2>/dev/null || /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $V" "$PL"
/usr/libexec/PlistBuddy -c "Add :NSHighResolutionCapable bool true" "$PL" 2>/dev/null || true
# 未签名：去掉隔离标记并做临时签名，避免“已损坏”提示
xattr -cr "dist/文隐.app" || true
codesign --force --deep --sign - "dist/文隐.app" 2>/dev/null || true
mkdir -p dist/dmg && cp -R "dist/文隐.app" dist/dmg/ && ln -s /Applications dist/dmg/应用程序
hdiutil create -quiet -volname "文隐 TextVeil" -srcfolder dist/dmg -ov -format UDZO "dist/TextVeil-$V-mac.dmg"
rm -rf dist/dmg
echo
echo "完成：$(pwd)/dist/TextVeil-$V-mac.dmg"
echo "首次打开：在“应用程序”里右键「文隐」→ 打开（程序没有 Apple 开发者签名）。"
open dist
read -p "按回车关闭"
