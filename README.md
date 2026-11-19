<p align="center"><img src="assets/logo/icon-1024.png" width="112" alt="文隐 TextVeil"></p>

<h1 align="center">文隐 TextVeil</h1>

<p align="center">文档信息脱敏工具 · Word / Excel / PPT / PDF / Markdown · 本地处理，文档不上传</p>

<p align="center">
  <a href="https://textveil.limch.cc"><b>在线使用</b></a> ·
  <a href="https://github.com/peter804762649-ux/textveil/releases/latest"><b>下载桌面版（Mac / Windows）</b></a> ·
  <a href="https://github.com/peter804762649-ux/drawveil">姊妹工具：图隐 DrawVeil（CAD 图纸脱敏）</a>
</p>

---

文隐会找出文档里的人名、电话、身份证、公司、金额、API Key、内网地址等敏感信息，替换成可还原的占位符（如 `[姓名_01]`）或不可逆的掩码（如 `138****5678`），并清掉作者、批注、修订记录等隐藏信息。适合把文档交给 AI、外包或客户之前先「过一遍」。

| | 网页版 | 桌面版 |
|---|---|---|
| 打开方式 | 浏览器访问 [textveil.limch.cc](https://textveil.limch.cc) | 安装包，双击运行 |
| 文档去哪了 | 只在浏览器内存里处理，**不会上传**到任何服务器 | 只在本机处理，不联网 |
| Word / Excel / PPT / Markdown | ✓ | ✓ |
| PDF | —（浏览器里没有 PDF 引擎） | ✓ |
| 映射表还原 | ✓（刷新页面前请先下载 `映射表.json`） | ✓（自动按批次保存） |
| 监视文件夹自动脱敏、固定输出目录 | — | ✓ |

## 核心特性

1. **双模式自由切换（支持一键还原）**
   - **可逆占位符**：如 `[姓名_01]`、`[手机_01]`、`[企业_01]`、`[密钥_01]`，输出 `映射表.json` 与 `映射表.csv`，脱敏文档交给 AI 处理或外包协作后，可在「还原」页面或 CLI 一键回填原文。
   - **不可逆掩码遮蔽**：格式感知打码（如 `138****5678`、`张*`、`z***@***.com`、`110101********1234`、`sk-************`），PDF 支持**白底覆写**与**纯黑涂黑条**两种模式（底层文字指令物理擦除，无法复制选中还原）。

2. **四维敏感信息识别与隐藏痕迹清理**
   - **个人隐私 PII**：手机号、座机号、18 位身份证（含 GB 11643-1999 校验位）、护照、银行卡（Luhn 校验）、邮箱、中文/英文姓名（含行内标签、表格列头与跨 Run 拆分识别）、通讯地址。
   - **企业与商业**：中英文单位名称、18 位统一社会信用代码（含 GB 32100-2015 校验位）、明确币种/金额、项目与合同编号、对公账号、自定义词库与正则（`re:...`）。
   - **技术凭证与密钥**：OpenAI / Anthropic / GitHub / AWS / 阿里云 / 腾讯云等 API Key、JWT、PEM 私钥、键值密码、IPv4/IPv6、数据库连接串、内网域名及本机用户路径（`/Users/...`、`C:\Users\...`）、Markdown 代码块扫描。
   - **文档隐藏元数据**：作者/公司/修改人属性、PDF Info/XMP、Word/Excel/PPT/PDF 批注、Word 修订记录（彻底清除 `<w:del>` 被删原文）、Excel 隐藏工作表、外部超链接、内嵌缩略图、YAML Frontmatter。

3. **自动化双校验**
   - 每份输出文档均验证格式可读性与结构完整性（段落/可见工作表/幻灯片/PDF 页数/文本行数），并二次全量扫描确认敏感原文 **0 残留**。

---

## 下载桌面版

到 [Releases](https://github.com/peter804762649-ux/textveil/releases/latest) 下载：

| 系统 | 文件 |
|---|---|
| macOS（Apple 芯片 M1/M2/M3/M4） | `TextVeil-*-mac-arm64.dmg` |
| macOS（Intel 芯片） | `TextVeil-*-mac-intel.dmg` |
| Windows 10 / 11 | `TextVeil-*-win-x64-setup.exe`（安装版）或 `*-portable.zip`（免安装） |

程序没有开发者签名，第一次打开：
- **macOS**：在「应用程序」里右键「文隐」→ 打开；如提示“已损坏”，在终端执行 `xattr -cr /Applications/文隐.app`
- **Windows**：出现“Windows 已保护你的电脑”时，点“更多信息”→“仍要运行”

## 从源码运行

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python desktop/textveil_desktop.py            # 桌面窗口
.venv/bin/python desktop/textveil_desktop.py --browser  # 或者在本机浏览器里打开
```

macOS 也可以直接双击 `启动脱敏工具.command`，Windows 双击 `启动脱敏工具.bat`。

### 命令行用法（Mole 交互菜单与批处理）

```bash
# 打开 Mole 交互式终端菜单（↑↓ 方向键选择）
.venv/bin/python doc_desensitize.py

# 检查 5 类格式引擎与字体状态
.venv/bin/python doc_desensitize.py check

# 仅扫描预览，不改文件
.venv/bin/python doc_desensitize.py scan 样例文档/

# 可逆占位符模式批量脱敏（默认生成 脱敏输出/ 与 _脱敏报告(含原文,勿外发)/）
.venv/bin/python doc_desensitize.py run 样例文档/ --mode placeholder -o 输出/

# 不可逆掩码模式 + PDF 纯黑涂黑
.venv/bin/python doc_desensitize.py run 样例文档/ --mode mask --pdf-style blackbox -o 输出_掩码/

# 使用映射表一键还原脱敏文档
.venv/bin/python doc_desensitize.py restore 输出/ -m "输出/_脱敏报告(含原文,勿外发)/映射表.json" -o 还原输出/
```

---

## 目录结构

```text
textveil/                   脱敏引擎（桌面版、网页版、命令行共用）
  detectors.py              校验位验证与上下文敏感信息检测
  masking.py                可逆占位符 / 格式感知掩码与逆向映射
  pipeline.py               扫描、执行、校验与 HTML/CSV/JSON 报告
  formats/                  Word / Excel / PPT / PDF / Markdown 处理器
doc_desensitize.py          命令行与终端交互菜单入口
desktop/                    桌面版：pywebview 窗口 + 界面（ui/）+ 打包脚本
web/                        网页版：在浏览器里用 Pyodide 运行同一套引擎
tests/                      样例生成与全流程回归测试
.github/workflows/          CI、网页版构建、打 tag 自动发布安装包
```

## 开发与发布

- **测试**：`python tests/run_tests.py`（需要 PyMuPDF）；网页版引擎：`python web/build_web.py && python tests/test_web_engine.py`
- **网页版**：推送到 `main` 后，GitHub Actions 会自动构建 `web/dist` 并更新 `site` 分支，Cloudflare Worker 从该分支取文件，在 textveil.limch.cc 提供页面。见 [web/README.md](web/README.md)
- **桌面版**：推送 `v*` 标签（例如 `git tag v1.0.1 && git push --tags`），GitHub Actions 自动打包 Mac（Apple 芯片 / Intel）和 Windows 安装包并发布到 Releases。本机打包见 [desktop/README.md](desktop/README.md)

## 许可证

本项目代码以 [MIT](LICENSE) 许可证开源。

桌面安装包内含第三方组件，各自遵循其许可证，其中 **PyMuPDF / MuPDF 为 [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html)**（用于处理 PDF）。分发或修改安装包时请同时遵守 AGPL-3.0：本仓库公开了全部源码与构建脚本，即为对应的完整源代码。网页版不包含 PyMuPDF。

> ⚠ **安全提示**：`脱敏报告.html` 与 `映射表.json` / `映射表.csv` 内含脱敏前原文，仅限内部留存或逆向还原使用，切勿随脱敏文档一同外发！
