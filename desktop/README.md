# 文隐 TextVeil · 桌面版

pywebview 原生窗口 + 本地界面（`ui/`），脱敏引擎在仓库根目录的 `textveil/`。支持 Word / Excel / PPT / PDF / Markdown。

## 直接运行（开发）

```bash
pip install -r requirements.txt
python textveil_desktop.py            # 原生窗口
python textveil_desktop.py --browser  # 在本机浏览器里打开
```

## 打包安装包

- **自动（推荐）**：推送 `v*` 标签，GitHub Actions 的 `release` 工作流会打包 Mac（Apple 芯片 / Intel 各一个 `.dmg`）和 Windows（安装版 `.exe` + 免安装 `.zip`），并发布到 Releases。
- **本机 macOS**：双击 `build_mac.command`，生成 `dist/TextVeil-<版本>-mac.dmg`。
- **本机 Windows**：双击 `build_win.bat`；装了 [Inno Setup 6](https://jrsoftware.org/isdl.php) 会同时生成安装程序。

版本号取自 `textveil/__init__.py` 的 `APP_VERSION`（打 tag 发布时自动改成 tag 的版本）。

设置和批次记录保存在：macOS `~/Library/Application Support/TextVeil/`，Windows `%APPDATA%\TextVeil\`（旧版 DocVeil 的设置会自动迁移过来）。
